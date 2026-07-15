#!/usr/bin/env python3
"""Build the Soyang shoreline low/high water imagery tile manifest."""

from __future__ import annotations

import concurrent.futures
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "soyang-imagery" / "tiles.json"
ZOOM = 14
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "mycanoe-map/1.0 (https://kohoon.github.io/mycanoe-map/)"

# Representative releases whose Soyang mid-lake metadata is in the target season.
SEASONS = {
    "low": {
        "label": "저수위기(5~7월)",
        "publish": "2023-08-10",
        "tile_id": "17632",
        "metadata": "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2023_r07/MapServer",
        "months": {5, 6, 7},
    },
    "high": {
        "label": "고수위기(9~11월)",
        "publish": "2022-08-10",
        "tile_id": "17825",
        "metadata": "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2022_r10/MapServer",
        "months": {9, 10, 11},
    },
}


def get_json(url: str, params: dict | None = None, attempts: int = 3):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}") from last


def lake_geometry():
    rows = get_json(
        NOMINATIM,
        {
            "q": "소양호, 대한민국",
            "format": "jsonv2",
            "polygon_geojson": 1,
            "limit": 5,
        },
    )
    row = next((x for x in rows if x.get("osm_type") == "relation" and x.get("name") == "소양호"), None)
    if not row:
        raise RuntimeError("OpenStreetMap 소양호 relation을 찾지 못했습니다.")
    return row["geojson"], row.get("osm_id")


def tile_xy(lng: float, lat: float, zoom: int = ZOOM):
    n = 2**zoom
    x = (lng + 180.0) / 360.0 * n
    lat_r = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_center(x: int, y: int, zoom: int = ZOOM):
    n = 2**zoom
    lng = (x + 0.5) / n * 360.0 - 180.0
    merc = math.pi * (1.0 - 2.0 * (y + 0.5) / n)
    lat = math.degrees(math.atan(math.sinh(merc)))
    return lat, lng


def rings_of(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [ring for polygon in geom["coordinates"] for ring in polygon]
    raise RuntimeError(f"unsupported geometry: {geom['type']}")


def shoreline_tiles(geom):
    found = set()
    for ring in rings_of(geom):
        for a, b in zip(ring, ring[1:] + ring[:1]):
            ax, ay = tile_xy(a[0], a[1])
            bx, by = tile_xy(b[0], b[1])
            steps = max(1, math.ceil(max(abs(bx - ax), abs(by - ay)) * 8))
            for i in range(steps + 1):
                t = i / steps
                found.add((math.floor(ax + (bx - ax) * t), math.floor(ay + (by - ay) * t)))
    return sorted(found, key=lambda p: (p[1], p[0]))


def simplify_ring(points, tolerance=0.00018):
    if len(points) < 3:
        return points

    def distance(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))

    def reduce(seq):
        if len(seq) <= 2:
            return seq
        a, b = seq[0], seq[-1]
        idx, furthest = 0, 0.0
        for i, point in enumerate(seq[1:-1], 1):
            value = distance(point, a, b)
            if value > furthest:
                idx, furthest = i, value
        if furthest <= tolerance:
            return [a, b]
        return reduce(seq[: idx + 1])[:-1] + reduce(seq[idx:])

    closed = points[0] == points[-1]
    body = points[:-1] if closed else points
    result = reduce(body)
    if closed:
        result.append(result[0])
    return result


def identify(tile, season_key):
    x, y = tile
    lat, lng = tile_center(x, y)
    season = SEASONS[season_key]
    params = {
        "f": "json",
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "sr": 4326,
        "layers": "all",
        "tolerance": 2,
        "mapExtent": f"{lng-.01},{lat-.01},{lng+.01},{lat+.01}",
        "imageDisplay": "900,900,96",
        "returnGeometry": "false",
    }
    try:
        payload = get_json(season["metadata"] + "/identify", params)
        match = next((r for r in payload.get("results", []) if 4 <= r.get("layerId", -1) <= 8), None)
        if not match:
            return season_key, None
        attrs = match.get("attributes", {})
        raw = str(attrs.get("SRC_DATE") or "")
        if not re.fullmatch(r"\d{8}", raw):
            return season_key, None
        month = int(raw[4:6])
        return season_key, {
            "capture": f"{raw[:4]}-{raw[4:6]}-{raw[6:]}",
            "publish": season["publish"],
            "tileId": season["tile_id"],
            "provider": attrs.get("NICE_DESC") or attrs.get("NICE_NAME") or "Esri",
            "resolution": attrs.get("SRC_RES"),
            "seasonMatch": month in season["months"],
        }
    except Exception:
        return season_key, None


def main():
    geom, osm_id = lake_geometry()
    tiles = shoreline_tiles(geom)
    records = {f"{x}/{y}": {"x": x, "y": y} for x, y in tiles}
    jobs = [(tile, season) for tile in tiles for season in SEASONS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(identify, tile, season): (tile, season) for tile, season in jobs}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            tile, season = futures[future]
            key, value = future.result()
            records[f"{tile[0]}/{tile[1]}"][key] = value
            done += 1
            if done % 50 == 0:
                print(f"metadata {done}/{len(jobs)}")

    for record in records.values():
        for season in SEASONS:
            value = record.get(season)
            if value and not value["seasonMatch"]:
                record[season] = None

    simple = {"type": geom["type"]}
    if geom["type"] == "Polygon":
        simple["coordinates"] = [simplify_ring(ring) for ring in geom["coordinates"]]
    else:
        simple["coordinates"] = [[simplify_ring(ring) for ring in polygon] for polygon in geom["coordinates"]]

    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "zoom": ZOOM,
        "source": {"lake": "OpenStreetMap", "osmRelation": osm_id, "imagery": "Esri World Imagery Wayback"},
        "seasons": {k: {x: y for x, y in v.items() if x != "months" and x != "metadata"} for k, v in SEASONS.items()},
        "lake": simple,
        "tiles": list(records.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    low = sum(1 for x in records.values() if x.get("low"))
    high = sum(1 for x in records.values() if x.get("high"))
    print(f"소양호 호안 타일 {len(tiles)}개 · 저수위 {low} · 고수위 {high} -> {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
