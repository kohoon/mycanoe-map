#!/usr/bin/env python3
"""물놀이 관리지역 전수 좌표를 카카오 주소/행정구역 API와 대조한다.

이 스크립트는 원본을 수정하지 않는다. 결과 JSON을 검토한 뒤 명백한
오류만 data/waterplay_coord_overrides.json에 출처와 함께 반영한다.
"""

import argparse
import concurrent.futures
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = Path("/tmp/mycanoe-waterplay-coordinate-audit.json")
KAKAO_API = "https://dapi.kakao.com/v2/local"
_LOCK = threading.Lock()


def kakao_key():
    match = re.search(
        r'^KAKAO_REST_KEY\s*=\s*"([^"]+)"',
        (ROOT / "wrangler.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise SystemExit("wrangler.toml에서 KAKAO_REST_KEY를 찾지 못했습니다")
    return match.group(1)


def api_get(key, path, params, attempts=4):
    url = f"{KAKAO_API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"KakaoAK {key}",
            "User-Agent": "mycanoe-waterplay-coordinate-audit/1.0",
        },
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(0.5 * (2 ** attempt))


def compact(value):
    return re.sub(r"\s+", "", value or "")


def canonical_province(value):
    value = compact(value)
    aliases = {
        "강원도": "강원특별자치도",
        "전라북도": "전북특별자치도",
        "제주도": "제주특별자치도",
        "광주광역시": "전남광주통합특별시",
        "전라남도": "전남광주통합특별시",
    }
    return aliases.get(value, value)


def region_matches(expected, actual):
    expected = compact(expected)
    actual = compact(actual)
    if not expected or not actual:
        return False
    return expected == actual or expected in actual or actual in expected


def address_queries(address):
    raw = re.sub(r"\s+", " ", address or "").strip()
    queries = []
    for query in (
        raw,
        re.sub(r"번지\s*일원$", "", raw).strip(),
        re.sub(r"\s+일원$", "", raw).strip(),
        raw.replace("  ", " "),
    ):
        if query and query not in queries:
            queries.append(query)
    return queries


def haversine_m(a_lng, a_lat, b_lng, b_lat):
    radius = 6371008.8
    a_lat, b_lat = math.radians(a_lat), math.radians(b_lat)
    d_lat = b_lat - a_lat
    d_lng = math.radians(b_lng - a_lng)
    h = math.sin(d_lat / 2) ** 2 + math.cos(a_lat) * math.cos(b_lat) * math.sin(d_lng / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(h)))


def reverse_region(key, lng, lat):
    payload = api_get(key, "geo/coord2regioncode.json", {"x": lng, "y": lat})
    documents = payload.get("documents", [])
    legal = next((row for row in documents if row.get("region_type") == "B"), None)
    row = legal or (documents[0] if documents else None)
    if not row:
        return None
    return {
        "province": row.get("region_1depth_name"),
        "district": row.get("region_2depth_name"),
        "town": row.get("region_3depth_name"),
        "address": row.get("address_name"),
    }


def forward_address(key, address):
    for query in address_queries(address):
        payload = api_get(key, "search/address.json", {"query": query, "size": 5})
        documents = payload.get("documents", [])
        if documents:
            row = documents[0]
            detail = row.get("address") or row.get("road_address") or {}
            return {
                "query": query,
                "lng": float(row["x"]),
                "lat": float(row["y"]),
                "address": row.get("address_name"),
                "province": detail.get("region_1depth_name"),
                "district": detail.get("region_2depth_name"),
                "town": detail.get("region_3depth_name"),
            }
    return None


def normalize_name(value):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").lower()


def keyword_search(key, row):
    declared = row.get("declared") or {}
    name = row.get("name") or ""
    queries = [
        " ".join(filter(None, (declared.get("district"), declared.get("town"), name))),
        " ".join(filter(None, (name, declared.get("district")))),
    ]
    documents = []
    seen = set()
    display = row.get("display") or {}
    wanted = normalize_name(name)
    for query in queries:
        payload = api_get(key, "search/keyword.json", {"query": query, "size": 10})
        for item in payload.get("documents", []):
            place_id = item.get("id")
            if place_id in seen:
                continue
            seen.add(place_id)
            found = normalize_name(item.get("place_name"))
            documents.append({
                "id": place_id,
                "name": item.get("place_name"),
                "address": item.get("address_name"),
                "category": item.get("category_name"),
                "lng": float(item["x"]),
                "lat": float(item["y"]),
                "distanceM": haversine_m(
                    display["lng"], display["lat"], float(item["x"]), float(item["y"])
                ),
                "nameMatch": "exact" if found == wanted else (
                    "contains" if wanted and (wanted in found or found in wanted) else "different"
                ),
            })
        if any(item["nameMatch"] == "exact" for item in documents):
            break
    rank = {"exact": 0, "contains": 1, "different": 2}
    documents.sort(key=lambda item: (rank[item["nameMatch"]], item["distanceM"]))
    return documents[:10]


