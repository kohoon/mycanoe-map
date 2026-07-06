#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""홍수정보시스템 수위관측 CCTV 지점 목록을 정적 데이터로 저장.

원본 목록 API는 브라우저 CORS가 없고 Cloudflare Worker 요청에는 522를 반환하므로,
빌드 시 좌표/관측소 코드만 가져와 지도에 임베드한다. 영상은 클릭 시 공식 cctvView.do를
현재 시각 파라미터로 직접 연다.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def kst_ymdhm():
    now = datetime.now(timezone.utc) + timedelta(hours=9)
    now = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
    return now.strftime("%Y%m%d%H%M")


def main():
    ymdhm = kst_ymdhm()
    url = f"https://n.flood.go.kr/main/getData.do?dataType=cctv&ymdhm={ymdhm}"
    req = urllib.request.Request(url, headers={"User-Agent": "mycanoe-map/1.0"})
    raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    items = json.loads(raw)
    out = []
    seen = set()
    for x in items:
        cd = str(x.get("obscd") or "").strip()
        nm = str(x.get("obsnm") or x.get("media_nm") or "").strip()
        try:
            lat, lng = float(x.get("lat")), float(x.get("lon"))
        except Exception:
            continue
        if not cd or not nm or not (33 < lat < 39 and 124 < lng < 131) or cd in seen:
            continue
        seen.add(cd)
        out.append({
            "cd": cd,
            "nm": nm,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "fcodvcd": str(x.get("fcodvcd") or ""),
        })
    out.sort(key=lambda x: (x["nm"], x["cd"]))
    (DATA / "cctv_stations.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"CCTV {len(out)}곳 → data/cctv_stations.json")


if __name__ == "__main__":
    main()
