"""Build web/basemap.json: a small vector map of Harvard/Cambridge drawn by the page itself.

Why: hosted pages may not load map tiles from other servers, and bulk tile downloads are against
OpenStreetMap's tile policy. So the page draws streets, buildings, water and green spaces from
OpenStreetMap data (ODbL, (c) OpenStreetMap contributors), fetched once from the Overpass API.

Format (coordinates as integers: 1e-5 degrees relative to the bbox's south-west corner,
delta-encoded within each feature: [x0, y0, dx1, dy1, ...]):
    {"origin": [lon0, lat0], "bbox": [w, s, e, n],
     "layers": {"water": [...], "green": [...], "building": [...],
                "major": [...], "minor": [...], "path": [...], "river": [...]},
     "labels": [[lon, lat, angle_deg, "Name", "street"|"area"], ...]}

    python tools/build_basemap.py
"""
import json
import math
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "basemap.json"
S, W, N, E = 42.3585, -71.1360, 42.3850, -71.1000     # Allston/HBS to Lippmann House, river to Radcliffe Quad

QUERY = f"""
[out:json][timeout:120];
(
  way["building"]({S},{W},{N},{E});
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|pedestrian|footway|path|cycleway|steps)$"]({S},{W},{N},{E});
  way["waterway"="river"]({S},{W},{N},{E});
  way["natural"="water"]({S},{W},{N},{E});
  way["leisure"~"^(park|garden|pitch|playground|common)$"]({S},{W},{N},{E});
  way["landuse"~"^(grass|recreation_ground|cemetery|meadow)$"]({S},{W},{N},{E});
);
out geom;
"""

MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary"}
MINOR = {"residential", "unclassified", "living_street", "pedestrian"}
PATHS = {"footway", "path", "cycleway", "steps"}      # no "service": driveways and parking aisles are clutter

AREA_LABELS = [   # hand-placed district names (lon, lat)
    (-71.1167, 42.3743, "Harvard Yard"), (-71.1214, 42.3767, "Cambridge Common"),
    (-71.1190, 42.3726, "Harvard Square"), (-71.1245, 42.3690, "Charles River"),
    (-71.1196, 42.3790, "Law School"), (-71.1220, 42.3718, "Kennedy School"),
    (-71.1230, 42.3762, "Radcliffe Yard"), (-71.1245, 42.3655, "Business School"),
]


def encode(coords, lon0, lat0):
    out, px, py = [], 0, 0
    for i, (lon, lat) in enumerate(coords):
        x, y = round((lon - lon0) * 1e5), round((lat - lat0) * 1e5)
        if i == 0:
            out += [x, y]
        else:
            if x == px and y == py:
                continue
            out += [x - px, y - py]
        px, py = x, y
    return out


def merc_angle(a, b):
    """Screen angle (degrees) of segment a->b in Web Mercator, text kept upright."""
    def y(lat):
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    dx = math.radians(b[0] - a[0])
    dy = -(y(b[1]) - y(a[1]))
    ang = math.degrees(math.atan2(dy, dx))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    return round(ang, 1)


def seg_len(a, b):
    return math.hypot((b[0] - a[0]) * math.cos(math.radians(42.37)), b[1] - a[1])


def main():
    r = requests.post("https://overpass-api.de/api/interpreter", data={"data": QUERY},
                      headers={"User-Agent": "FreeFoodMap/0.2 (Harvard student prototype)"}, timeout=180)
    r.raise_for_status()
    elements = r.json()["elements"]
    layers = {k: [] for k in ("water", "green", "building", "major", "minor", "path", "river")}
    best_label = {}     # street name -> (length, midpoint, angle)
    for el in elements:
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        coords = [(g["lon"], g["lat"]) for g in geom]
        tags = el.get("tags", {})
        hw = tags.get("highway")
        if "building" in tags:
            key = "building"
        elif hw in MAJOR:
            key = "major"
        elif hw in MINOR:
            key = "minor"
        elif hw in PATHS:
            key = "path"
        elif tags.get("waterway") == "river":
            key = "river"
        elif tags.get("natural") == "water":
            key = "water"
        else:
            key = "green"
        layers[key].append(encode(coords, W, S))
        name = tags.get("name")
        if name and (hw in MAJOR or hw in ("residential", "unclassified")):
            # label at the middle of the way's longest segment
            segs = [(seg_len(a, b), a, b) for a, b in zip(coords, coords[1:])]
            length, a, b = max(segs)
            total = sum(s[0] for s in segs)
            if total > best_label.get(name, (0,))[0]:
                best_label[name] = (total, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), merc_angle(a, b),
                                    "major" if hw in MAJOR else "minor")
    # keep every major street and only the longer side streets (>= 350 m), so labels don't crowd
    labels = [[round(mid[0], 6), round(mid[1], 6), ang, name, kind]
              for name, (length, mid, ang, kind) in best_label.items()
              if kind == "major" or length * 111_000 >= 350]
    labels += [[lon, lat, 0, text, "area"] for lon, lat, text in AREA_LABELS]
    out = {"origin": [W, S], "bbox": [W, S, E, N], "layers": layers, "labels": labels,
           "attribution": "© OpenStreetMap contributors (ODbL)"}
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    counts = {k: len(v) for k, v in layers.items()}
    print(f"wrote {OUT.name}: {OUT.stat().st_size / 1024:.0f} KB, {counts}, {len(labels)} labels")


if __name__ == "__main__":
    sys.exit(main())
