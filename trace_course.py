#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSM 하천(waterway) 라인을 따라 두 점(+경유) 사이 코스를 추적.
courses_def.json 정의를 읽어 courses.geojson 생성.
courses_def.json 예:
[{"name":"엑스페디션#4 (동강)","color":"#ff6d00","points":[[lat,lng],[lat,lng], ...]}]
"""
import json, sys, math, heapq, time, urllib.request, urllib.parse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


def haversine(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def fetch_waterways(bbox):
    s, w, n, e = bbox
    q = f'[out:json][timeout:90];(way["waterway"~"river|stream|canal|riverbank"]({s},{w},{n},{e}););out geom;'
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(6):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, data=data,
                headers={"User-Agent": "mycanoe-map/1.0"}), timeout=120)
            return json.loads(r.read().decode("utf-8")).get("elements", [])
        except Exception as ex:
            last = ex
            print(f"    overpass 재시도({attempt+1}) {url.split('/')[2]}: {str(ex)[:50]}")
            time.sleep(4)
    raise RuntimeError(f"overpass 실패: {last}")


def build_graph(ways):
    """좌표를 5자리로 합쳐 노드화, 인접 꼭짓점끼리 엣지."""
    adj = {}
    nodes = {}  # key -> (lat,lng)

    def key(lat, lng):
        k = (round(lat, 5), round(lng, 5))
        if k not in nodes:
            nodes[k] = (lat, lng)
        return k

    for wy in ways:
        geom = wy.get("geometry") or []
        prev = None
        for p in geom:
            k = key(p["lat"], p["lon"])
            if prev is not None and prev != k:
                d = haversine(nodes[prev], nodes[k])
                adj.setdefault(prev, []).append((k, d))
                adj.setdefault(k, []).append((prev, d))
            prev = k
    return nodes, adj


def nearest_node(nodes, pt):
    best, bd = None, 1e18
    for k, c in nodes.items():
        d = haversine(c, pt)
        if d < bd:
            bd, best = d, k
    return best, bd


def dijkstra(adj, src, dst):
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd; prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None, None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist[dst]


def trace_segment(nodes, adj, p1, p2):
    n1, d1 = nearest_node(nodes, p1)
    n2, d2 = nearest_node(nodes, p2)
    path, dist = dijkstra(adj, n1, n2)
    if not path:
        return None, None, (d1, d2)
    coords = [[nodes[k][1], nodes[k][0]] for k in path]  # [lng,lat]
    return coords, dist, (d1, d2)


def course_bbox(points, pad=0.04):
    lats = [p[0] for p in points]; lngs = [p[1] for p in points]
    return (min(lats) - pad, min(lngs) - pad, max(lats) + pad, max(lngs) + pad)


def trace_course(course):
    pts = course["points"]
    bbox = course_bbox(pts)
    ways = fetch_waterways(bbox)
    nodes, adj = build_graph(ways)
    print(f"  [{course['name']}] OSM 라인 {len(ways)} / 노드 {len(nodes)}")
    full = []
    total = 0.0
    for i in range(len(pts) - 1):
        coords, dist, (d1, d2) = trace_segment(nodes, adj, pts[i], pts[i + 1])
        if not coords:
            print(f"    구간 {i+1}: 경로 못 찾음 (snap {d1:.0f}m/{d2:.0f}m)")
            continue
        print(f"    구간 {i+1}: {dist/1000:.1f}km, {len(coords)}점 (snap {d1:.0f}m/{d2:.0f}m)")
        total += dist
        if full and coords:
            full += coords[1:]
        else:
            full += coords
    return full, total


def main():
    defs = json.loads((BASE / "courses_def.json").read_text(encoding="utf-8"))
    feats = []
    for c in defs:
        coords, total = trace_course(c)
        if not coords:
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"name": c["name"], "color": c.get("color", "#ff6d00"),
                                     "km": round(total / 1000, 1)}})
        print(f"  → {c['name']}: 총 {total/1000:.1f}km")
        time.sleep(1.0)
    fc = {"type": "FeatureCollection", "features": feats}
    (BASE / "courses.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"\n[done] {len(feats)}개 코스 → courses.geojson")


if __name__ == "__main__":
    main()
