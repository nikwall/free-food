"""Turn free-text event locations into map coordinates.

1. Match the text against the Harvard gazetteer (freefood/places.py).
2. Otherwise, if the text contains a street address, ask OpenStreetMap
   Nominatim (cached in data/geocache.json, bounded to greater Boston).
3. Otherwise leave the event unmapped; it still appears in the list.
"""
import json
import math
import re
import threading
import time

import requests

from .config import DATA_DIR, NOMINATIM_UA
from .places import PLACES

# Greater Boston: anything outside this box is a geocoding mistake.
BBOX = {"south": 42.30, "north": 42.42, "west": -71.20, "east": -71.00}

STREET_RE = re.compile(
    r"\b\d{1,5}[a-z]?\s+(?:[A-Z][\w.'-]*\s+){1,4}"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Way|Pl|Place|Blvd|Dr|Drive|Sq|Square|Ln|Lane|Ct|Court|Pkwy|Terrace|Park)\b\.?",
    re.I)
ONLINE_RE = re.compile(r"^\s*(?:online|virtual|zoom|webinar|livestream|remote|via zoom|zoom webinar|microsoft teams|tbd|tba)\b", re.I)


def nominatim_search(query):
    """One Nominatim lookup, bounded to greater Boston. Returns dict or None."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "limit": 1, "bounded": 1,
                    "viewbox": f"{BBOX['west']},{BBOX['north']},{BBOX['east']},{BBOX['south']}"},
            headers={"User-Agent": NOMINATIM_UA}, timeout=20)
        r.raise_for_status()
        res = r.json()
    except (requests.RequestException, ValueError):
        return None
    if not res:
        return None
    lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
    if not (BBOX["south"] <= lat <= BBOX["north"] and BBOX["west"] <= lon <= BBOX["east"]):
        return None
    return {"lat": lat, "lon": lon, "display_name": res[0].get("display_name", "")}


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_minutes(lat1, lon1, lat2, lon2):
    """Rough walking time: straight-line distance x 1.3 detour factor at 80 m/min."""
    return max(1, round(haversine_m(lat1, lon1, lat2, lon2) * 1.3 / 80))


class Geocoder:
    def __init__(self):
        places_file = DATA_DIR / "places.json"
        self.coords = json.loads(places_file.read_text(encoding="utf-8")) if places_file.exists() else {}
        self.cache_file = DATA_DIR / "geocache.json"
        self.cache = json.loads(self.cache_file.read_text(encoding="utf-8")) if self.cache_file.exists() else {}
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.patterns = []
        for key, name, _queries, aliases in PLACES:
            for alias in aliases:
                rx, only = (alias if isinstance(alias, tuple) else (alias, None))
                self.patterns.append((key, name, re.compile(rx, re.I), only))

    def home(self):
        c = self.coords.get("lippmann", {})
        return {"name": "Lippmann House (Nieman Foundation)", "lat": c.get("lat"), "lon": c.get("lon")}

    def match_place(self, text, source_id=None):
        for key, name, rx, only in self.patterns:
            if only and source_id not in only:
                continue
            if rx.search(text):
                c = self.coords.get(key, {})
                if c.get("lat") is not None:
                    return {"place_key": key, "place_name": name, "lat": c["lat"], "lon": c["lon"],
                            "geo_method": "gazetteer"}
        return None

    def locate(self, location, source_id=None, extra_text=""):
        """location: the event's own location field; extra_text: fallback text (e.g. host name)."""
        location = (location or "").strip()
        if location and ONLINE_RE.search(location):
            return None
        for text in (location, extra_text):
            if text:
                hit = self.match_place(text, source_id)
                if hit:
                    return hit
        m = STREET_RE.search(location)
        if m:
            addr = m.group(0)
            if not re.search(r"cambridge|boston|allston|somerville", location, re.I):
                addr += ", Cambridge, MA"
            elif (city := re.search(r"(cambridge|boston|allston|somerville)", location, re.I)):
                addr += ", " + city.group(1) + ", MA"
            return self._nominatim_cached(addr)
        return None

    def _nominatim_cached(self, addr):
        key = addr.lower()
        with self._lock:
            if key in self.cache:
                hit = self.cache[key]
            else:
                wait = 1.1 - (time.time() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                hit = nominatim_search(addr)
                self._last_call = time.time()
                self.cache[key] = hit
                self.cache_file.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
        if not hit:
            return None
        return {"place_key": None, "place_name": addr.split(",")[0], "lat": hit["lat"], "lon": hit["lon"],
                "geo_method": "address"}
