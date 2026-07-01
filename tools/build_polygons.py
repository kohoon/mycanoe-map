#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""상수원보호구역(LT_C_UM710) 폴리곤을 받아 단순화한 GeoJSON 생성(외곽선만).
출력: protect_polygons.geojson  (자체포함 지도용)"""
import json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
sys.path.insert(0, str(BASE))
from vworld_protect import fetch_page, extract_features, make_grid, KOR_BBOX  # noqa

import os
_kf = BASE / "vworld_key.txt"
KEY = os.environ.get("VWORLD_KEY") or (_kf.read_text(encoding="utf-8").strip() if _kf.exists() else "")
DOMAIN = "http://localhost"
if not KEY:
    raise SystemExit("[!] V-World 키 없음. 환경변수 VWORLD_KEY 설정 또는 vworld_key.txt 생성")
EPS = 0.0008  # ~80m


def dp(pts, eps):
    """Douglas-Peucker 단순화 (열린 폴리라인)."""
    if len(pts) < 3:
        return pts[:]
    dmax, idx = 0.0, 0
    x1, y1 = pts[0]; x2, y2 = pts[-1]
    dx, dy = x2 - x1, y2 - y1
    den = (dx * dx + dy * dy) ** 0.5 or 1e-12
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / den
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = dp(pts[:idx + 1], eps)
        right = dp(pts[idx:], eps)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def simp_ring(ring):
    r = [[round(x, 4), round(y, 4)] for x, y in ring]
    if len(r) <= 5:
        if r[0] != r[-1]:
            r.append(r[0])
        return r
    op = r[:-1] if r[0] == r[-1] else r[:]   # 열린 링
    p0 = op[0]
    far = max(range(len(op)), key=lambda i: (op[i][0]-p0[0])**2 + (op[i][1]-p0[1])**2)
    a = dp(op[:far+1], EPS)
    b = dp(op[far:] + [op[0]], EPS)
    s = a[:-1] + b[:-1]
    if len(s) < 3:
        s = op[:3]
    s.append(s[0])
    return s


def exterior_only(geom):
    """Polygon/MultiPolygon에서 외곽 링만 단순화해 반환."""
    t = geom.get("type"); c = geom.get("coordinates")
    if not c:
        return None
    if t == "Polygon":
        return {"type": "Polygon", "coordinates": [simp_ring(c[0])]}
    if t == "MultiPolygon":
        polys = [[simp_ring(poly[0])] for poly in c if poly and poly[0]]
        return {"type": "MultiPolygon", "coordinates": polys}
    return None


def main():
    seen = {}
    tiles = list(make_grid(KOR_BBOX, 6))
    print(f"[fetch] {len(tiles)} 타일")
    for ti, box in enumerate(tiles, 1):
        page = 1
        while True:
            resp = fetch_page(KEY, DOMAIN, box, page)
            feats, status, _ = extract_features(resp)
            if status != "OK" or not feats:
                break
            for f in feats:
                pr = f.get("properties") or {}
                mnum = pr.get("mnum") or f.get("id")
                if mnum in seen:
                    continue
                g = exterior_only(f.get("geometry") or {})
                if not g:
                    continue
                seen[mnum] = {"type": "Feature", "geometry": g,
                              "properties": {"s": (pr.get("sido_name") or "") + " " + (pr.get("sigg_name") or "")}}
            if len(feats) < 1000:
                break
            page += 1
        print(f"  타일{ti}/{len(tiles)} 누적 {len(seen)}")
    fc = {"type": "FeatureCollection", "features": list(seen.values())}
    out = BASE / "protect_polygons.geojson"
    out.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    nv = sum(len(r) for ft in fc["features"] for poly in
             ([ft["geometry"]["coordinates"]] if ft["geometry"]["type"] == "Polygon"
              else ft["geometry"]["coordinates"]) for r in poly)
    print(f"[done] {len(seen)}개 폴리곤 → {out.name} ({out.stat().st_size/1024:.0f} KB, 꼭짓점 {nv})")


if __name__ == "__main__":
    main()
