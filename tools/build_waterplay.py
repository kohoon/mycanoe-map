#!/usr/bin/env python3
"""생활안전지도 물놀이관리지역 API를 공개용 GeoJSON으로 정제한다."""
import json
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
CREDS = BASE / "safemap_credentials.txt"
API = "https://www.safemap.go.kr/openapi2/IF_0044"


def service_key():
    key = os.environ.get("SAFEMAP_SERVICE_KEY", "").strip()
    if key:
        return key
    if CREDS.exists():
        for line in CREDS.read_text(encoding="utf-8").splitlines():
            if line.startswith("SERVICE_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("SAFEMAP_SERVICE_KEY 또는 safemap_credentials.txt가 필요합니다")


def fetch_page(key, page, rows=1000):
    query = urllib.parse.urlencode({
        "serviceKey": key, "pageNo": page, "numOfRows": rows, "returnType": "json"
    })
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "mycanoe-map/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.load(response)
    if payload.get("header", {}).get("resultCode") != "00":
        raise RuntimeError(payload.get("header", {}))
    body = payload["body"]
    items = body.get("items", {}).get("item", [])
    return items if isinstance(items, list) else [items], int(body.get("totalCount", 0))


def mercator_to_wgs84(x, y):
    lng = x * 180.0 / 20037508.342789244
    lat = math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2)
    return round(lng, 7), round(lat, 7)


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if value in ("", "-") else value


def main():
    key = service_key()
    rows, total, page = [], None, 1
    while total is None or len(rows) < total:
        batch, total = fetch_page(key, page)
        if not batch:
            break
        rows.extend(batch)
        page += 1
    if len(rows) != total:
        raise RuntimeError(f"수집 건수 불일치: {len(rows)}/{total}")

    staff_path = DATA / "waterplay_staff.json"
    staff_data = json.loads(staff_path.read_text(encoding="utf-8")) if staff_path.exists() else {"places": {}}
    staff = staff_data.get("places", {})
    for rule in staff_data.get("rules", []):
        for oid in rule.get("ids", []):
            staff.setdefault(str(oid), rule.get("staff"))
    features = []
    for item in rows:
        lng, lat = mercator_to_wgs84(float(item["x"]), float(item["y"]))
        oid = str(item["objt_id"])
        props = {
            "id": int(item["objt_id"]),
            "name": clean(item.get("plc_nm")),
            "detail": clean(item.get("detail_nm")),
            "province": clean(item.get("ctprvn_nm")),
            "district": clean(item.get("sgg_nm")),
            "town": clean(item.get("emd_nm")),
            "address": clean(item.get("adres")),
            "placeType": clean(item.get("plc_type")),
            "management": clean(item.get("management")),
            "manageCode": clean(item.get("manage_cd")),
            "sectionM": clean(item.get("wtrplay_se")),
            "riskSectionM": clean(item.get("wtrplay_er")),
            "depthAvg": clean(item.get("water_avg")),
            "depthMax": clean(item.get("water_deep")),
            "accidents": clean(item.get("acdt_co")),
            "safetyAction": clean(item.get("safety_act")),
            "note": clean(item.get("etc_note")),
            "equipment": {
                "total": item.get("equip_co"), "sign": item.get("risk_sign"),
                "rescueBox": item.get("rescuship"), "vest": item.get("life_vest"),
                "buoy": item.get("life_buoy"), "rope": item.get("life_rope"),
                "pole": item.get("rescubng")
            },
            "staff": staff.get(oid),
            "sourceYear": 2025
        }
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]}, "properties": props})

    output = {"type": "FeatureCollection", "features": features,
              "meta": {"source": "행정안전부 생활안전지도 IF_0044", "sourceYear": 2025, "count": len(features)}}
    out = BASE / "waterplay.geojson"
    out.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"물놀이 관리지역 {len(features)}곳 -> {out.name} (안전요원 보강 {sum(1 for f in features if f['properties']['staff'])}곳)")


if __name__ == "__main__":
    main()
