#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""내수면 수상레저 금지구역 폴리곤 생성 → wlz_inland.geojson.

해경 고시(공공데이터 PNG 도면)와 서울시 한강 고시를 기반으로:
- 강 구간 구역: OSM 물길 추적(trace_course 재사용) 후 좌우 버퍼 → 폴리곤
- 한강 서울 구역(동력만 금지): 고시 문구 기반 강변 띠(수동 좌표)
※ 도면 기반 '대략' 표시 — 팝업에 명시.
"""
import json, math, sys
from pathlib import Path
from trace_course import fetch_waterways, build_graph, nearest_node, dijkstra_all, reconstruct, haversine

BASE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NOTE = "해양경찰청·지자체 고시 도면 기반 대략 표시(원문 고시 확인 권장)"

def buffer_path(latlngs, width_m):
    """폴리라인 좌우 width/2 버퍼 → 폴리곤 링([[lng,lat],...])."""
    half = width_m / 2.0
    left, right = [], []
    n = len(latlngs)
    for i, (la, lo) in enumerate(latlngs):
        pa = latlngs[max(0, i - 1)]; pb = latlngs[min(n - 1, i + 1)]
        mlat = 110540.0; mlng = 111320.0 * math.cos(math.radians(la))
        dx = (pb[1] - pa[1]) * mlng; dy = (pb[0] - pa[0]) * mlat
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d   # 좌측 법선
        left.append([round(lo + nx * half / mlng, 6), round(la + ny * half / mlat, 6)])
        right.append([round(lo - nx * half / mlng, 6), round(la - ny * half / mlat, 6)])
    ring = left + right[::-1] + [left[0]]
    return [ring]

def trace_river(river, a, b, pad=0.04):
    """a→b 물길 최단경로 좌표([lat,lng] 목록)."""
    s = min(a[0], b[0]) - pad; n = max(a[0], b[0]) + pad
    w = min(a[1], b[1]) - pad; e = max(a[1], b[1]) + pad
    ways = fetch_waterways((s, w, n, e))
    nodes, adj, named = build_graph(ways, river)
    def snap(p):
        if named:
            k, d = nearest_node(nodes, p, named)
            if k is not None and d < 800: return k
        k, d = nearest_node(nodes, p)
        return k
    ka, kb = snap(a), snap(b)
    dist, prev = dijkstra_all(adj, ka)
    path = reconstruct(prev, ka, kb)
    if not path:
        print(f"  [!] 경로 실패: {river}"); return [a, b]
    pts = [list(nodes[k]) for k in path]
    # 단순화(20m 미만 점 병합)
    out = [pts[0]]
    for p in pts[1:]:
        if haversine(out[-1], p) >= 20: out.append(p)
    if out[-1] != pts[-1]: out.append(pts[-1])
    return out

def strip(a, b, width_m):
    """두 점 잇는 직선 띠."""
    return buffer_path([a, b], width_m)

def box(c, w_m, h_m):
    mlat = 110540.0; mlng = 111320.0 * math.cos(math.radians(c[0]))
    dlat = h_m / 2 / mlat; dlng = w_m / 2 / mlng
    la, lo = c
    return [[[round(lo-dlng,6),round(la-dlat,6)],[round(lo+dlng,6),round(la-dlat,6)],
             [round(lo+dlng,6),round(la+dlat,6)],[round(lo-dlng,6),round(la+dlat,6)],
             [round(lo-dlng,6),round(la-dlat,6)]]]

MOTOR = "동력수상레저기구(서울시 고시)"        # 카누 가능(회청)
ALL_ = "모든 수상레저기구(도면 기준)"          # 카누 포함(주황)

def main():
    feats = []
    def add(name, rings, target, period, office):
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": rings},
                      "properties": {"name": name, "office": office, "period": period,
                                     "target": target, "note": NOTE}})
    # ---- 한강(서울시 고시, 동력만 금지 = 카누 가능) ----
    add("한강 여의도1구역(물빛무대~마포대교 하류400m)",
        strip([37.5323, 126.9280], [37.5300, 126.9345], 130), MOTOR, "2023.10.6~2026.9.5", "서울시 미래한강본부")
    add("한강 여의도2구역(마포대교 상류~임시선착장)",
        strip([37.5295, 126.9395], [37.5287, 126.9430], 130), MOTOR, "2023.10.6~2026.9.5", "서울시 미래한강본부")
    add("한강 반포구역(세빛섬~반포대교~이크루즈)",
        strip([37.5105, 126.9930], [37.5125, 127.0005], 130), MOTOR, "2023.10.6~2026.9.5", "서울시 미래한강본부")
    add("한강 망원구역(경사로 진입부)",
        box([37.5505, 126.9000], 50, 20), MOTOR, "2025.6.1~2028.5.31", "서울시 미래한강본부")
    # ---- 해경 고시(보·철새도래지 등, 카누 포함으로 표시) ----
    print("이포보 추적…")
    add("남한강 이포보 구역", buffer_path(trace_river("남한강", [37.4080, 127.5360], [37.3700, 127.5430]), 280),
        ALL_, "", "여주시/해양경찰청 고시")
    print("세종보 추적…")
    add("금강 세종보 구역(금남교~금강교)", buffer_path(trace_river("금강", [36.4774, 127.2712], [36.4655, 127.2475]), 380),
        ALL_, "", "세종시/해양경찰청 고시")
    print("백제보 추적…")
    add("금강 백제보 구역", buffer_path(trace_river("금강", [36.3191, 126.9390], [36.3320, 126.9580]), 320),
        ALL_, "", "부여군/해양경찰청 고시")
    print("합천창녕보 추적…")
    add("낙동강 합천창녕보 구역", buffer_path(trace_river("낙동강", [35.6040, 128.3520], [35.5760, 128.3610]), 320),
        ALL_, "", "창녕군/해양경찰청 고시")
    print("오십천 추적…")
    add("삼척 오십천 구역(미로면)", buffer_path(trace_river("오십천", [37.4280, 129.1080], [37.4060, 129.1180]), 90),
        ALL_, "", "삼척시/해양경찰청 고시")
    # 낙동강 하구 철새도래지(을숙도 동·서 수로)
    add("낙동강 철새도래지(을숙도 서수로)", strip([35.0990, 128.9285], [35.1130, 128.9325], 320), ALL_, "", "부산시/해양경찰청 고시")
    add("낙동강 철새도래지(을숙도 동수로)", strip([35.0960, 128.9560], [35.1140, 128.9600], 320), ALL_, "", "부산시/해양경찰청 고시")
    # 하동 청용저수지(소형, OSM 실측 좌표)
    add("하동 청용저수지", box([35.17451, 127.85312], 220, 380), ALL_, "", "하동군/해양경찰청 고시")

    fc = {"type": "FeatureCollection", "features": feats}
    (BASE / "wlz_inland.geojson").write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[done] {len(feats)}개 구역 → wlz_inland.geojson")

if __name__ == "__main__":
    main()
