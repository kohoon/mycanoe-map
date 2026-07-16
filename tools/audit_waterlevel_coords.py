#!/usr/bin/env python3
"""Audit HRFCO bridge gauge coordinates against VWorld place POIs."""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"
STATIONS = DATA / "hrfco_stations.json"
REPORT = DATA / "waterlevel_coord_audit.json"
OVERRIDES = DATA / "waterlevel_coord_overrides.json"
TRUSTED_EXACT_POIS = {"1018662", "5006670"}  # 청담대교(행정명 표기 차이), 몽탄대교(VWorld 주소 공백)


def hav_m(a, b):
    radius = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def clean(text):
    return re.sub(r"[\s·ㆍ\-\(\)\[\]]", "", text or "")


def facility_name(name):
    match = re.search(r"\(([^()]*(?:교|대교|교량|댐|보))\)$", name)
    if match:
        return match.group(1)
    match = re.match(r"(.+?(?:댐|보))\((?:상류|하류|내|외)\)$", name)
    if match:
        return match.group(1)
    if re.search(r"(?:교|대교|교량|댐|보)$", name):
        return re.sub(r"^[^()]+\((.+)\)$", r"\1", name)
    return ""


def region_tokens(name):
    prefix = name.split("(", 1)[0]
    return [x for x in re.findall(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구)", prefix) if len(x) >= 2]


def request_json(url, params):
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "mycanoe-map-coordinate-audit/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def search_vworld(api_key, query):
    payload = request_json(
        "https://api.vworld.kr/req/search",
        {
            "service": "search",
            "request": "search",
            "version": "2.0",
            "crs": "EPSG:4326",
            "size": 30,
            "page": 1,
            "query": query,
            "type": "place",
            "format": "json",
            "key": api_key,
        },
    )
    return (((payload.get("response") or {}).get("result") or {}).get("items") or [])


def main():
    key_file = BASE / "vworld_key.txt"
    if not key_file.exists():
        sys.exit("vworld_key.txt 필요")
    api_key = key_file.read_text(encoding="utf-8").strip()
    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    bridges = [(station, facility_name(station["nm"])) for station in stations]
    bridges = [(station, name) for station, name in bridges if name]
    rows = []
    for index, (station, name) in enumerate(bridges, 1):
        try:
            items = search_vworld(api_key, name)
        except Exception as exc:
            rows.append({"cd": station["cd"], "nm": station["nm"], "query": name, "error": str(exc)})
            continue
        origin = (station["lat"], station["lng"])
        tokens = region_tokens(station["nm"])
        candidates = []
        for item in items:
            title = re.sub(r"<[^>]+>", "", item.get("title") or "")
            if clean(title) != clean(name):
                continue
            point = item.get("point") or {}
            try:
                target = (float(point["y"]), float(point["x"]))
            except Exception:
                continue
            address = item.get("address") or {}
            address_text = (address.get("road") or "") + " " + (address.get("parcel") or "")
            distance = round(hav_m(origin, target))
            region_match = not tokens or any(token in address_text for token in tokens)
            if region_match or distance <= 1500:
                candidates.append(
                    {
                        "title": title,
                        "address": address_text.strip(),
                        "lat": target[0],
                        "lng": target[1],
                        "distanceM": distance,
                        "regionMatch": region_match,
                    }
                )
        candidates.sort(key=lambda x: (not x["regionMatch"], x["distanceM"]))
        best = candidates[0] if candidates else None
        rows.append(
            {
                "cd": station["cd"],
                "nm": station["nm"],
                "query": name,
                "official": {"lat": station["lat"], "lng": station["lng"]},
                "best": best,
                "candidateCount": len(candidates),
                "action": "review" if best and best["distanceM"] >= 80 else "keep",
            }
        )
        if index % 25 == 0:
            print(f"VWorld 확인 {index}/{len(bridges)}", flush=True)
        time.sleep(0.03)
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stationCount": len(stations),
        "bridgeCount": len(bridges),
        "rows": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    review = [row for row in rows if row.get("action") == "review"]
    accepted = {}
    for row in review:
        best = row.get("best") or {}
        distance = best.get("distanceM", 10**9)
        if not re.search(r"(?:교|대교|교량)$", row.get("query") or ""):
            continue
        # Same-region exact POIs are accepted up to 2 km. Cross-boundary bridges
        # are accepted only when the exact POI is within 750 m.
        if (best.get("regionMatch") and distance <= 2000) or distance <= 750 or row["cd"] in TRUSTED_EXACT_POIS:
            accepted[row["cd"]] = {
                "lat": round(best["lat"], 6),
                "lng": round(best["lng"], 6),
                "name": row["nm"],
                "poi": best["title"],
                "address": best["address"],
                "distanceM": distance,
            }
    OVERRIDES.write_text(json.dumps(accepted, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"완료: 교량형 {len(bridges)}곳, 보정 검토 {len(review)}곳, 확정 {len(accepted)}곳"
        f" -> {REPORT.relative_to(BASE)}, {OVERRIDES.relative_to(BASE)}"
    )


if __name__ == "__main__":
    main()
