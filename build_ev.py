"""전기차 충전소 수집 → ev.geojson (장소·코스 근처, 관리자 전용 레이어용).

근거: 한국환경공단_전기자동차 충전소 정보 (data.go.kr 15076352)
  GET http://apis.data.go.kr/B552584/EvCharger/getChargerInfo (serviceKey, pageNo, numOfRows; XML)
키: ev_key.txt (Encoding 인증키) — gitignore. 런타임은 키 불필요(빌드 임베드).
사용: python build_ev.py  (이후 git add ev.geojson && commit)
저장 필드(역별 집계): name, busi(운영사), addr, useTime, output(kW들), park(주차무료), note, ct(chgerType 코드들), n(충전기수)
"""
import json, math, os, time, urllib.request, urllib.parse
from collections import Counter
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent
KEY = (BASE / "ev_key.txt").read_text(encoding="utf-8").strip() if (BASE / "ev_key.txt").exists() else os.environ.get("EV_KEY", "")
if not KEY:
    raise SystemExit("ev_key.txt 없음 — data.go.kr 한국환경공단 전기차충전소 인증키(Encoding) 필요")

RADIUS_KM = 3.0
ENDPOINT = "http://apis.data.go.kr/B552584/EvCharger/getChargerInfo"
ROWS = 2000   # 9999는 서버 504 빈발 → 축소(페이지↑ 안정↑)

anchors = []
ss = json.load(open(BASE / "synced_seqs.json", encoding="utf-8")).get("items", {})
for v in (ss.values() if isinstance(ss, dict) else ss):
    if isinstance(v, dict) and v.get("lat") and v.get("lng"):
        anchors.append((v["lat"], v["lng"]))
try:
    cg = json.load(open(BASE / "courses.geojson", encoding="utf-8"))
    for f in cg.get("features", []):
        cs = f.get("geometry", {}).get("coordinates", [])
        for i in range(0, len(cs), 20):
            anchors.append((cs[i][1], cs[i][0]))
except Exception:
    pass
print(f"앵커 {len(anchors)}개, 반경 {RADIUS_KM}km")

def near(lat, lng):
    cl = math.cos(math.radians(lat))
    for (a, b) in anchors:
        dy = (lat - a) * 111.0
        dx = (lng - b) * 111.0 * cl
        if dy * dy + dx * dx <= RADIUS_KM * RADIUS_KM:
            return True
    return False

def fetch_page(page):
    url = ENDPOINT + "?serviceKey=" + KEY + f"&pageNo={page}&numOfRows={ROWS}"
    last = None
    for attempt in range(5):
        try:
            return urllib.request.urlopen(url, timeout=90).read()
        except Exception as e:
            last = e; wait = 2 ** attempt
            print(f"  page {page} 재시도 {attempt+1}/5 ({e}) — {wait}s 대기"); time.sleep(wait)
    raise last

stations = {}   # statId -> dict 또는 {skip:1}
ctCount = Counter()
page, total = 1, None
while True:
    try:
        raw = fetch_page(page)
    except Exception as e:
        print("fetch 최종 실패", e); break
    try:
        root = ET.fromstring(raw)
    except Exception:
        print("parse err(앞 200자):", raw[:200]); break
    if total is None:
        tc = root.findtext(".//totalCount")
        total = int(tc) if (tc and tc.isdigit()) else None
        print("totalCount", total)
    items = root.findall(".//item")
    if not items:
        break
    for it in items:
        sid = it.findtext("statId") or ""
        if not sid:
            continue
        ct = (it.findtext("chgerType") or "").strip()
        if ct:
            ctCount[ct] += 1
        rec = stations.get(sid)
        if rec is not None and rec.get("skip"):
            continue
        try:
            lat = float(it.findtext("lat")); lng = float(it.findtext("lng"))
        except Exception:
            continue
        if rec is None:
            if not near(lat, lng):
                stations[sid] = {"skip": 1}
                continue
            rec = {"sid": sid, "name": it.findtext("statNm") or "충전소", "busi": it.findtext("busiNm") or "",
                   "addr": it.findtext("addr") or "", "loc": it.findtext("location") or "",
                   "call": it.findtext("busiCall") or "", "zcode": (it.findtext("zcode") or ""), "lat": lat, "lng": lng,
                   "useTime": it.findtext("useTime") or "", "park": it.findtext("parkingFree") or "",
                   "limit": (it.findtext("limitYn") or ""), "limitD": (it.findtext("limitDetail") or ""),
                   "note": it.findtext("note") or "", "ct": set(), "out": set(), "n": 0}
            stations[sid] = rec
        rec["n"] += 1
        if ct:
            rec["ct"].add(ct)
        ov = (it.findtext("output") or "").strip()
        if ov:
            rec["out"].add(ov)

    kept = sum(1 for s in stations.values() if not s.get("skip"))
    print(f"page {page}: +{len(items)}행 / 근처 {kept}곳")
    if (total and page * ROWS >= total) or len(items) < ROWS:
        break
    page += 1; time.sleep(0.3)

print("chgerType 코드 분포(전체):", dict(ctCount.most_common()))

feats = []
for s in stations.values():
    if s.get("skip"):
        continue
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lng"], s["lat"]]},
                  "properties": {"sid": s["sid"], "name": s["name"], "busi": s["busi"], "addr": s["addr"], "loc": s["loc"],
                                 "call": s["call"], "zcode": s["zcode"], "useTime": s["useTime"], "park": s["park"],
                                 "limit": s["limit"], "limitD": s["limitD"], "note": s["note"],
                                 "out": sorted(s["out"]), "ct": sorted(s["ct"]), "n": s["n"]}})
json.dump({"type": "FeatureCollection", "features": feats},
          open(BASE / "ev.geojson", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"ev.geojson 생성: {len(feats)}곳(장소·코스 근처)")
