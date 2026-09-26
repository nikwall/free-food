"""Scan all sources -> classify -> geocode -> de-duplicate -> data/events.json."""
import hashlib
import json
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import suggestions
from .audience import detect_audience
from .classify import detect_food, detect_registration
from .config import DATA_DIR, DAYS_AHEAD, EVENTS_FILE, TZ
from .geo import Geocoder, walk_minutes
from .http import Http
from .sources import SOURCES

FOOD_RANK = {"confirmed": 3, "likely": 2, "byo": 1, "none": 0}
# a calendar's default guess ("College calendar -> undergrads") must not override another calendar's
# listing of the same event, so "default" ranks below "none"
BASIS_RANK = {"listing": 4, "text": 3, "inferred": 2, "none": 1, "default": 0}
LEVEL_RANK = {"restricted": 4, "likely": 3, "harvard": 2, "public": 1, "unknown": 0}


STOP = {"the", "a", "an", "and", "of", "in", "on", "for", "with", "to", "at", "by", "ft", "feat", "featuring"}


def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP}


def _same_event(a, b):
    """Same day, and either near-identical titles or same start time with overlapping titles."""
    if a["date"] != b["date"]:
        return False
    ta, tb = _tokens(a["title"]), _tokens(b["title"])
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    minutes_apart = abs(datetime.fromisoformat(a["start"]) - datetime.fromisoformat(b["start"])).total_seconds() / 60
    # calendars sometimes disagree by a few minutes (12:15 vs 12:20); repeated sessions are hours apart
    return (overlap >= 0.9 and minutes_apart <= 60) or (minutes_apart <= 15 and overlap >= 0.5)


def _summary(text, n=320):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def build_record(ev, geo, home):
    local_start = ev.start.astimezone(TZ)
    food = detect_food(ev.title, ev.description, online=ev.online)
    reg = detect_registration(ev.description, ev.extra.get("html", ""), ev.registration_hint, ev.registration_link)
    if ev.lat is not None and ev.lon is not None:
        place = {"place_name": ev.location.split(",")[0], "lat": ev.lat, "lon": ev.lon, "geo_method": "source"}
    else:
        place = geo.locate(ev.location, ev.source_id) if not ev.online else None
        if not place and not ev.online:
            place = geo.locate("", ev.source_id, extra_text=f"{ev.host} {ev.source_name}")
            if place:
                place["geo_method"] = "host"   # building of the organizer: approximate
        if not place and not ev.online and ev.source_id == "suggested":
            place = geo.match_place(ev.description[:800], ev.source_id)   # a building named in the text
            if place:
                place["geo_method"] = "text"
    rec = {
        "id": hashlib.sha1(f"{ev.source_id}|{ev.url}|{ev.start.isoformat()}".encode()).hexdigest()[:12],
        "title": ev.title,
        "url": ev.url,
        "source_id": ev.source_id,
        "source_name": ev.source_name,
        "also_listed": [],
        "aliases": [],
        "suggested": None,          # {"by", "note"} when a fellow suggested it
        "start": local_start.isoformat(),
        "end": ev.end.astimezone(TZ).isoformat() if ev.end else None,
        "date": local_start.date().isoformat(),
        "all_day": ev.all_day,
        "location": ev.location,
        "online": ev.online,
        "host": ev.host,
        "food": food,
        "registration": reg,
        "audience": detect_audience(ev.title, ev.description, ev.source_id, ev.host, ev.extra),
        "summary": _summary(ev.description),
        "notes": ev.extra.get("notes", ""),
        "place_name": place["place_name"] if place else "",
        "lat": round(place["lat"], 6) if place else None,
        "lon": round(place["lon"], 6) if place else None,
        "geo_method": place["geo_method"] if place else None,
        "walk_min": None,
    }
    if place and home.get("lat") is not None:
        rec["walk_min"] = walk_minutes(home["lat"], home["lon"], place["lat"], place["lon"])
    return rec


def merge_duplicates(records):
    """The same talk is often on 2-3 calendars. Keep the richest record, remember the others."""
    groups = []
    for r in records:
        for g in groups:
            if _same_event(g[0], r):
                g.append(r)
                break
        else:
            groups.append([r])
    out = []
    for group in groups:
        group.sort(key=lambda r: (FOOD_RANK[r["food"]["status"]], r["food"].get("cue") == "strong",
                                  r["lat"] is not None, r["registration"]["status"] != "unknown",
                                  len(r["summary"])), reverse=True)
        best = dict(group[0])
        for other in group[1:]:
            listed = {best["source_name"]} | {a["source_name"] for a in best["also_listed"]}
            if other["source_name"] not in listed:
                best["also_listed"].append({"source_name": other["source_name"], "url": other["url"]})
            if best["lat"] is None and other["lat"] is not None:
                for k in ("place_name", "lat", "lon", "geo_method", "walk_min", "location"):
                    best[k] = other[k]
            if best["registration"]["status"] == "unknown" and other["registration"]["status"] != "unknown":
                best["registration"] = other["registration"]
        # audience: the most authoritative statement wins (a listing field beats a sentence beats a guess);
        # between equally authoritative ones, the more restrictive
        best["audience"] = max((r["audience"] for r in group),
                               key=lambda a: (BASIS_RANK[a["basis"]], LEVEL_RANK[a["level"]]))
        # votes are keyed by id, so a merged event keeps the same id whichever record is "best"
        ids = sorted(r["id"] for r in group)
        best["id"], best["aliases"] = ids[0], ids[1:]
        out.append(best)
    return out


