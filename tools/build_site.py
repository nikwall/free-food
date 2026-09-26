"""Assemble the static website in site/ for GitHub Pages (or any static host).

site/ = everything in web/ + the latest data/events.json. The GitHub Actions workflow
(.github/workflows/pages.yml) runs this after each scan and publishes site/.

Refuses to build (exit code 1) when the scan looks broken, so the site keeps yesterday's list
instead of showing an empty one.

    python tools/build_site.py [--min-events 150] [--ping-votes]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
WEB, DATA, SITE = ROOT / "web", ROOT / "data", ROOT / "site"


def check_scan(min_events):
    data = json.loads((DATA / "events.json").read_text(encoding="utf-8"))
    n, ok = data["stats"]["events"], [s["id"] for s in data["sources"] if s["ok"]]
    failed = [f'{s["id"]}: {s["error"]}' for s in data["sources"] if not s["ok"]]
    print(f"scan: {n} events, sources ok: {', '.join(ok)}" + (f"; FAILED: {failed}" if failed else ""))
    if n < min_events or not ({"hls", "hks"} & set(ok)):
        print(f"refusing to publish: fewer than {min_events} events or both HLS and HKS failed")
        return False
    return True


def ping_votes():
    """Touch the Supabase votes table so a free project isn't paused for inactivity."""
    cfg = (WEB / "config.js").read_text(encoding="utf-8")
    url = re.search(r'supabaseUrl:\s*"([^"]*)"', cfg).group(1)
    key = re.search(r'supabaseAnonKey:\s*"([^"]*)"', cfg).group(1)
    if not (url and key):
        print("votes: not configured (config.js empty), skipping ping")
        return
    r = requests.get(url.rstrip("/") + "/rest/v1/votes?select=event_id&limit=1",
                     headers={"apikey": key, **({"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {})},
                     timeout=30)
    print(f"votes: Supabase answered {r.status_code}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-events", type=int, default=150)
    ap.add_argument("--ping-votes", action="store_true")
    args = ap.parse_args()
    if not check_scan(args.min_events):
        return 1
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(WEB, SITE)
    shutil.copy2(DATA / "events.json", SITE / "events.json")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")     # serve files as-is, no Jekyll processing
    print(f"built {SITE.relative_to(ROOT)}/ ({sum(1 for _ in SITE.rglob('*') if _.is_file())} files)")
    if args.ping_votes:
        try:
            ping_votes()
        except Exception as ex:                                  # a sleepy vote database must not block the site
            print("votes ping failed:", ex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
