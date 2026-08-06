#!/usr/bin/env python3
"""Build a compact South Korea named river/stream centerline GeoJSON from Overpass JSON."""
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "rivers.geojson"
BOUNDARY_URL = "https://nominatim.openstreetmap.org/search?format=jsonv2&country=South%20Korea&polygon_geojson=1&limit=1"
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"
# OSM에 이름이 없지만 공식 본류 구간인 선분. 원본 way 546163695·546166922(2026-08-06 확인).
FORCED_EXTENSIONS = [{"name": "홍천강", "kind": "river", "coordinates": [
    [128.012857, 37.858959], [128.014867, 37.854185], [128.019874, 37.847986],
    [128.020044, 37.846694], [128.019618, 37.84344], [128.018, 37.841046],
    [128.017864, 37.838706], [128.016553, 37.833702], [128.012278, 37.827205],
    [128.007697, 37.822039], [128.00429, 37.819362], [128.000731, 37.818824],
    [127.998772, 37.817196], [127.995928, 37.809998], [127.994719, 37.807831],
    [127.991074, 37.803633],
]}]


def fetch_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "mycanoe-map/1.0 river-build"})
    with urllib.request.urlopen(req, timeout=300) as res:
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
    key = (round(lon, 3), round(lat, 3))
    if key in _inside_cache:
        return _inside_cache[key]
    for bbox, poly in polygons:
        if lon < bbox[0] or lon > bbox[2] or lat < bbox[1] or lat > bbox[3]:
            continue
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
        d = point_line_distance(points[i], points[0], points[-1])
        if d > best:
            best, idx = d, i
    if best <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:idx + 1], tolerance)[:-1] + simplify(points[idx:], tolerance)


def runs_in_country(points, polygons):
    runs, current = [], []
    for p in points:
        if inside_country(p[0], p[1], polygons):
            current.append(p)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = []
    if len(current) >= 2:
        runs.append(current)
    return runs


def merge_named_features(features):
    groups = {}
    for feature in features:
        p = feature["properties"]
        groups.setdefault(p["name"], []).append((p["kind"], feature["geometry"]["coordinates"]))
    merged = []
    for name, parts in groups.items():
        kind = "river" if any(k == "river" for k, _ in parts) else "stream"
        lines = [line for _, line in parts]
        tolerance = 0.04 if kind == "river" else 0.0015
        while lines:
            chain = lines.pop()
            changed = True
            while changed:
                changed = False
                best = None
                for i, other in enumerate(lines):
                    choices = [
                        ((chain[-1][0]-other[0][0])**2+(chain[-1][1]-other[0][1])**2, "append"),
                        ((chain[-1][0]-other[-1][0])**2+(chain[-1][1]-other[-1][1])**2, "append_rev"),
                        ((chain[0][0]-other[-1][0])**2+(chain[0][1]-other[-1][1])**2, "prepend"),
                        ((chain[0][0]-other[0][0])**2+(chain[0][1]-other[0][1])**2, "prepend_rev"),
                    ]
                    dist, mode = min(choices)
                    if best is None or dist < best[0]:
                        best = (dist, i, mode)
                if best and best[0] <= tolerance * tolerance:
                    _, i, mode = best; other = lines.pop(i)
                    if mode == "append": chain += other[1:] if chain[-1] == other[0] else other
                    elif mode == "append_rev":
                        other.reverse(); chain += other[1:] if chain[-1] == other[0] else other
                    elif mode == "prepend": chain = (other[:-1] if other[-1] == chain[0] else other) + chain
                    else:
                        other.reverse(); chain = (other[:-1] if other[-1] == chain[0] else other) + chain
                    changed = True
            merged.append({"type": "Feature", "properties": {"name": name, "kind": kind}, "geometry": {"type": "LineString", "coordinates": chain}})
    return merged


def load_overpass(kind, local_path=None):
    if local_path:
        return json.loads(Path(local_path).read_text(encoding="utf-8"))
    query = f'[out:json][timeout:240];way["waterway"="{kind}"]["name"](33,124,39,132);out tags geom;'
    return fetch_json(OVERPASS_URL, urllib.parse.urlencode({"data": query}).encode())


def normalize_name(name):
    name = str(name or "").strip()
    if "임진강" in name:
        return "임진강"
    return name


def main():
    river_path = sys.argv[1] if len(sys.argv) > 1 else None
    stream_path = sys.argv[2] if len(sys.argv) > 2 else None
    boundary = fetch_json(BOUNDARY_URL)[0]["geojson"]
    raw_polygons = boundary["coordinates"] if boundary["type"] == "MultiPolygon" else [boundary["coordinates"]]
    polygons = []
    for poly in raw_polygons:
        xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
        polygons.append(((min(xs), min(ys), max(xs), max(ys)), poly))
    features = []
    for kind, path, tol in (("river", river_path, 0.00022), ("stream", stream_path, 0.00035)):
        raw = load_overpass(kind, path)
        for way in raw.get("elements", []):
            tags = way.get("tags", {})
            name = normalize_name(tags.get("name:ko") or tags.get("name"))
            points = [[round(n["lon"], 6), round(n["lat"], 6)] for n in way.get("geometry", [])]
            for run in runs_in_country(points, polygons):
                coords = simplify(run, tol)
                if len(coords) >= 2:
                    features.append({"type": "Feature", "properties": {"name": name, "kind": kind}, "geometry": {"type": "LineString", "coordinates": coords}})
    for extension in FORCED_EXTENSIONS:
        features.append({"type": "Feature", "properties": {"name": extension["name"], "kind": extension["kind"]},
                         "geometry": {"type": "LineString", "coordinates": extension["coordinates"]}})
    features = merge_named_features(features)
    fc = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}: {len(features)} segments, {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
