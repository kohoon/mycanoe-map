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


def build_graph(ways, river_name=None):
    """좌표를 5자리로 합쳐 노드화. river_name 본류는 엣지 가중치 할인(경로 우선) + named 집합."""
    adj = {}
    nodes = {}      # key -> (lat,lng)
    named = set()   # 본류(river_name) 위 노드
    MULT = 0.04     # 본류 엣지 라우팅 가중치(작을수록 본류 강하게 선호, 곡류 질러가기 방지)

    def key(lat, lng):
        k = (round(lat, 5), round(lng, 5))
        if k not in nodes:
            nodes[k] = (lat, lng)
        return k

    for wy in ways:
        nm = (wy.get("tags") or {}).get("name", "") or ""
        geom = wy.get("geometry") or []
        is_main = bool(river_name) and river_name in nm
        # 본류라도 '긴 way'(실제 강 본류)만 강하게 선호. 짧은 동명 way(가로지름/지선)는 약하게.
        if is_main and len(geom) >= 80:
            mult = MULT
        elif is_main:
            mult = 0.6
        else:
            mult = 1.0
        prev = None
        for p in geom:
            k = key(p["lat"], p["lon"])
            if is_main:
                named.add(k)
            if prev is not None and prev != k:
                d = haversine(nodes[prev], nodes[k]) * mult
                adj.setdefault(prev, []).append((k, d))
                adj.setdefault(k, []).append((prev, d))
            prev = k
    return nodes, adj, named


def nearest_node(nodes, pt, restrict=None):
    best, bd = None, 1e18
    pool = restrict if restrict else nodes.keys()
    for k in pool:
        d = haversine(nodes[k], pt)
        if d < bd:
            bd, best = d, k
    return best, bd


def path_meters(nodes, path):
    return sum(haversine(nodes[path[i]], nodes[path[i + 1]]) for i in range(len(path) - 1))


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
    import re, itertools
    pts = course["points"]
    m = re.search(r'\((.+?)\)', course["name"])
    river = m.group(1) if m else None     # 코스명 괄호 안 강 이름(본류)
    bbox = course_bbox(pts)
    ways = fetch_waterways(bbox)
    nodes, adj, named = build_graph(ways, river)
    def smart_snap(p):
        """본류가 충분히 가까우면 본류, 아니면(이름전환 구간 등) 가장 가까운 물길."""
        n_all, d_all = nearest_node(nodes, p)
        if named:
            n_nm, d_nm = nearest_node(nodes, p, named)
            if n_nm is not None and d_nm <= d_all + 300:
                return n_nm, d_nm
        return n_all, d_all
    snaps = [smart_snap(p) for p in pts]   # [(node, 스냅거리m), ...]
    snapped = [s[0] for s in snaps]
    alld, allp = {}, {}
    for sn in set(snapped):
        if sn is None:
            continue
        alld[sn], allp[sn] = dijkstra_all(adj, sn)
    n = len(pts)

    def true_dist(i, j):   # 정렬용 실거리(본류 가중치 아님)
        a, b = snapped[i], snapped[j]
        p = reconstruct(allp.get(a, {}), a, b)
        return path_meters(nodes, p) if p else None

    if n <= 2:
        order = list(range(n))
    else:
        best, blen = None, 1e18
        for perm in itertools.permutations(range(n)):
            if perm[0] > perm[-1]:
                continue
            tot, ok = 0.0, True
            for i in range(n - 1):
                d = true_dist(perm[i], perm[i + 1])
                if d is None:
                    ok = False; break
                tot += d
            if ok and tot < blen:
                blen, best = tot, perm
        order = list(best) if best else list(range(n))
    full, total = [], 0.0
    for i in range(len(order) - 1):
        a, b = snapped[order[i]], snapped[order[i + 1]]
        path = reconstruct(allp.get(a, {}), a, b)
        if not path:
            print("    구간 못 찾음")
            continue
        coords = [[nodes[k][1], nodes[k][0]] for k in path]
        total += path_meters(nodes, path)   # 실거리(라우팅 가중치 아님)
        full += coords[1:] if full else coords
    # 추적선을 실제 시작/끝 지점까지 연결하고 그 거리도 포함(점-to-점)
    if full:
        sp, ep = pts[order[0]], pts[order[-1]]
        full = [[sp[1], sp[0]]] + full + [[ep[1], ep[0]]]
        total += snaps[order[0]][1] + snaps[order[-1]][1]
    print(f"  [{course['name']}] 강='{river}' 본류노드 {len(named)}/{len(nodes)} / 순서 {order} / "
          f"{total/1000:.1f}km (스냅 {snaps[order[0]][1]:.0f}m/{snaps[order[-1]][1]:.0f}m)")
    return full, total


def load_favorites():
    p = BASE / "synced_seqs.json"
    if not p.exists():
        return []
    items = json.loads(p.read_text(encoding="utf-8")).get("items", {})
    return [(v.get("name") or "", v.get("lat"), v.get("lng")) for v in items.values()
            if v.get("lat") is not None]


def load_id_map():
    """place_ids.json(즐겨찾기 key->ID) + synced_seqs => {ID: [lat,lng]}."""
    rp = BASE / "place_ids.json"
    sj = BASE / "synced_seqs.json"
    if not rp.exists() or not sj.exists():
        return {}
    ids = json.loads(rp.read_text(encoding="utf-8")).get("ids", {})
    items = json.loads(sj.read_text(encoding="utf-8")).get("items", {})
    m = {}
    for key, pid in ids.items():
        v = items.get(key)
        if v and v.get("lat") is not None:
            m[int(pid)] = [v["lat"], v["lng"]]
    return m


def resolve_point(pt, favs, idmap=None):
    """장소 ID(정수/"#N"/"N"), [lat,lng], 또는 즐겨찾기 이름(부분일치)을 좌표로."""
    idmap = idmap or {}
    pid = None
    if isinstance(pt, bool):
        pass
    elif isinstance(pt, int):
        pid = pt
    elif isinstance(pt, str) and pt.strip().lstrip("#").isdigit():
        pid = int(pt.strip().lstrip("#"))
    if pid is not None:
        if pid in idmap:
            return idmap[pid]
        raise SystemExit(f"[!] 장소 ID {pid} 에 해당하는 장소 없음")
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
    idmap = load_id_map()
    for c in defs:
        c["points"] = [resolve_point(p, favs, idmap) for p in c["points"]]
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
