#!/usr/bin/env python3
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEUNGCHON = (35.06523178, 126.76606233)


def point_in_ring(lat, lng, ring):
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def haversine(a, b):
    radius = 6_371_000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dlambda = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def main():
    payload = json.loads((ROOT / "data" / "wlz_inland.geojson").read_text(encoding="utf-8"))
    matches = [f for f in payload["features"] if "승촌보" in f["properties"]["name"]]
    assert len(matches) == 1

    feature = matches[0]
    props = feature["properties"]
    ring = feature["geometry"]["coordinates"][0]
    assert props["name"] == "영산강 승촌보 상·하류 1km 구역"
    assert props["period"] == "영구"
    assert props["target"] == "공식 현황표 미기재"
    assert point_in_ring(*SEUNGCHON, ring)

    # 보 중심에서 물길 양방향으로 약 1km씩 펼쳐져야 한다.
    distances = sorted(haversine(SEUNGCHON, (lat, lng)) for lng, lat in ring)
    assert distances[-1] >= 900
    assert sum(distance >= 900 for distance in distances) >= 2

    builder = (ROOT / "tools" / "build_wlz_inland.py").read_text(encoding="utf-8")
    assert "[35.06523178,126.76606233]" in builder
    assert "UNKNOWN, \"영구\", \"나주시\"" in builder
    print("water leisure zone regression: ok")


if __name__ == "__main__":
    main()
