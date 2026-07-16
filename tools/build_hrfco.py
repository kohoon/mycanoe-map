#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HRFCO(홍수통제소) 수위관측소 목록 수집 → 카누 장소 근처만 선별 → hrfco_stations.json.

- 키: 환경변수 HRFCO_KEY 또는 hrfco_key.txt (gitignore)
- 전국 1,400여 관측소 중 즐겨찾기 장소/코스 반경 RADIUS_KM 내만 임베드(지도 깔끔).
실행: python build_hrfco.py [반경km=12]
"""
import json, math, os, sys, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
RADIUS_KM = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
# HRFCO 공식 좌표가 관측기 기준으로 다리 중심/지도 POI와 어긋나는 경우 표시용 보정.
# 수위 조회 코드는 그대로 유지하고 지도 마커 위치만 보정한다.
COORD_OVERRIDES = {
    # 정선군(광하교): 공식 37.369722,128.618889 → VWorld 광하교 POI/다리 중심
    "1001658": (37.368204, 128.619352),
    # 포천시(대회산교): 공식 38.090000,127.220556 → VWorld 대회산교 POI
    "1022642": (38.089208, 127.221601),
    # 포천시(영로대교): 공식 38.065278,127.205833 → VWorld 영로대교 POI
    "1022643": (38.068764, 127.204830),
    # 홍천군(모곡교): 공식 좌표는 강변 육지 쪽 → VWorld 모곡2교 중심
    "1014696": (37.675137, 127.607544),
    # 한덕교: 공식 좌표는 교량 남쪽 하천변 → VWorld 한덕교 중심
    "1014695": (37.675711, 127.611365),
}

# HRFCO info에는 남아 있지만 최신 10M/1H 관측값이 비는 중복·레거시 코드.
# 지도 표시는 유지하되 수위 조회는 바로 옆 실측 코드로 대체한다.
ALT_CODE_OVERRIDES = {
    "1010688": "1010690",  # 춘천댐 → 춘천시(춘천댐)
    "1015639": "1015640",  # 청평댐 → 가평군(청평댐)
    "1018660": "1018662",  # 청담 → 서울시(청담대교)
    "1022665": "1022664",  # 연천군(궁신교) → 궁신교
    "3006650": "3006680",  # 이원 → 옥천군(이원대교)
    "4009668": "4009667",  # 하동 → 하동군(하동저수지)
    "4105660": "4105210",  # 수어댐 → 수어댐(실측 코드)
}

# 카누 판단용 "하천 수위"로 보이면 오해가 큰 지점.
# 댐/저수위 성격 값이거나 0m/EL.m 계열로 들어와 주변 하천 수위와 스케일이 다르다.
EXCLUDE_CODES = {
    "1022644",  # 연천군(한탄강댐): 최신 10M 0.00m, 1H 공백
    "1022645",  # 연천군(한여울교): 47m대 댐 영향/표고성 수위로 일반 하천수위와 혼동
}
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

def _valid_wl(v):
    try:
        return v is not None and str(v).strip() != "" and math.isfinite(float(v))
    except Exception:
        return False

def _first_valid(rows):
    for rec in rows or []:
        if _valid_wl(rec.get("wl")):
            return rec
    return None

def _has_usable_value(key, cd):
    now = ""
    try:
        # 10M: 최신값이 있으면 즉시 통과
        j = json.loads(urllib.request.urlopen(
            f"https://api.hrfco.go.kr/{key}/waterlevel/list/10M/{cd}.json", timeout=30
        ).read().decode("utf-8"))
        if _first_valid(j.get("content")):
            return True
    except Exception:
        pass
    # 10M가 비면 1H/1D까지 확인
    try:
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        from_h = now - timedelta(days=2)
        ymdh = lambda d: d.strftime("%Y%m%d%H")
        j = json.loads(urllib.request.urlopen(
            f"https://api.hrfco.go.kr/{key}/waterlevel/list/1H/{cd}/{ymdh(from_h)}/{ymdh(now)}.json",
            timeout=30
        ).read().decode("utf-8"))
        if _first_valid(j.get("content")):
            return True
    except Exception:
        pass
    try:
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        from_d = now - timedelta(days=7)
        ymd = lambda d: d.strftime("%Y%m%d")
        j = json.loads(urllib.request.urlopen(
            f"https://api.hrfco.go.kr/{key}/waterlevel/list/1D/{cd}/{ymd(from_d)}/{ymd(now)}.json",
            timeout=30
        ).read().decode("utf-8"))
        if _first_valid(j.get("content")):
            return True
    except Exception:
        pass
    return False

def main():
    api_key = key()
    url = f"https://api.hrfco.go.kr/{key()}/waterlevel/info.json"
    info = json.loads(urllib.request.urlopen(url, timeout=60).read().decode("utf-8"))
    stations = []
    for s in info.get("content", []):
        lat, lon = dms(s.get("lat")), dms(s.get("lon"))
        if lat is None or lon is None or not (33 < lat < 39 and 124 < lon < 131): continue
        if s.get("wlobscd") in COORD_OVERRIDES:
            lat, lon = COORD_OVERRIDES[s["wlobscd"]]
        st = {"cd": s["wlobscd"], "nm": s.get("obsnm",""), "lat": lat, "lng": lon,
              "att": s.get("attwl",""), "wrn": s.get("wrnwl",""),
              "alm": s.get("almwl",""), "srs": s.get("srswl","")}
        if st["cd"] in ALT_CODE_OVERRIDES:
            st["alt"] = ALT_CODE_OVERRIDES[st["cd"]]
        stations.append(st)
    print(f"전체 관측소(좌표 유효): {len(stations)}")

    # 기준점: 즐겨찾기 장소 + 코스 꼭짓점
    pts = []
    items = json.loads((DATA/"synced_seqs.json").read_text(encoding="utf-8"))["items"]
    pts += [(v["lat"], v["lng"]) for v in items.values() if v.get("lat") is not None]
    try:
        cj = json.loads((DATA/"courses.geojson").read_text(encoding="utf-8"))
        for f in cj["features"]:
            cs = f["geometry"]["coordinates"]
            pts += [(c[1], c[0]) for c in cs[::10]]
    except Exception: pass
    print(f"기준점: {len(pts)}")

    sel = [st for st in stations if st["cd"] not in EXCLUDE_CODES and not st.get("alt") and any(hav_km((st["lat"], st["lng"]), p) <= RADIUS_KM for p in pts)]
    print(f"선별({RADIUS_KM}km 이내): {len(sel)}")
    live = []
    for i, st in enumerate(sel, 1):
        if _has_usable_value(api_key, st["cd"]):
            live.append(st)
        if i % 25 == 0:
            print(f"  수위값 확인 {i}/{len(sel)}", flush=True)
    print(f"유효값 있음: {len(live)} / {len(sel)}")
    (DATA/"hrfco_stations.json").write_text(json.dumps(live, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print("[done] hrfco_stations.json")

if __name__ == "__main__":
    main()
