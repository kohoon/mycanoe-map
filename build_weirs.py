#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전국 보(洑) 위치 추출 → weirs.json (카누 장소·코스 근처 선별).

원천: 해양수산부 「어도 현황」(공공데이터포털 15115610, CSV) — 어도가 설치된 보 5,500여 곳의
보 명칭 + DMS 좌표 + 하천명. 어도는 보에 설치되므로 사실상 전국 주요 보 좌표 목록.
실행: python build_weirs.py [반경km=8]  (원본 _eodo.csv 필요 — 재다운로드 가능)
"""
import csv, json, math, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RADIUS_KM = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def hav_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))

def main():
    rows = list(csv.DictReader(open(BASE/"_eodo.csv", encoding="cp949")))
    print(f"어도 레코드: {len(rows)}")
    weirs = {}
    for r in rows:
        try:
            lat = float(r["어도 위치정보(위도-도)"]) + float(r["어도 위치정보(위도-분)"])/60 + float(r["어도 위치정보(위도-초)"])/3600
            lng = float(r["어도 위치정보(경도-도)"]) + float(r["어도 위치정보(경도-분)"])/60 + float(r["어도 위치정보(경도-초)"])/3600
        except Exception:
            continue
        if not (33 < lat < 39 and 124 < lng < 131):
            continue
        nm = (r.get("보 명칭") or "").strip() or "보"
        river = (r.get("어도가 위치한 하천(하위)") or r.get("어도가 위치한 수계") or "").strip()
        key = nm + "|" + f"{round(lat,3)},{round(lng,3)}"   # 같은 보의 복수 어도 병합(~100m)
        if key not in weirs:
            weirs[key] = {"nm": nm, "river": river, "lat": round(lat,5), "lng": round(lng,5)}
    print(f"보(중복 병합): {len(weirs)}")

    pts = []
    items = json.loads((BASE/"synced_seqs.json").read_text(encoding="utf-8"))["items"]
    pts += [(v["lat"], v["lng"]) for v in items.values() if v.get("lat") is not None]
    try:
        cj = json.loads((BASE/"courses.geojson").read_text(encoding="utf-8"))
        for f in cj["features"]:
            pts += [(c[1], c[0]) for c in f["geometry"]["coordinates"][::10]]
    except Exception:
        pass
    sel = [w for w in weirs.values() if any(hav_km((w["lat"], w["lng"]), p) <= RADIUS_KM for p in pts)]
    print(f"선별({RADIUS_KM}km): {len(sel)}")
    (BASE/"weirs.json").write_text(json.dumps(sel, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print("[done] weirs.json")

if __name__ == "__main__":
    main()
