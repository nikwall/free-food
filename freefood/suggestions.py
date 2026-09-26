"""Suggestions from fellows (the website's Suggest form) -> events on the map.

Fellows suggest either
  - an event: a link to its page, plus an optional note ("pizza, open to all"), or
  - a source: a newsletter or calendar, with an optional link.
The site stores suggestions in the Supabase table `suggestions` (hosting/supabase.sql); the scanner
reads them with the site's public key, so no secret is needed.

At each scan:
  1. Links on Harvard-related sites (AUTO_OK) are used right away; other links wait until the
     maintainer ticks `approved` in Supabase (Table Editor -> suggestions).
  2. An event link is read for its event data: schema.org JSON-LD, a linked iCal (.ics) file, or
     the page's title and first date. It then goes through the usual food and audience checks.
     If the page does not mention food, the fellow's note counts as "food reported by a fellow".
  3. A calendar link is read the same way and every event on it is checked like any other source.
     An email newsletter needs a subscription (see inbox/README.txt), so it is only listed.
  4. Each suggestion gets a status that the Suggest page shows ("On the map", "Waiting for review").
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urljoin, urlsplit

import lxml.html
from dateutil import parser as dparser

from .config import ROOT, TZ
from .models import Event
from .sources.newsletters import DATE_RE, _parse_day, _parse_time
from .text import html_to_text, one_line

AUTO_OK = re.compile(r"(^|\.)(harvard\.edu|hbs\.edu|belfercenter\.org|shorensteincenter\.org|"
                     r"harvardartmuseums\.org|harvard-yenching\.org|eventbrite\.com|lu\.ma)$", re.I)
LOC_LABEL = re.compile(r"^(?:location|where|venue|place|room)\s*[:\-]?\s*(.*)$", re.I)


# ---------------------------------------------------------------- reading suggestions
def supabase_config():
    """URL and public key: environment first, else the site's own web/config.js."""
    url, key = os.environ.get("FFM_SUPABASE_URL", ""), os.environ.get("FFM_SUPABASE_KEY", "")
    if not (url and key):
        cfg = (ROOT / "web" / "config.js").read_text(encoding="utf-8")
        url = (re.search(r'supabaseUrl:\s*"([^"]*)"', cfg) or [None, ""])[1]
        key = (re.search(r'supabaseAnonKey:\s*"([^"]*)"', cfg) or [None, ""])[1]
    return url.rstrip("/"), key


