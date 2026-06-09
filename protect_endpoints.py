#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
protect_endpoints.py

상수원보호구역(LT_C_UM710) 폴리곤을 받아 구역(군집)별로:
 - 길쭉한(강형) 구역 → 주축(PCA) 양 끝점 2개 (상/하류 근사)
 - 둥근(호수형) 구역 → 중심점 1개
좌표는 카카오 즐겨찾기 추가용 WGS84(lng,lat).

1차 실행 시 지오메트리를 protect_geom.json 으로 캐시 → 이후 재처리는 캐시 사용.

사용:
  python protect_endpoints.py --key KEY --domain http://localhost          # 최초(수집+처리)
  python protect_endpoints.py --aspect 2.5 --minlen-km 1.0                  # 캐시로 재처리(임계 조정)
"""
import argparse, json, math, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
GEOM_CACHE = BASE / "protect_geom.json"
sys.path.insert(0, str(BASE))
from vworld_protect import fetch_page, extract_features, make_grid, KOR_BBOX  # noqa


def parcel_vertices(geom):
    t = geom.get("type"); c = geom.get("coordinates")
    verts = []
    if not c:
        return verts
    if t == "Polygon":
        for ring in c:
            verts += ring
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                verts += ring
    elif t == "Point":
        verts.append(c)
    return verts


def fetch_geometry(key, domain, grid=6):
    seen = {}
    tiles = list(make_grid(KOR_BBOX, grid))
    print(f"[fetch] {len(tiles)} 타일 수집(지오메트리 포함)")
    for ti, box in enumerate(tiles, 1):
        page = 1
        while True:
            try:
                resp = fetch_page(key, domain, box, page)
            except Exception as e:
                print(f"  타일{ti} p{page} 실패: {e}"); break
            feats, status, msg = extract_features(resp)
            if status != "OK" or not feats:
                break
            for f in feats:
                pr = f.get("properties") or {}
                mnum = pr.get("mnum") or f.get("id")
                if mnum in seen:
                    continue
                vs = parcel_vertices(f.get("geometry") or {})
                if not vs:
                    continue
                cx = sum(v[0] for v in vs) / len(vs)
                cy = sum(v[1] for v in vs) / len(vs)
                seen[mnum] = {"mnum": mnum, "sido": pr.get("sido_name") or "",
                              "sigg": pr.get("sigg_name") or "",
                              "cx": cx, "cy": cy,
                              "verts": [[round(v[0], 6), round(v[1], 6)] for v in vs]}
            print(f"  타일{ti}/{len(tiles)} p{page}: +{len(feats)} (누적 {len(seen)})")
            if len(feats) < 1000:
                break
            page += 1; time.sleep(0.3)
        time.sleep(0.15)
    parcels = list(seen.values())
    GEOM_CACHE.write_text(json.dumps(parcels, ensure_ascii=False), encoding="utf-8")
    print(f"[fetch] 캐시 저장: {GEOM_CACHE.name} ({len(parcels)} 필지)")
    return parcels


def cluster(parcels, thresh_km=1.0):
    n = len(parcels); deg = thresh_km / 111.0
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    buckets = {}
    pts = [(p["cx"], p["cy"]) for p in parcels]
    for i, (x, y) in enumerate(pts):
        buckets.setdefault((int(x / deg), int(y / deg)), []).append(i)
    th2 = deg * deg
    for i, (x, y) in enumerate(pts):
        bx, by = int(x / deg), int(y / deg)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in buckets.get((bx + dx, by + dy), []):
                    if j <= i:
                        continue
                    xx, yy = pts[j]
                    ddx = (x - xx) * math.cos(math.radians(y)); ddy = y - yy
                    if ddx * ddx + ddy * ddy <= th2:
                        uni(i, j)
    roots = {}
    for i in range(n):
        roots.setdefault(find(i), []).append(i)
    return list(roots.values())


def pca(verts):
    """반환: (끝점A, 끝점B, 주축길이m, 보조축길이m, 중심[lng,lat], 축방향)."""
    n = len(verts)
    lon0 = sum(v[0] for v in verts) / n
    lat0 = sum(v[1] for v in verts) / n
    k = math.cos(math.radians(lat0))
    P = [((v[0] - lon0) * 111000 * k, (v[1] - lat0) * 111000) for v in verts]
    sxx = sum(p[0] * p[0] for p in P) / n
    syy = sum(p[1] * p[1] for p in P) / n
    sxy = sum(p[0] * p[1] for p in P) / n
    tr = sxx + syy; det = sxx * syy - sxy * sxy
    disc = math.sqrt(max(0.0, (tr / 2) ** 2 - det))
    l1 = tr / 2 + disc
    if abs(sxy) > 1e-9:
        vx, vy = l1 - syy, sxy
    else:
        vx, vy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)
    nv = math.hypot(vx, vy) or 1.0
    vx, vy = vx / nv, vy / nv
    ux, uy = -vy, vx
    proj = [(p[0] * vx + p[1] * vy, i) for i, p in enumerate(P)]
    pmin, pmax = min(proj), max(proj)
    major = pmax[0] - pmin[0]
    pm = [p[0] * ux + p[1] * uy for p in P]
    minor = max(pm) - min(pm)
    A = verts[pmin[1]]; B = verts[pmax[1]]
    return A, B, major, minor, [lon0, lat0], (vx, vy)


def endpoint_labels(A, B, axis):
    """축 방향 따라 두 끝점에 방위 라벨."""
    vx, vy = axis
    if abs(vy) >= abs(vx):       # 남북 축
        hi, lo = ("북측", "남측")
        return (hi, lo) if A[1] >= B[1] else (lo, hi)
    else:                         # 동서 축
        hi, lo = ("동측", "서측")
        return (hi, lo) if A[0] >= B[0] else (lo, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key"); ap.add_argument("--domain")
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--thresh", type=float, default=1.0, help="군집 거리 km")
    ap.add_argument("--aspect", type=float, default=2.5, help="강형 판정 종횡비")
    ap.add_argument("--minlen-km", type=float, default=1.0, help="강형 최소 주축 길이 km")
    ap.add_argument("--maxlen-km", type=float, default=12.0, help="강형 최대 주축 길이 km(초과시 호수형)")
    ap.add_argument("--out", default=str(BASE / "protect_zones.json"))
    args = ap.parse_args()

    if GEOM_CACHE.exists() and not args.refetch:
        parcels = json.loads(GEOM_CACHE.read_text(encoding="utf-8"))
        print(f"[cache] {GEOM_CACHE.name} 로드 ({len(parcels)} 필지)")
    else:
        if not (args.key and args.domain):
            print("[!] 최초 실행엔 --key, --domain 필요"); return
        parcels = fetch_geometry(args.key, args.domain)

    clusters = cluster(parcels, args.thresh)
    print(f"[zones] 필지 {len(parcels)} → 군집 {len(clusters)}")

    from collections import Counter
    zones = []
    for idx in clusters:
        members = [parcels[i] for i in idx]
        verts = [v for m in members for v in m["verts"]]
        sido = Counter(m["sido"] for m in members).most_common(1)[0][0]
        sigg = Counter(m["sigg"] for m in members).most_common(1)[0][0]
        A, B, major, minor, cen, axis = pca(verts)
        aspect = major / max(minor, 1.0)
        base = f"[상수원보호] {sido} {sigg}".strip()
        if aspect >= args.aspect and args.minlen_km * 1000 <= major <= args.maxlen_km * 1000:
            la, lb = endpoint_labels(A, B, axis)
            pts = [{"label": la, "lat": round(A[1], 7), "lng": round(A[0], 7)},
                   {"label": lb, "lat": round(B[1], 7), "lng": round(B[0], 7)}]
            ztype = "river"
        else:
            pts = [{"label": "", "lat": round(cen[1], 7), "lng": round(cen[0], 7)}]
            ztype = "lake"
        zones.append({"name": base, "sido": sido, "sigg": sigg, "type": ztype,
                      "aspect": round(aspect, 2), "major_km": round(major / 1000, 2),
                      "parcels": len(members), "points": pts})

    # 같은 시군구 다중 구역 번호
    cnt = Counter((z["sido"], z["sigg"]) for z in zones)
    seen = {}
    for z in zones:
        key = (z["sido"], z["sigg"])
        if cnt[key] > 1:
            seen[key] = seen.get(key, 0) + 1
            z["name"] = f"{z['name']} #{seen[key]}"

    rivers = [z for z in zones if z["type"] == "river"]
    lakes = [z for z in zones if z["type"] == "lake"]
    total_pts = sum(len(z["points"]) for z in zones)
    Path(args.out).write_text(json.dumps(zones, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[zones] 강형 {len(rivers)} (2점) / 호수형 {len(lakes)} (1점)")
    print(f"[zones] 총 마커 점 {total_pts}개 → {Path(args.out).name}")
    print("\n[예시 강형]")
    for z in rivers[:5]:
        print(f"  {z['name']}  종횡비{z['aspect']} 길이{z['major_km']}km  점{len(z['points'])}")


if __name__ == "__main__":
    main()
