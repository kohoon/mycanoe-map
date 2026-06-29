"""전기차 충전소 수집 → ev.geojson (장소·코스 근처만, 관리자 전용 레이어용).

근거: 한국환경공단_전기자동차 충전소 정보 (data.go.kr 15076352)
  GET http://apis.data.go.kr/B552584/EvCharger/getChargerInfo (serviceKey, pageNo, numOfRows; XML)
키: ev_key.txt (data.go.kr 발급 Encoding 키) — gitignore. 런타임은 키 불필요(빌드 임베드).
사용: python build_ev.py  (이후 git add ev.geojson && commit)
"""
import json, math, os, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = Path(__file__).resolve().parent
KEY = (BASE / "ev_key.txt").read_text(encoding="utf-8").strip() if (BASE / "ev_key.txt").exists() else os.environ.get("EV_KEY", "")
if not KEY:
    raise SystemExit("ev_key.txt 없음 — data.go.kr 한국환경공단 전기차충전소 인증키(Encoding) 필요")

RADIUS_KM = 3.0   # 장소·코스에서 이 반경 내 충전소만 수집
ENDPOINT = "http://apis.data.go.kr/B552584/EvCharger/getChargerInfo"
ROWS = 9999

# ---- 앵커(장소 + 코스 샘플점) ----
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

# ---- 전체 페이지 수집 → statId 중복제거 → 근처만 ----
stations = {}   # statId -> {name,busi,addr,lat,lng,n} 또는 {skip:1}
page, total = 1, None
while True:
    url = ENDPOINT + "?serviceKey=" + KEY + f"&pageNo={page}&numOfRows={ROWS}"
    try:
        raw = urllib.request.urlopen(url, timeout=60).read()
    except Exception as e:
        print("fetch err", e); break
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
        if sid in stations:
            if not stations[sid].get("skip"):
                stations[sid]["n"] += 1
            continue
        try:
            lat = float(it.findtext("lat")); lng = float(it.findtext("lng"))
        except Exception:
            continue
        if not near(lat, lng):
            stations[sid] = {"skip": 1}
            continue
        stations[sid] = {"name": it.findtext("statNm") or "충전소", "busi": it.findtext("busiNm") or "",
                         "addr": it.findtext("addr") or "", "lat": lat, "lng": lng, "n": 1}
    kept = sum(1 for s in stations.values() if not s.get("skip"))
    print(f"page {page}: +{len(items)}행 / 근처 {kept}곳")
    if (total and page * ROWS >= total) or len(items) < ROWS:
        break
    page += 1; time.sleep(0.3)

feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lng"], s["lat"]]},
          "properties": {"name": s["name"], "busi": s["busi"], "addr": s["addr"], "n": s["n"]}}
         for s in stations.values() if not s.get("skip")]
json.dump({"type": "FeatureCollection", "features": feats},
          open(BASE / "ev.geojson", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"ev.geojson 생성: {len(feats)}곳(장소·코스 근처)")
