#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""내수면 수상레저 금지구역 폴리곤 생성 → wlz_inland.geojson.

근거: 해양경찰청 「내수면 수상레저활동 금지구역 지정현황(2024)」(전국 51개소, 공식 xlsx)
+ 서울시 한강 고시(여의도1·2/반포/망원).
- weir/segment: OSM 물길 추적(trace_course 재사용) 후 좌우 버퍼
- lake: OSM 수면 폴리곤(Overpass) 사용, 실패 시 박스
※ 좌표 고시가 없어 '대략 표시' — 팝업에 명시. 위치 미상 구역(화적연/영로교/안동댐 산야리)은 제외.
"""
import json, math, sys, time, urllib.request, urllib.parse
from pathlib import Path
from trace_course import fetch_waterways, build_graph, nearest_node, dijkstra_all, reconstruct, haversine

BASE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NOTE = "공식 지정현황(2024) 기반 대략 표시(세부구간은 관할 고시 참조)"
MOTOR_NOTE = "동력 수상레저기구 금지(카누·카약 등 무동력은 허용)"

def buffer_path(latlngs, width_m):
    half = width_m / 2.0
    left, right = [], []
    n = len(latlngs)
    for i, (la, lo) in enumerate(latlngs):
        pa = latlngs[max(0, i - 1)]; pb = latlngs[min(n - 1, i + 1)]
        mlat = 110540.0; mlng = 111320.0 * math.cos(math.radians(la))
        dx = (pb[1] - pa[1]) * mlng; dy = (pb[0] - pa[0]) * mlat
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d
        left.append([round(lo + nx * half / mlng, 6), round(la + ny * half / mlat, 6)])
        right.append([round(lo - nx * half / mlng, 6), round(la - ny * half / mlat, 6)])
    return [left + right[::-1] + [left[0]]]

def _graph(anchor, river, pad, weighted=True):
    """weighted=False면 실거리 그래프(본류 가중치 할인 없음) — 거리 기준 구역용.
    named(본류 노드 집합)는 항상 강 이름 기준으로 산출(스냅용)."""
    s = anchor[0] - pad; n = anchor[0] + pad; w = anchor[1] - pad; e = anchor[1] + pad
    ways = fetch_waterways((s, w, n, e))
    nodes, adj, named = build_graph(ways, river if weighted else None)
    if not weighted and river:
        _, _, named = build_graph(ways, river)   # 같은 좌표 키 → named만 추출
    return nodes, adj, named

def _snap(nodes, named, p):
    if named:
        k, d = nearest_node(nodes, p, named)
        if k is not None and d < 1200: return k
    k, d = nearest_node(nodes, p)
    return k

def weir_zone(anchor, river, up_m, down_m, width_m, pad=0.05):
    """보 기준 상하류 — 앵커에서 물길 양방향으로 지정 거리(실거리, 본류 한정)."""
    nodes, adj, named = _graph(anchor, river, pad, weighted=False)
    # 본류 노드만으로 보행(지류 새기 방지) — 본류 정보 없으면 전체
    if named and len(named) > 30:
        adj = {k: [(v, w) for v, w in vs if v in named] for k, vs in adj.items() if k in named}
    ka = _snap(nodes, named, anchor)
    dist, prev = dijkstra_all(adj, ka)
    def first_hop(k):
        p = reconstruct(prev, ka, k)
        return p[1] if p and len(p) > 1 else None
    lim1, lim2 = max(up_m, down_m), min(up_m, down_m)
    cand = sorted(((d, k) for k, d in dist.items() if d <= lim1 * 1.08), reverse=True)
    end1 = cand[0][1] if cand else None
    h1 = first_hop(end1) if end1 else None
    end2 = None
    for d, k in cand:
        if d > lim2 * 1.08: continue
        if first_hop(k) != h1: end2 = k; break
    pts = []
    if end1 and end2:
        a = reconstruct(prev, ka, end1); b = reconstruct(prev, ka, end2)
        pts = [nodes[k] for k in a[::-1]] + [nodes[k] for k in b[1:]]
    elif end1:
        pts = [nodes[k] for k in reconstruct(prev, ka, end1)]
    if len(pts) < 2:
        pts = [(anchor[0] - 0.004, anchor[1]), (anchor[0] + 0.004, anchor[1])]
    out = [list(pts[0])]
    for p in pts[1:]:
        if haversine(out[-1], list(p)) >= 25: out.append(list(p))
    return buffer_path(out, width_m)

def seg_zone(a, b, river, width_m, pad=0.05):
    nodes, adj, named = _graph([(a[0]+b[0])/2, (a[1]+b[1])/2], river, pad + max(abs(a[0]-b[0]), abs(a[1]-b[1])))
    ka, kb = _snap(nodes, named, a), _snap(nodes, named, b)
    dist, prev = dijkstra_all(adj, ka)
    path = reconstruct(prev, ka, kb)
    pts = [nodes[k] for k in path] if path else [a, b]
    out = [list(pts[0])]
    for p in pts[1:]:
        if haversine(out[-1], list(p)) >= 25: out.append(list(p))
    return buffer_path(out, width_m)

def box(c, w_m, h_m):
    mlat = 110540.0; mlng = 111320.0 * math.cos(math.radians(c[0]))
    dla = h_m/2/mlat; dlo = w_m/2/mlng; la, lo = c
    return [[[round(lo-dlo,6),round(la-dla,6)],[round(lo+dlo,6),round(la-dla,6)],
             [round(lo+dlo,6),round(la+dla,6)],[round(lo-dlo,6),round(la+dla,6)],
             [round(lo-dlo,6),round(la-dla,6)]]]

def lake_zone(name_re, center, fallback_wh, pad=0.06):
    """OSM 수면 폴리곤(이름 매칭, 최대 면적) — 실패 시 박스."""
    s=center[0]-pad; n=center[0]+pad; w=center[1]-pad; e=center[1]+pad
    q=f'[out:json][timeout:50];(way["natural"="water"]["name"~"{name_re}"]({s},{w},{n},{e});relation["natural"="water"]["name"~"{name_re}"]({s},{w},{n},{e}););out geom;'
    try:
        r=urllib.request.urlopen(urllib.request.Request('https://overpass-api.de/api/interpreter',
            data=urllib.parse.urlencode({'data':q}).encode(),headers={'User-Agent':'mycanoe-map/1.0'}),timeout=90)
        els=json.loads(r.read().decode()).get('elements',[])
        best=None
        for el in els:
            geom=el.get('geometry') or (el.get('members',[{}])[0].get('geometry') if el.get('members') else None)
            if geom and (best is None or len(geom)>len(best)): best=geom
        if best and len(best)>=4:
            ring=[[round(p['lon'],6),round(p['lat'],6)] for p in best]
            if ring[0]!=ring[-1]: ring.append(ring[0])
            return [ring]
    except Exception as ex:
        print('  lake fallback:', str(ex)[:40])
    return box(center, *fallback_wh)

ALL_  = "모든 수상레저기구"
MOTOR = "동력수상레저기구"

def main():
    feats = []
    def add(name, rings, target, period, office, note=NOTE):
        feats.append({"type":"Feature","geometry":{"type":"Polygon","coordinates":rings},
                      "properties":{"name":name,"office":office,"period":period,"target":target,"note":note}})
        print(f"  + {name}")
    S=lambda:time.sleep(4)

    # ---- 서울 한강(서울시 고시, 동력만) ----
    add("한강 여의도1구역(물빛무대~마포대교 하류400m)", buffer_path([[37.5323,126.9280],[37.5300,126.9345]],130), MOTOR,"2023.10.6~2026.10.5","서울시",MOTOR_NOTE)
    add("한강 여의도2구역(마포대교 상류~임시선착장)", buffer_path([[37.5295,126.9395],[37.5287,126.9430]],130), MOTOR,"2023.10.6~2026.10.5","서울시",MOTOR_NOTE)
    add("한강 반포구역(세빛섬~반포대교~이크루즈)", buffer_path([[37.5105,126.9930],[37.5125,127.0005]],130), MOTOR,"2023.10.6~2026.10.5","서울시",MOTOR_NOTE)
    add("한강 망원구역(경사로 진입부)", box([37.5505,126.9000],50,20), MOTOR,"2025.6.1~2028.5.31","서울시",MOTOR_NOTE)

    # ---- 한강 수계 ----
    print("신곡수중보…"); add("한강 신곡수중보 구역(김포·고양)", weir_zone([37.6144,126.79303],"한강",1300,1000,650), ALL_,"연중","김포시·고양시"); S()
    print("팔당~강동대교…"); add("한강 팔당댐~강동대교 구역(하남)", seg_zone([37.52656,127.27926],[37.57869,127.16047],"한강",700), ALL_,"연중","하남시"); S()
    print("강동대교~잠실수중보…"); add("한강 강동대교~잠실수중보 구역(구리·잠실상수원)", seg_zone([37.57869,127.16047],[37.5300,127.0850],"한강",700), ALL_,"연중","구리시"); S()
    print("이포보…"); add("남한강 이포보 구역", weir_zone([37.40391,127.53665],"남한강",1000,1000,300), ALL_,"연중","여주시"); S()
    print("여주보…"); add("남한강 여주보 구역", weir_zone([37.32795,127.60783],"남한강",1000,1000,300), ALL_,"연중","여주시"); S()
    print("강천보…"); add("남한강 강천보 구역", weir_zone([37.27754,127.68394],"남한강",1000,1000,300), ALL_,"연중","여주시"); S()
    print("흑천…"); add("흑천 구역(원덕초교~한강 합류)", seg_zone([37.46823,127.54246],[37.4900,127.5060],"흑천",70), ALL_,"연중","양평군"); S()
    print("양평 남한강…"); add("남한강 양평 구역(상수원 일원)", seg_zone([37.5280,127.3160],[37.4890,127.4870],"한강",550), ALL_,"연중","양평군"); S()
    print("조안 삼봉리…"); add("북한강 조안면 구역(상수원)", weir_zone([37.60482,127.31905],"북한강",800,800,450), ALL_,"연중","남양주시"); S()
    print("팔당호 남종면…"); add("팔당호 광주시 구역(남종면 수역)", seg_zone([37.5180,127.3040],[37.4530,127.3180],"한강",600), ALL_,"연중","광주시"); S()
    print("경안천 광주…"); add("경안천 광주시 구역(팔당호~초월읍)", seg_zone([37.4870,127.2830],[37.3650,127.2780],"경안천",120), ALL_,"연중","광주시"); S()
    print("군남…"); add("임진강 군남 상수원 구역", weir_zone([38.10461,127.01762],"임진강",200,3200,250), ALL_,"연중","연천군"); S()
    print("충주 조정지댐…"); add("남한강 충주 조정지댐 구역", weir_zone([37.04467,127.86681],"남한강",500,500,350), ALL_,"연중","충주시"); S()
    print("단양수중보…"); add("남한강 단양수중보 구역", weir_zone([36.9470,128.3220],"남한강",500,500,300), ALL_,"연중","단양군"); S()

    # ---- 수원·의왕 호수/저수지 ----
    print("백운호수…"); add("백운호수", lake_zone("백운",[37.37953,127.00244],(600,500)), ALL_,"연중","의왕시"); S()
    print("왕송호수…"); add("왕송호수", lake_zone("왕송",[37.31798,126.94585],(800,900)), ALL_,"연중","의왕시"); S()
    print("파장저수지…"); add("파장저수지(상수원)", lake_zone("파장",[37.32892,126.99458],(350,350)), ALL_,"연중","수원시"); S()
    print("광교저수지…"); add("광교저수지(상수원)", lake_zone("광교",[37.30727,127.02714],(400,900)), ALL_,"연중","수원시"); S()

    # ---- 영산강·섬진강 ----
    print("승촌보…"); add("영산강 승촌보 구역", weir_zone([35.05599,126.74945],"영산강",1000,1000,250), ALL_,"영구","나주시"); S()
    print("죽산보…"); add("영산강 죽산보 구역", weir_zone([34.97328,126.62469],"영산강",1000,1000,250), ALL_,"연중","나주시"); S()
    print("관방보…"); add("영산강 관방보 구역(담양)", weir_zone([35.32413,126.99093],"영산강",500,350,80), ALL_,"영구","담양군"); S()
    print("곡성 섬진강…"); add("섬진강 곡성 구역(세부 7개소)", weir_zone([35.19768,127.37393],"섬진강",2000,2000,130), ALL_,"6.1~8.31","곡성군"); S()
    print("하동 화개…"); add("섬진강 화개 구역(하동상수원)", weir_zone([35.18838,127.62428],"섬진강",700,700,200), ALL_,"연중","하동군"); S()

    # ---- 낙동강 수계 ----
    print("강정고령보…"); add("낙동강 강정고령보 구역", weir_zone([35.84208,128.46272],"낙동강",300,700,400), ALL_,"연중","대구 달성군"); S()
    print("달성보…"); add("낙동강 달성보 구역", weir_zone([35.73409,128.41689],"낙동강",380,500,350), ALL_,"연중","대구 달성군"); S()
    print("창녕함안보…"); add("낙동강 창녕함안보 구역", weir_zone([35.3797,128.55198],"낙동강",1000,1000,350), ALL_,"연중","함안군"); S()
    print("합천창녕보…"); add("낙동강 합천창녕보 구역", weir_zone([35.59091,128.35628],"낙동강",1000,1000,320), ALL_,"연중","창녕군"); S()
    print("구미보…"); add("낙동강 구미보 구역", weir_zone([36.23684,128.34572],"낙동강",1000,1000,300), ALL_,"연중","구미시"); S()
    print("칠곡보…"); add("낙동강 칠곡보 구역", weir_zone([36.01552,128.39861],"낙동강",1000,1000,300), ALL_,"연중","칠곡군"); S()
    print("구미 상수원…"); add("낙동강 구미 상수원 구역(괴평리~숭선대교)", weir_zone([36.1949,128.36526],"낙동강",100,3250,300), ALL_,"연중","구미시"); S()
    print("안동보…"); add("낙동강 안동보 구역", weir_zone([36.5575,128.6924],"낙동강",250,500,250), ALL_,"연중","안동시"); S()
    print("수하보…"); add("낙동강 수하보 구역", weir_zone([36.57414,128.67493],"낙동강",250,500,250), ALL_,"연중","안동시"); S()
    print("구담보…"); add("낙동강 구담보 구역", weir_zone([36.53894,128.46328],"낙동강",250,500,250), ALL_,"연중","안동시"); S()
    print("밀양강…"); add("밀양강 일원(동력 금지)", weir_zone([35.49049,128.75399],"밀양강",5000,3000,150), MOTOR,"연중","밀양시",MOTOR_NOTE); S()
    print("산청 경호강…"); add("경호강·남강 산청 전 구간(허용 2구간 제외)", seg_zone([35.4150,127.8730],[35.24564,127.9526],"경호강|남강",200), ALL_,"연중","산청군"); S()

    # ---- 기타 ----
    print("용담호…"); add("용담호 전 구역", lake_zone("용담",[35.945,127.50],(5000,5000),pad=0.12), ALL_,"연중","진안군"); S()
    print("진교저수지…"); add("하동 진교저수지(상수원)", lake_zone("진교|백련",[35.02692,127.8828],(350,400)), ALL_,"연중","하동군"); S()
    print("청용저수지…"); add("하동 청용저수지(옥종상수원)", lake_zone("청용",[35.17451,127.85312],(220,380)), ALL_,"연중","하동군")

    fc={"type":"FeatureCollection","features":feats}
    (BASE/"wlz_inland.geojson").write_text(json.dumps(fc,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(f"[done] {len(feats)}개 구역 → wlz_inland.geojson")
    print("제외(위치 미상): 포천 화적연·영로교, 안동댐 산야리 / 중복(상수원 레이어): 일부 구간 겹침 허용")

if __name__ == "__main__":
    main()