def audit_one(key, feature):
    props = feature["properties"]
    lng, lat = feature["geometry"]["coordinates"]
    reverse = reverse_region(key, lng, lat)
    forward = forward_address(key, props.get("address"))
    flags = []
    if not (124 <= lng <= 132 and 33 <= lat <= 39.5):
        flags.append("outside_korea_bounds")
    if reverse is None:
        flags.append("reverse_not_found")
    else:
        if canonical_province(props.get("province")) != canonical_province(reverse.get("province")):
            flags.append("province_mismatch")
        address_compact = compact(props.get("address"))
        district_ok = region_matches(props.get("district"), reverse.get("district"))
        if not reverse.get("district") and canonical_province(props.get("province")) == "세종특별자치시":
            district_ok = True
        if not props.get("district") and compact(reverse.get("district")) in address_compact:
            district_ok = True
        if not district_ok:
            flags.append("district_mismatch")
        town_ok = region_matches(props.get("town"), reverse.get("town"))
        if compact(reverse.get("town")) in address_compact:
            town_ok = True
        if props.get("town") and not town_ok:
            flags.append("town_mismatch")
    distance = None
    if forward is None:
        flags.append("address_not_found")
    else:
        distance = haversine_m(lng, lat, forward["lng"], forward["lat"])
        if distance >= 20000:
            flags.append("address_distance_20km")
        elif distance >= 5000:
            flags.append("address_distance_5km")
        elif distance >= 1000:
            flags.append("address_distance_1km")
    return {
        "id": props["id"],
        "name": props.get("name"),
        "address": props.get("address"),
        "declared": {
            "province": props.get("province"),
            "district": props.get("district"),
            "town": props.get("town"),
        },
        "display": {"lng": lng, "lat": lat, "corrected": props.get("coordinateCorrected", False)},
        "reverse": reverse,
        "forward": forward,
        "distanceM": distance,
        "flags": flags,
        "fingerprint": feature_fingerprint(feature),
    }


def feature_fingerprint(feature):
    props = feature["properties"]
    lng, lat = feature["geometry"]["coordinates"]
    return "|".join(str(value or "") for value in (
        props.get("id"), props.get("name"), props.get("address"), lng, lat,
    ))


def load_cache(path):
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["id"]): row for row in payload.get("results", [])}


def save_cache(path, results, total):
    ordered = sorted(results.values(), key=lambda row: row["id"])
    path.write_text(
        json.dumps({"total": total, "completed": len(ordered), "results": ordered}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--keywords", action="store_true",
        help="주소/구역 이상 및 서로 다른 이름의 중복 좌표를 장소명으로 추가 대조",
    )
    args = parser.parse_args()

    features = json.loads((ROOT / "waterplay.geojson").read_text(encoding="utf-8"))["features"]
    results = load_cache(args.cache)
    pending = [
        feature for feature in features
        if results.get(str(feature["properties"]["id"]), {}).get("fingerprint") != feature_fingerprint(feature)
    ]
    key = kakao_key()
    print(f"전체 {len(features)}건 / 캐시 {len(results)}건 / 조회 {len(pending)}건")

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(audit_one, key, feature): feature for feature in pending}
        for future in concurrent.futures.as_completed(futures):
            feature = futures[future]
            try:
                row = future.result()
            except Exception as error:
                props = feature["properties"]
                row = {
                    "id": props["id"], "name": props.get("name"), "address": props.get("address"),
                    "error": f"{type(error).__name__}: {error}", "flags": ["audit_error"],
                }
            with _LOCK:
                results[str(row["id"])] = row
                completed += 1
                if completed % 50 == 0 or completed == len(pending):
                    save_cache(args.cache, results, len(features))
                    print(f"좌표 재검증 {completed}/{len(pending)} (전체 캐시 {len(results)}/{len(features)})")

    duplicate_coordinates = {}
    for feature in features:
        key_coord = ",".join(str(value) for value in feature["geometry"]["coordinates"])
        duplicate_coordinates.setdefault(key_coord, []).append(feature["properties"]["id"])
    duplicates = {key: ids for key, ids in duplicate_coordinates.items() if len(ids) > 1}

    if args.keywords:
        duplicate_ids = set()
        for ids in duplicates.values():
            names = {normalize_name(results[str(oid)].get("name")) for oid in ids}
            if len(names) > 1:
                duplicate_ids.update(ids)
        keyword_rows = [
            row for row in results.values()
            if "keywordCandidates" not in row and (
                (row.get("distanceM") or 0) >= 1000
                or "address_not_found" in row.get("flags", [])
                or "district_mismatch" in row.get("flags", [])
                or row["id"] in duplicate_ids
            )
        ]
        print(f"장소명 추가 대조 {len(keyword_rows)}건")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(keyword_search, key, row): row for row in keyword_rows}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                row = futures[future]
                try:
                    row["keywordCandidates"] = future.result()
                except Exception as error:
                    row["keywordError"] = f"{type(error).__name__}: {error}"
                if index % 25 == 0 or index == len(keyword_rows):
                    save_cache(args.cache, results, len(features))
                    print(f"장소명 진행 {index}/{len(keyword_rows)}")

    rows = list(results.values())
    summary = {
        "total": len(features),
        "completed": len(rows),
        "errors": sum("audit_error" in row.get("flags", []) for row in rows),
        "reverseNotFound": sum("reverse_not_found" in row.get("flags", []) for row in rows),
        "addressNotFound": sum("address_not_found" in row.get("flags", []) for row in rows),
        "provinceMismatch": sum("province_mismatch" in row.get("flags", []) for row in rows),
        "districtMismatch": sum("district_mismatch" in row.get("flags", []) for row in rows),
        "townMismatch": sum("town_mismatch" in row.get("flags", []) for row in rows),
        "distance1km": sum((row.get("distanceM") or 0) >= 1000 for row in rows),
        "distance5km": sum((row.get("distanceM") or 0) >= 5000 for row in rows),
        "distance20km": sum((row.get("distanceM") or 0) >= 20000 for row in rows),
        "duplicateCoordinateGroups": len(duplicates),
        "keywordChecked": sum("keywordCandidates" in row for row in rows),
    }
    payload = {"summary": summary, "duplicateCoordinates": duplicates, "results": sorted(rows, key=lambda r: r["id"])}
    args.cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"결과: {args.cache}")


if __name__ == "__main__":
    main()
