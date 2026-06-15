#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상수원보호구역 폴리곤을 로컬 원본(protect_geom.json)에서 정확도 보존 단순화로 재생성.

기존 build_polygons.py 는 VWorld 키·네트워크가 필요한 온라인 크롤러이고, 그 단순화
(simp_ring, EPS 80m + 4자리 반올림)가 작은 강변 필지를 0~9m 슬리버로 으깨 전국 61%를
붕괴시켰다. 이 스크립트는 같은 원본 캐시에서 **Visvalingam–Whyatt + 면적 바닥 + 최소점
가드 + 원본 폴백**으로 작은 필지를 보존하며 단순화한다. 네트워크/키 불필요(오프라인 재현).

출력: protect_polygons.geojson  (지도가 런타임에 fetch)
입력: protect_geom.json (로컬, gitignore. list of {mnum,sido,sigg,cx,cy,verts})
      verts = 닫힌 외곽링 [[lng,lat],...] (레코드당 1링, 홀 없음)
"""
import json, sys, heapq
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
SRC = BASE / "protect_geom.json"
OUT = BASE / "protect_polygons.geojson"

MIN_POINTS = 6        # 닫힌 링을 이 미만으로 줄이지 않음(5 distinct + 폐합점)
AREA_FLOOR = 3.0e-7   # 이 삼각형 면적(deg^2) 미만 꼭짓점만 제거. 작을수록 정밀/큰 파일. argv[1]로 덮어쓰기
                      # 3e-7 ≈ 61k점/1.5MB(작은 필지는 MIN_POINTS·폴백으로 보존, 큰 폴리곤만 간소화)
ROUND = 5             # 좌표 반올림 자리(~1.1m)
if len(sys.argv) > 1:
    AREA_FLOOR = float(sys.argv[1])


def tri_area(a, b, c):
    """삼각형 (a,b,c) 면적의 2배 절댓값(deg^2). 단순화 중요도 척도."""
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def vw_simplify(open_ring):
    """Visvalingam–Whyatt. open_ring = 폐합점 제거한 열린 링(list of [lng,lat]).
    면적 최소 꼭짓점부터 제거하되 MIN_POINTS 또는 최소면적>AREA_FLOOR 에서 중단.
    반환: 단순화된 열린 링."""
    n = len(open_ring)
    if n <= MIN_POINTS:
        return open_ring[:]
    prev = [(i - 1) % n for i in range(n)]
    nxt = [(i + 1) % n for i in range(n)]
    alive = [True] * n
    area = [0.0] * n
    heap = []
    ver = [0] * n
    for i in range(n):
        area[i] = tri_area(open_ring[prev[i]], open_ring[i], open_ring[nxt[i]])
        heapq.heappush(heap, (area[i], i, 0))
    cnt = n
    while heap and cnt > MIN_POINTS:
        a, i, v = heapq.heappop(heap)
        if not alive[i] or v != ver[i]:
            continue            # 낡은 엔트리
        if a > AREA_FLOOR:
            break               # 남은 모든 꼭짓점이 유의미 → 중단
        # i 제거
        alive[i] = False
        cnt -= 1
        p, q = prev[i], nxt[i]
        nxt[p] = q
        prev[q] = p
        for j in (p, q):        # 이웃 면적 재계산
            if alive[j]:
                area[j] = tri_area(open_ring[prev[j]], open_ring[j], open_ring[nxt[j]])
                ver[j] += 1
                heapq.heappush(heap, (area[j], j, ver[j]))
    # alive 순서대로 복원(시작점부터 next 체인)
    start = next(i for i in range(n) if alive[i])
    out = []
    i = start
    while True:
        out.append(open_ring[i])
        i = nxt[i]
        if i == start:
            break
    return out


def close_round(open_ring):
    """반올림 + 연속 중복 제거 + 폐합. 너무 적으면 None."""
    r = []
    for x, y in open_ring:
        p = [round(x, ROUND), round(y, ROUND)]
        if not r or r[-1] != p:
            r.append(p)
    if len(r) >= 2 and r[0] == r[-1]:
        r.pop()
    if len(r) < 3:
        return None
    r.append(r[0])
    return r


def process_ring(verts):
    """원본 verts(닫힌 링) → 단순화된 닫힌 링. 붕괴 방지 폴백 포함."""
    ring = verts[:]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]        # 열린 링으로
    if len(ring) < 3:
        return None
    simp = vw_simplify(ring)
    out = close_round(simp)
    if out is None or len(set(map(tuple, out[:-1]))) < 4:
        # 하드 가드: 붕괴 시 원본(반올림)으로 폴백 → 실제 범위 이하로 붕괴 안 함
        out = close_round(ring)
    return out


def main():
    if not SRC.exists():
        raise SystemExit(f"[!] 원본 없음: {SRC} (protect_geom.json 로컬 필요)")
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    feats = []
    nv = 0
    skipped = 0
    deg = 0
    for it in raw:
        verts = it.get("verts")
        if isinstance(verts, str):
            verts = json.loads(verts)
        if not verts or len(verts) < 3:
            skipped += 1
            continue
        ring = process_ring(verts)
        if not ring:
            skipped += 1
            continue
        nv += len(ring)
        if len(ring) <= 4:
            deg += 1
        s = ((str(it.get("sido") or "")) + " " + (str(it.get("sigg") or ""))).strip()
        feats.append({"type": "Feature",
                      "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"s": s}})
    fc = {"type": "FeatureCollection", "features": feats}
    OUT.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"[done] {len(feats)}폴리곤 (원본 {len(raw)}, 스킵 {skipped}) → {OUT.name}")
    print(f"       꼭짓점 {nv}, {kb:.0f}KB, ≤4점 {deg}개")
    # 한글 샘플
    for f in feats[:3]:
        print("       샘플 s:", f["properties"]["s"])


if __name__ == "__main__":
    main()
