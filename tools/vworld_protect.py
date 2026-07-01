#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vworld_protect.py

V-World 데이터 API로 전국 '상수원보호구역'(LT_C_UM710, 면) 을 받아
각 구역의 대표점(중심점)을 계산해 JSON/CSV 로 저장.

사용:
  python vworld_protect.py --key 발급키 --domain http://localhost

출력:
  protect_points.json  (카카오 추가 단계 입력)
  protect_points.csv   (확인용)
"""
import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
API = "https://api.vworld.kr/req/data"
DATA_ID = "LT_C_UM710"  # 상수원보호

# 대한민국 대략 BBOX (경도 min,max / 위도 min,max) — EPSG:4326
KOR_BBOX = (124.5, 33.0, 131.9, 38.7)


def fetch_page(key, domain, box, page, size=1000):
    params = {
        "service": "data", "request": "GetFeature", "version": "2.0",
        "data": DATA_ID, "key": key, "domain": domain,
        "geomFilter": f"BOX({box[0]},{box[1]},{box[2]},{box[3]})",
        "crs": "EPSG:4326", "geometry": "true", "attribute": "true",
        "size": str(size), "page": str(page), "format": "json",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def extract_features(resp):
    """V-World 응답에서 feature 리스트와 status 반환."""
    res = resp.get("response", resp)
    status = res.get("status")
    if status and status != "OK":
        err = res.get("error") or {}
        return [], status, (err.get("text") or err.get("code") or "")
    result = res.get("result") or {}
    fc = result.get("featureCollection") or {}
    feats = fc.get("features") or []
    return feats, status or "OK", ""


def ring_centroid(ring):
    """폐곡선 ring([[lon,lat],...])의 무게중심(shoelace)."""
    n = len(ring)
    if n < 3:
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (None, None)
    A = cx = cy = 0.0
    for i in range(n - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        A += cross; cx += (x0 + x1) * cross; cy += (y0 + y1) * cross
    if A == 0:
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    A *= 0.5
    return cx / (6 * A), cy / (6 * A)


def ring_area(ring):
    n = len(ring); A = 0.0
    for i in range(n - 1):
        A += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(A) * 0.5


def geom_centroid(geom):
    """Polygon/MultiPolygon GeoJSON에서 대표점(가장 큰 폴리곤의 무게중심)."""
    if not geom:
        return None, None
    t = geom.get("type"); coords = geom.get("coordinates")
    if not coords:
        return None, None
    if t == "Polygon":
        return ring_centroid(coords[0])
    if t == "MultiPolygon":
        best = None; best_a = -1
        for poly in coords:
            if not poly:
                continue
            a = ring_area(poly[0])
            if a > best_a:
                best_a = a; best = poly[0]
        return ring_centroid(best) if best else (None, None)
    # 그 외(혹시 Point/LineString)
    if t == "Point":
        return coords[0], coords[1]
    return None, None


def make_grid(bbox, n):
    x0, y0, x1, y1 = bbox
    dx = (x1 - x0) / n; dy = (y1 - y0) / n
    for i in range(n):
        for j in range(n):
            yield (x0 + i * dx, y0 + j * dy, x0 + (i + 1) * dx, y0 + (j + 1) * dy)


def main():
    ap = argparse.ArgumentParser(description="V-World 상수원보호구역 → 중심점")
    ap.add_argument("--key", required=True, help="V-World 인증키")
    ap.add_argument("--domain", required=True, help="키에 등록한 도메인 (예: http://localhost)")
    ap.add_argument("--grid", type=int, default=6, help="전국 BBOX 격자 분할 수 (기본 6 → 36타일)")
    ap.add_argument("--out", default=str(DATA / "protect_points.json"))
    args = ap.parse_args()

    seen = {}  # mnum -> record
    tiles = list(make_grid(KOR_BBOX, args.grid))
    print(f"[vworld] 전국 BBOX를 {len(tiles)}개 타일로 수집 시작")
    for ti, box in enumerate(tiles, 1):
        page = 1
        while True:
            try:
                resp = fetch_page(args.key, args.domain, box, page)
            except Exception as e:
                print(f"  [타일 {ti}] page {page} 요청 실패: {e}")
                break
            feats, status, msg = extract_features(resp)
            if status != "OK":
                # NOT_FOUND 는 해당 타일에 데이터 없음 → 정상
                if status not in ("NOT_FOUND",):
                    print(f"  [타일 {ti}] status={status} {msg}")
                break
            if not feats:
                break
            for f in feats:
                props = f.get("properties") or {}
                mnum = props.get("mnum") or props.get("id") or f.get("id")
                if mnum in seen:
                    continue
                lon, lat = geom_centroid(f.get("geometry"))
                if lon is None:
                    continue
                seen[mnum] = {
                    "mnum": mnum,
                    "name": props.get("uname") or "상수원보호구역",
                    "sido": props.get("sido_name") or "",
                    "sigg": props.get("sigg_name") or props.get("sigg_nm") or "",
                    "dyear": props.get("dyear") or "",
                    "dnum": props.get("dnum") or "",
                    "lat": round(lat, 7), "lng": round(lon, 7),
                }
            print(f"  [타일 {ti}/{len(tiles)}] page {page}: +{len(feats)} (누적 {len(seen)})")
            if len(feats) < 1000:
                break
            page += 1
            time.sleep(0.3)
        time.sleep(0.2)

    records = list(seen.values())
    # 보기 좋게: 시도→시군구→이름 정렬
    records.sort(key=lambda r: (r["sido"], r["sigg"], str(r["name"])))
    Path(args.out).write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    csv_path = Path(args.out).with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["mnum", "name", "sido", "sigg",
                                           "dyear", "dnum", "lat", "lng"])
        w.writeheader()
        w.writerows(records)
    print(f"\n[done] 상수원보호구역 {len(records)}개 → {Path(args.out).name} / {csv_path.name}")
    if records:
        s = records[0]
        print(f"[sample] {s['sido']} {s['sigg']} {s['name']} ({s['lat']},{s['lng']})")


if __name__ == "__main__":
    main()
