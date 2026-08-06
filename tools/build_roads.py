#!/usr/bin/env python3
"""Build compact South Korea expressway/national/local-road route GeoJSON."""
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "roads.geojson"
BOUNDARY_URL = "https://nominatim.openstreetmap.org/search?format=jsonv2&country=South%20Korea&polygon_geojson=1&limit=1"
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"


def fetch_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "mycanoe-map/1.0 road-build"})
    with urllib.request.urlopen(req, timeout=360) as res:
        return json.load(res)


def inside_ring(x, y, ring):
    hit = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi:
            hit = not hit
        j = i
    return hit


_inside_cache = {}
def inside_country(lon, lat, polygons):
    key = (round(lon, 2), round(lat, 2))
    if key in _inside_cache:
        return _inside_cache[key]
    for bbox, poly in polygons:
        if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
            if inside_ring(lon, lat, poly[0]) and not any(inside_ring(lon, lat, hole) for hole in poly[1:]):
                _inside_cache[key] = True
                return True
    _inside_cache[key] = False
    return False


def point_line_distance(p, a, b):
    x, y = p; x1, y1 = a; x2, y2 = b
    dx, dy = x2 - x1, y2 - y1
    if not dx and not dy:
        return math.hypot(x - x1, y - y1)
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points, tolerance):
    if len(points) <= 2:
        return points
    best, idx = 0, 0
    for i in range(1, len(points) - 1):
        distance = point_line_distance(points[i], points[0], points[-1])
        if distance > best:
            best, idx = distance, i
    if best <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:idx + 1], tolerance)[:-1] + simplify(points[idx:], tolerance)


def clean_ref(value):
    refs = re.findall(r"\d+", str(value or ""))
    return ";".join(dict.fromkeys(refs))


def main():
    local_path = sys.argv[1] if len(sys.argv) > 1 else None
    boundary = fetch_json(BOUNDARY_URL)[0]["geojson"]
    raw_polygons = boundary["coordinates"] if boundary["type"] == "MultiPolygon" else [boundary["coordinates"]]
    polygons = []
    for poly in raw_polygons:
        xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
        polygons.append(((min(xs), min(ys), max(xs), max(ys)), poly))
    if local_path:
        raw = json.loads(Path(local_path).read_text(encoding="utf-8"))
    else:
        query = '[out:json][timeout:240];way["highway"~"^(motorway|trunk|primary|secondary)$"]["ref"](33,124,39,132);out tags geom;'
        raw = fetch_json(OVERPASS_URL, urllib.parse.urlencode({"data": query}).encode())

    groups = defaultdict(lambda: {"names": defaultdict(int), "lines": []})
    tolerance = {"expressway": 0.00012, "national": 0.00018, "local": 0.00025}
    for way in raw.get("elements", []):
        tags = way.get("tags", {})
        ref = clean_ref(tags.get("ref"))
        nums = [int(n) for n in ref.split(";") if n] if ref else []
        kind = "expressway" if tags.get("highway") == "motorway" else ("national" if nums and max(nums) < 100 else "local")
        geom = way.get("geometry") or []
        if not kind or not ref or len(geom) < 2:
            continue
        points = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom]
        # A segment is retained only when its midpoint is in South Korea; this removes Japan/North Korea cheaply.
        mid = points[len(points) // 2]
        if not inside_country(mid[0], mid[1], polygons):
            continue
        key = (kind, ref)
        name = str(tags.get("name:ko") or tags.get("name") or "").strip()
        if name:
            groups[key]["names"][name] += len(points)
        line = simplify(points, tolerance[kind])
        if len(line) >= 2:
            groups[key]["lines"].append(line)

    features = []
    for (kind, ref), value in groups.items():
        name = max(value["names"], key=value["names"].get) if value["names"] else ""
        aliases = [n for n, _ in sorted(value["names"].items(), key=lambda x: (-x[1], x[0])) if n != name][:12]
        features.append({"type": "Feature", "properties": {"kind": kind, "ref": ref, "name": name, "aliases": aliases},
                         "geometry": {"type": "MultiLineString", "coordinates": value["lines"]}})
    features.sort(key=lambda f: ({"expressway": 0, "national": 1, "local": 2}[f["properties"]["kind"]], f["properties"]["ref"]))
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}: {len(features)} routes, {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
