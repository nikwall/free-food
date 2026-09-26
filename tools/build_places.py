"""Resolve the gazetteer in freefood/places.py to coordinates.

Queries OpenStreetMap Nominatim (max 1 request/second, per its usage policy)
and writes data/places.json. Run again after adding places; entries that
already have coordinates are kept unless --force is given.

    python tools/build_places.py [--force]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from freefood.geo import nominatim_search  # noqa: E402
from freefood.places import PLACES  # noqa: E402

OUT = ROOT / "data" / "places.json"


def main(force=False):
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out = {}
    for key, name, queries, _aliases in PLACES:
        old = existing.get(key)
        if old and old.get("lat") and not force:
            out[key] = {**old, "name": name}
            continue
        hit = None
        for q in queries:
            hit = nominatim_search(q)
            time.sleep(1.1)
            if hit:
                hit["query"] = q
                break
        if hit:
            out[key] = {"name": name, "lat": hit["lat"], "lon": hit["lon"],
                        "query": hit["query"], "osm_name": hit["display_name"][:120]}
            print(f"ok   {key:18s} {hit['lat']:.5f},{hit['lon']:.5f}  <- {hit['query']}")
        else:
            out[key] = {"name": name, "lat": None, "lon": None}
            print(f"MISS {key:18s} {queries}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({sum(1 for v in out.values() if v['lat'])}/{len(out)} located)")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