def fetch_rows(http, days=60):
    url, key = supabase_config()
    if not (url and key):
        return []
    since = (datetime.now(TZ) - timedelta(days=days)).isoformat()
    headers = {"apikey": key, **({"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {})}
    r = http.s.get(f"{url}/rest/v1/suggestions", headers=headers, timeout=30,
                   params={"select": "*", "created_at": f"gte.{since}", "order": "created_at.desc"})
    r.raise_for_status()
    return r.json()


def norm_url(u):
    """host + path, lower-case host without www, no trailing slash, query or fragment."""
    if not u:
        return ""
    p = urlsplit(u.strip())
    host = p.netloc.lower().removeprefix("www.")
    return host + p.path.rstrip("/")


def accepted(row):
    host = urlsplit(row.get("url") or "").netloc.lower().split(":")[0]
    return bool(row.get("approved")) or bool(host and AUTO_OK.search(host))


# ---------------------------------------------------------------- reading event pages
def _aware(value):
    if not value:
        return None
    dt = value if isinstance(value, datetime) else dparser.parse(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "subEvent", "itemListElement", "item", "event", "events"):
            if k in node:
                yield from _walk(node[k])


def _jsonld_location(loc):
    if isinstance(loc, list):
        loc = loc[0] if loc else ""
    if isinstance(loc, str):
        return loc
    if isinstance(loc, dict):
        addr = loc.get("address") or ""
        if isinstance(addr, dict):
            addr = ", ".join(str(addr.get(k, "")) for k in ("streetAddress", "addressLocality") if addr.get(k))
        return ", ".join(x for x in (loc.get("name", ""), addr) if x)
    return ""


def _from_jsonld(item, page_url):
    types = item.get("@type")
    types = types if isinstance(types, list) else [types]
    if not any(isinstance(t, str) and t.endswith("Event") for t in types) or not item.get("startDate"):
        return None
    mode = str(item.get("eventAttendanceMode", ""))
    return {"title": one_line(str(item.get("name", ""))), "start": _aware(item["startDate"]),
            "end": _aware(item.get("endDate")), "location": one_line(_jsonld_location(item.get("location"))),
            "description": html_to_text(str(item.get("description", ""))),
            "url": item.get("url") if isinstance(item.get("url"), str) else page_url,
            "online": "OnlineEventAttendanceMode" in mode}


def _ics_events(text, page_url):
    text = re.sub(r"\r?\n[ \t]", "", text)                      # unfold continuation lines
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in block.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                f.setdefault(k.split(";")[0].upper(), (k, v))
        def val(name):
            return f.get(name, ("", ""))[1].replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
        def when(name):
            k, v = f.get(name, ("", ""))
            if not v:
                return None
            dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S") if "T" in v else datetime.strptime(v[:8], "%Y%m%d")
            return dt.replace(tzinfo=timezone.utc if v.endswith("Z") else TZ)
        start = when("DTSTART")
        if start and val("SUMMARY"):
            out.append({"title": one_line(val("SUMMARY")), "start": start, "end": when("DTEND"),
                        "location": one_line(val("LOCATION")), "description": val("DESCRIPTION"),
                        "url": val("URL") or page_url, "online": False})
    return out


def _single_event(doc, page_url):
    """Fallback for pages without structured data: title plus the first date in the main text."""
    title = (doc.xpath('//meta[@property="og:title"]/@content') or doc.xpath("//h1//text()")
             or doc.xpath("//title/text()") or [""])[0]
    main = (doc.xpath("//main") or doc.xpath("//article") or doc.xpath("//body") or [doc])[0]
    for bad in main.xpath(".//script|.//style|.//nav|.//header|.//footer"):
        bad.drop_tree()
    text = html_to_text(lxml.html.tostring(main, encoding="unicode"))
    lines = [ln for ln in text.split("\n") if ln.strip()]
    today = datetime.now(TZ).date()
    # month-name dates ("Sept. 29") first; bare numbers like 9/29 only if no such line exists
    candidates = [(i, ln, DATE_RE.search(ln)) for i, ln in enumerate(lines[:250]) if len(ln) <= 160]
    candidates = [c for c in candidates if c[2]]
    candidates.sort(key=lambda c: (not re.search(r"[A-Za-z]", c[2].group(0)), c[0]))
    for i, ln, m in candidates:
        day = _parse_day(m.group(0), today)
        if not day:
            continue
        # pages often split "5–7pm" across elements, so read the date line together with the next ones
        hm = _parse_time(" ".join(lines[i:i + 2])) or _parse_time(" ".join(lines[i:i + 3]))
        loc = ""
        for x in lines[i:i + 8]:
            lm = LOC_LABEL.match(x)
            if lm:
                loc = lm.group(1) or ""
                break
        start = datetime(day.year, day.month, day.day, *(hm or (12, 0)), tzinfo=TZ)
        return {"title": one_line(re.sub(r"\s+\|\s+[^|]*$", "", title) or title), "start": start, "end": None,
                "location": one_line(loc), "description": "\n".join(lines[i:i + 60]), "url": page_url,
                "online": False, "all_day": hm is None}
    return None


def events_from_page(page_url, html, http):
    doc = lxml.html.fromstring(html)
    found = []
    for raw in doc.xpath('//script[@type="application/ld+json"]/text()'):
        raw = re.sub(r"/\*\s*<!\[CDATA\[\s*\*/|/\*\s*\]\]>\s*\*/|<!\[CDATA\[|\]\]>", "", raw)   # LiveWhale wraps it
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        found += [e for e in (_from_jsonld(x, page_url) for x in _walk(data)) if e]
    if found:
        return found
    for href in doc.xpath("//a/@href | //link/@href"):
        try:
            if href.startswith("data:text/calendar"):
                return _ics_events(unquote(href.split(",", 1)[1]), page_url)
            if re.search(r"\.ics(\?|$)|[?&](ical|outlook-ical)=", href, re.I):
                return _ics_events(http.get_text(urljoin(page_url, href), cache=True), page_url)
        except Exception:
            continue
    one = _single_event(doc, page_url)
    return [one] if one else []


# ---------------------------------------------------------------- scan-time processing
def _event(d, row, source_name):
    note = one_line(row.get("note") or "")
    desc = d["description"] + (f"\nA fellow's note: {note}." if note else "")
    return Event(source_id="suggested", source_name=source_name, title=d["title"] or one_line(row.get("title") or ""),
                 url=d["url"] or row.get("url", ""), start=d["start"], end=d.get("end"), all_day=d.get("all_day", False),
                 location=d.get("location", ""), description=desc, online=d.get("online", False),
                 extra={"suggestion_id": row["id"]})


def collect(http, log=print):
    """-> (plan, events): one plan entry per suggestion, and the events read from their links."""
    rows = fetch_rows(http)
    plan, events = [], []
    for row in rows:
        item = {"row": row, "keys": {norm_url(row.get("url"))} - {""}, "extracted": [], "state": ""}
        plan.append(item)
        by = one_line(row.get("name") or "")
        if not row.get("url"):
            item["state"] = "no_link"
            continue
        if not accepted(row):
            item["state"] = "review"
            continue
        try:
            html = http.get_text(row["url"], cache=True)
            found = events_from_page(row["url"], html, http)
        except Exception as ex:
            item["state"], item["error"] = "unreadable", f"{type(ex).__name__}"
            continue
        if row["kind"] == "event":
            # a page with several events (a calendar) was suggested as one event: keep the one it links to
            same = [d for d in found if norm_url(d["url"]) == norm_url(row["url"])]
            found = (same or found)[:1]
            name = f"Suggested by {by}" if by else "Suggested by a fellow"
        else:
            title = one_line(row.get("title") or "") or urlsplit(row["url"]).netloc
            name = f"Suggested calendar: {title}"
        item["extracted"] = found
        item["state"] = "read" if found else "no_date"
        item["keys"] |= {norm_url(d["url"]) for d in found}
        events += [_event(d, row, name) for d in found if d.get("start")]
    log(f"  suggestions  {len(rows)} rows, {sum(p['state'] == 'read' for p in plan)} read, "
        f"{sum(p['state'] == 'review' for p in plan)} waiting for review")
    return plan, events


def _fmt(dt):
    dt = dt.astimezone(TZ)
    return f"{dt:%a %b} {dt.day}, {dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def finalize(events, plan, start, end):
    """Mark suggested events, let a fellow's report stand in for food, and write a status per suggestion."""
    by_url = {}
    for ev in events:
        for u in [ev["url"]] + [a["url"] for a in ev.get("also_listed", [])]:
            by_url.setdefault(norm_url(u), ev)
    out = []
    for item in plan:
        row = item["row"]
        st = {"id": row["id"], "state": item["state"], "label": ""}
        by, note = one_line(row.get("name") or ""), one_line(row.get("note") or "")
        if row["kind"] == "event":
            ev = next((by_url[k] for k in item["keys"] if k in by_url), None)
            if ev:
                ev["suggested"] = {"by": by, "note": note}
                if ev["food"]["status"] == "none":
                    ev["food"] = {"status": "reported", "types": ev["food"]["types"] or ["Food"],
                                  "evidence": note or "A fellow says there is food here.", "cue": "fellow"}
                aud = ev["audience"]
                if ev["food"]["status"] == "byo":
                    st.update(state="byo", label="The page says to bring your own food")
                elif aud["level"] in ("restricted", "likely"):
                    st.update(state="listed_restricted", label=f"Listed, but only for {aud['group'] or 'a specific group'}")
                else:
                    st.update(state="on_map", label=f"On the map: {_fmt(datetime.fromisoformat(ev['start']))}")
                st["event_id"] = ev["id"]
            elif item["state"] == "read":
                when = item["extracted"][0]["start"].astimezone(TZ).date()
                if when > end:
                    st.update(state="later", label=f"Will show up closer to the date ({when:%b %d})")
                elif when < start:
                    st.update(state="past", label="Already over")
                else:
                    st.update(state="skipped", label="Found, but it looks like an exhibition or online event")
        else:
            listed = [by_url.get(norm_url(d["url"])) for d in item["extracted"]]
            n_food = sum(1 for ev in listed if ev and ev["food"]["status"] in ("confirmed", "likely"))
            if item["state"] == "read":
                st.update(state="scanned", label=f"Scanned at every update: {len(item['extracted'])} events found, "
                                                 f"{n_food} with food this week")
            elif item["state"] == "no_link":
                st.update(label="Noted. Newsletters need a subscription before they can be scanned")
            st["n_food"] = n_food
        if not st["label"]:
            st["label"] = {
                "review": "Waiting for review",
                "unreadable": "Couldn't open that page",
                "no_date": "Couldn't find a date on that page",
                "no_link": "Noted",
            }.get(item["state"], "Checked")
        out.append(st)
    return out
