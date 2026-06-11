#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HRFCO(홍수통제소) 수위관측소 목록 수집 → 카누 장소 근처만 선별 → hrfco_stations.json.

- 키: 환경변수 HRFCO_KEY 또는 hrfco_key.txt (gitignore)
- 전국 1,400여 관측소 중 즐겨찾기 장소/코스 반경 RADIUS_KM 내만 임베드(지도 깔끔).
실행: python build_hrfco.py [반경km=12]
"""
import json, math, os, sys, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
RADIUS_KM = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def key():
    k = os.environ.get("HRFCO_KEY", "").strip()
    if k: return k
    f = BASE / "hrfco_key.txt"
    if f.exists(): return f.read_text(encoding="utf-8").strip()
    sys.exit("[!] HRFCO_KEY 필요(환경변수 또는 hrfco_key.txt)")

def dms(s):
    """'128-33-04' → 십진수. 실패 시 None."""
    try:
        p = [float(x) for x in str(s).strip().split("-")]
        return round(p[0] + p[1]/60 + (p[2] if len(p) > 2 else 0)/3600, 6)
    except Exception:
        return None

def hav_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

def main():
    url = f"https://api.hrfco.go.kr/{key()}/waterlevel/info.json"
    info = json.loads(urllib.request.urlopen(url, timeout=60).read().decode("utf-8"))
    stations = []
    for s in info.get("content", []):
        lat, lon = dms(s.get("lat")), dms(s.get("lon"))
        if lat is None or lon is None or not (33 < lat < 39 and 124 < lon < 131): continue
        stations.append({"cd": s["wlobscd"], "nm": s.get("obsnm",""), "lat": lat, "lng": lon,
                         "att": s.get("attwl",""), "wrn": s.get("wrnwl",""),
                         "alm": s.get("almwl",""), "srs": s.get("srswl","")})
    print(f"전체 관측소(좌표 유효): {len(stations)}")

    # 기준점: 즐겨찾기 장소 + 코스 꼭짓점
    pts = []
    items = json.loads((BASE/"synced_seqs.json").read_text(encoding="utf-8"))["items"]
    pts += [(v["lat"], v["lng"]) for v in items.values() if v.get("lat") is not None]
    try:
        cj = json.loads((BASE/"courses.geojson").read_text(encoding="utf-8"))
        for f in cj["features"]:
            cs = f["geometry"]["coordinates"]
            pts += [(c[1], c[0]) for c in cs[::10]]
    except Exception: pass
    print(f"기준점: {len(pts)}")

    sel = [st for st in stations if any(hav_km((st["lat"], st["lng"]), p) <= RADIUS_KM for p in pts)]
    print(f"선별({RADIUS_KM}km 이내): {len(sel)}")
    (BASE/"hrfco_stations.json").write_text(json.dumps(sel, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print("[done] hrfco_stations.json")

if __name__ == "__main__":
    main()
