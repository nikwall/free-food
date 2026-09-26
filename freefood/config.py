"""Paths and settings shared across the package."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
INBOX_DIR = ROOT / "inbox"
WEB_DIR = ROOT / "web"
EVENTS_FILE = DATA_DIR / "events.json"

TZ = ZoneInfo("America/New_York")

# How many days ahead to scan (today + N-1).
DAYS_AHEAD = int(os.environ.get("FFM_DAYS", "8"))

# Several Harvard sites reject non-browser user agents, so the scraper
# presents as a normal browser. Nominatim's policy asks for an app name.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NOMINATIM_UA = "FreeFoodMap/0.1 (Harvard student prototype, local use)"

# Detail pages are cached this long so re-scans are cheap and polite.
PAGE_CACHE_HOURS = float(os.environ.get("FFM_PAGE_CACHE_HOURS", "6"))
