#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
protect_zones.py

protect_points.json(상수원보호구역 '필지' 중심점들)을 거리 기반으로 군집화하여
'구역' 단위 대표점으로 집계. 카카오 즐겨찾기 근처(반경 N km) 여부도 표시.

출력: protect_zones.json / .csv
"""
import argparse, csv, json, math, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def load_points():
    return json.load(open(DATA / "protect_points.json", encoding="utf-8"))


def load_canoe_coords():
    p = DATA / "synced_seqs.json"
    if not p.exists():
        return []
    items = json.load(open(p, encoding="utf-8")).get("items", {})
    return [(v["lng"], v["lat"]) for v in items.values()
            if v.get("lat") is not None and v.get("lng") is not None]


def cluster(pts, thresh_km):
    n = len(pts)
    deg = thresh_km / 111.0
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


def dist_km(a, b):
    ddx = (a[0] - b[0]) * math.cos(math.radians(a[1])); ddy = a[1] - b[1]
    return math.hypot(ddx, ddy) * 111.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thresh", type=float, default=1.0, help="군집 거리 임계 km (기본 1.0)")
    ap.add_argument("--near", type=float, default=10.0, help="카누 즐겨찾기 근처 반경 km (기본 10)")
    ap.add_argument("--out", default=str(DATA / "protect_zones.json"))
    args = ap.parse_args()

    recs = load_points()
    pts = [(r["lng"], r["lat"]) for r in recs]
    clusters = cluster(pts, args.thresh)
    canoe = load_canoe_coords()
    print(f"[zones] 필지 {len(recs)} → 군집 {len(clusters)}개 (임계 {args.thresh}km)")

    zones = []
    for idx in clusters:
        members = [recs[i] for i in idx]
        mx = sum(m["lng"] for m in members) / len(members)
        my = sum(m["lat"] for m in members) / len(members)
        # 대표점 = 평균에 가장 가까운 실제 필지점
        rep = min(members, key=lambda m: (m["lng"] - mx) ** 2 + (m["lat"] - my) ** 2)
        # 이름: 최빈 시군구
        from collections import Counter
        sido = Counter(m["sido"] for m in members).most_common(1)[0][0]
        sigg = Counter(m["sigg"] for m in members).most_common(1)[0][0]
        near = False
        if canoe:
            near = any(dist_km((rep["lng"], rep["lat"]), c) <= args.near for c in canoe)
        zones.append({
            "name": f"[상수원보호] {sido} {sigg}".strip(),
            "sido": sido, "sigg": sigg,
            "parcels": len(members),
            "lat": round(rep["lat"], 7), "lng": round(rep["lng"], 7),
            "near_canoe": near,
        })
    # 같은 시군구 내 여러 구역엔 번호 부여
    from collections import Counter
    cnt = Counter((z["sido"], z["sigg"]) for z in zones)
    seen = {}
    for z in zones:
        key = (z["sido"], z["sigg"])
        if cnt[key] > 1:
            seen[key] = seen.get(key, 0) + 1
            z["name"] = f"{z['name']} #{seen[key]}"

    zones.sort(key=lambda z: (not z["near_canoe"], z["sido"], z["sigg"]))
    Path(args.out).write_text(json.dumps(zones, ensure_ascii=False, indent=1), encoding="utf-8")
    csv_path = Path(args.out).with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["name", "sido", "sigg", "parcels",
                                           "lat", "lng", "near_canoe"])
        w.writeheader(); w.writerows(zones)

    near_n = sum(1 for z in zones if z["near_canoe"])
    print(f"[zones] 전국 구역 {len(zones)}개")
    print(f"[zones] 카누 즐겨찾기 반경 {args.near}km 내 구역: {near_n}개")
    print(f"[zones] → {Path(args.out).name} / {csv_path.name}")


if __name__ == "__main__":
    main()
