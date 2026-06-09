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
            print(f"    overpass 재시도({attempt+1}) {url.split('/')[2]}: {str(ex)[:50]}", flush=True)
            time.sleep(6 + attempt * 4)
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


def dijkstra_all(adj, src):
    """src에서 모든 노드까지 최단거리/경로(prev)."""
    dist = {src: 0.0}; prev = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd; prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def reconstruct(prev, src, dst):
    if dst == src:
        return [src]
    path = [dst]
    while path[-1] != src:
        if path[-1] not in prev:
            return None
        path.append(prev[path[-1]])
    path.reverse()
    return path


def course_bbox(points, pad=0.05):
    lats = [p[0] for p in points]; lngs = [p[1] for p in points]
    return (min(lats) - pad, min(lngs) - pad, max(lats) + pad, max(lngs) + pad)


def trace_course(course):
    import itertools
    pts = course["points"]
    bbox = course_bbox(pts)
    ways = fetch_waterways(bbox)
    nodes, adj = build_graph(ways)
    snapped = [nearest_node(nodes, p)[0] for p in pts]
    # 각 지점에서 다익스트라(전체)
    alld, allp = {}, {}
    for sn in set(snapped):
        if sn is None:
            continue
        alld[sn], allp[sn] = dijkstra_all(adj, sn)
    n = len(pts)
    # 다지점이면 강 따라 최적 순서(열린경로 최소합) 자동 결정
    if n <= 2:
        order = list(range(n))
    else:
        best, blen = None, 1e18
        for perm in itertools.permutations(range(n)):
            if perm[0] > perm[-1]:
                continue  # 역순 중복 제거
            tot, ok = 0.0, True
            for i in range(n - 1):
                a, b = snapped[perm[i]], snapped[perm[i + 1]]
                dd = alld.get(a, {}).get(b)
                if dd is None:
                    ok = False; break
                tot += dd
            if ok and tot < blen:
                blen, best = tot, perm
        order = list(best) if best else list(range(n))
    full, total = [], 0.0
    for i in range(len(order) - 1):
        a, b = snapped[order[i]], snapped[order[i + 1]]
        path = reconstruct(allp.get(a, {}), a, b)
        if not path:
            print(f"    구간 못 찾음")
            continue
        coords = [[nodes[k][1], nodes[k][0]] for k in path]
        total += alld[a].get(b, 0.0)
        full += coords[1:] if full else coords
    print(f"  [{course['name']}] 노드 {len(nodes)} / 순서 {order} / {total/1000:.1f}km")
    return full, total


def load_favorites():
    p = BASE / "synced_seqs.json"
    if not p.exists():
        return []
    items = json.loads(p.read_text(encoding="utf-8")).get("items", {})
    return [(v.get("name") or "", v.get("lat"), v.get("lng")) for v in items.values()
            if v.get("lat") is not None]


def resolve_point(pt, favs):
    """[lat,lng] 그대로, 또는 즐겨찾기 이름(부분일치)을 좌표로."""
    if isinstance(pt, (list, tuple)) and len(pt) == 2 and all(isinstance(x, (int, float)) for x in pt):
        return [pt[0], pt[1]]
    if isinstance(pt, str):
        hits = [(nm, la, ln) for nm, la, ln in favs if pt in nm]
        if not hits:
            raise SystemExit(f"[!] '{pt}' 와 일치하는 즐겨찾기 없음")
        if len(hits) > 1:
            print(f"    [주의] '{pt}' 다중 일치 → 첫번째 사용: {hits[0][0]}")
        return [hits[0][1], hits[0][2]]
    raise SystemExit(f"[!] 잘못된 point: {pt}")


def main():
    defs = json.loads((BASE / "courses_def.json").read_text(encoding="utf-8"))
    favs = load_favorites()
    for c in defs:
        c["points"] = [resolve_point(p, favs) for p in c["points"]]
    feats = []
    for c in defs:
        coords, total = trace_course(c)
        if not coords:
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"name": c["name"], "color": c.get("color", "#ff6d00"),
                                     "km": round(total / 1000, 1)}})
        print(f"  → {c['name']}: 총 {total/1000:.1f}km", flush=True)
        time.sleep(5.0)
    fc = {"type": "FeatureCollection", "features": feats}
    (BASE / "courses.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"\n[done] {len(feats)}개 코스 → courses.geojson")


if __name__ == "__main__":
    main()
