"""Run one scan of all sources and write data/events.json.

    python scan.py                 # all sources, today + 7 days
    python scan.py --days 3        # shorter window
    python scan.py --only hks hls  # just some sources (ids in freefood/sources/__init__.py)
"""
import argparse
import sys

from freefood.pipeline import run_scan

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=8, help="days to scan, starting today (default 8)")
    ap.add_argument("--only", nargs="*", help="source ids to run")
    args = ap.parse_args()
    run_scan(days=args.days, only=set(args.only) if args.only else None)