def run_scan(days=DAYS_AHEAD, only=None, log=print):
    t0 = time.time()
    today = datetime.now(TZ).date()
    start, end = today, today + timedelta(days=days - 1)
    http, geo = Http(), Geocoder()
    home = geo.home()
    sources = [s for s in SOURCES if not only or s.id in only]

    def run(src):
        t = time.time()
        try:
            evs = src.fetch(start, end, http)
            return src, evs, None, time.time() - t
        except Exception as ex:  # one broken site must not stop the scan
            return src, [], f"{type(ex).__name__}: {ex}", time.time() - t

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, sources))

    records, status = [], []
    for src, evs, err, secs in results:
        kept = []
        for ev in evs:
            if ev.canceled or not ev.title:
                continue
            if ev.end and (ev.end - ev.start) > timedelta(hours=14):
                continue          # exhibitions and multi-day programs are not meals
            if not (start <= ev.start.astimezone(TZ).date() <= end):
                continue
            try:
                kept.append(build_record(ev, geo, home))
            except Exception:
                log(f"  ! could not process '{ev.title[:60]}' from {src.id}:\n{traceback.format_exc(limit=2)}")
        records += kept
        n_food = sum(r["food"]["status"] in ("confirmed", "likely") for r in kept)
        status.append({"id": src.id, "name": src.name, "homepage": src.homepage, "ok": err is None,
                       "error": err, "n_events": len(kept), "n_food": n_food, "seconds": round(secs, 1)})
        log(f"  {src.id:12s} {'ok ' if err is None else 'ERR'} {len(kept):4d} events, {n_food:3d} with food"
            f"  ({secs:.0f}s){'  ' + err if err else ''}")

    # fellows' suggestions from the website: read their links, check them like everything else
    plan, t = [], time.time()
    try:
        plan, sugg_events = suggestions.collect(http, log=log)
        kept = [build_record(ev, geo, home) for ev in sugg_events if not ev.canceled and ev.title
                and not (ev.end and (ev.end - ev.start) > timedelta(hours=14))
                and start <= ev.start.astimezone(TZ).date() <= end]
        records += kept
        status.append({"id": "suggested", "name": "Suggestions from fellows", "homepage": "", "ok": True,
                       "error": None, "n_events": len(kept),
                       "n_food": sum(r["food"]["status"] in ("confirmed", "likely") for r in kept),
                       "seconds": round(time.time() - t, 1)})
    except Exception as ex:
        log(f"  suggestions  ERR {type(ex).__name__}: {ex}")
        status.append({"id": "suggested", "name": "Suggestions from fellows", "homepage": "", "ok": False,
                       "error": f"{type(ex).__name__}: {ex}", "n_events": 0, "n_food": 0, "seconds": 0})

    events = merge_duplicates(records)
    events.sort(key=lambda r: (r["start"], r["title"]))
    try:
        sugg_status = suggestions.finalize(events, plan, start, end) if plan else []
    except Exception:           # suggestion statuses are a nice-to-have; never lose the scan over them
        log(f"  ! suggestion statuses failed:\n{traceback.format_exc(limit=3)}")
        sugg_status = []
    payload = {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "home": home,
        "sources": status,
        "stats": {"events": len(events),
                  "food_confirmed": sum(e["food"]["status"] == "confirmed" for e in events),
                  "food_likely": sum(e["food"]["status"] == "likely" for e in events),
                  "food_restricted": sum(e["food"]["status"] in ("confirmed", "likely")
                                         and e["audience"]["level"] == "restricted" for e in events),
                  "seconds": round(time.time() - t0, 1)},
        "events": events,
        "suggestions": sugg_status,
    }
    DATA_DIR.mkdir(exist_ok=True)
    tmp = EVENTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(EVENTS_FILE)
    s = payload["stats"]
    log(f"  => {s['events']} unique events, {s['food_confirmed']} confirmed + {s['food_likely']} likely food "
        f"events, written to {EVENTS_FILE.name} in {s['seconds']}s")
    return payload
