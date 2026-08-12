#!/usr/bin/env python3
"""런칭·랜딩 원본을 Cloudflare Worker 비공개 KV와 동기화한다.

사용:
  python tools/sync_launch_sites.py push
  python tools/sync_launch_sites.py pull
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
WORKER = "https://mycanoe-map.kohoon0140.workers.dev/launch-sites-admin"
SPOTS = ["마이카누", "라온카누", "캐나디언카누클럽", "장자늪카누체험장", "올리버보트", "카페벌곡"]


def admin_key():
    p = BASE / "admin_key.txt"
    if not p.exists():
        raise SystemExit("admin_key.txt 필요")
    return p.read_text(encoding="utf-8").strip()


def call(body):
    req = urllib.request.Request(
        WORKER,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": "https://kohoon.github.io"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def records(source):
    ids = json.loads((DATA / "place_ids.json").read_text(encoding="utf-8")).get("ids", {})
    road = json.loads((DATA / "roadview.json").read_text(encoding="utf-8")) if (DATA / "roadview.json").exists() else {}
    out = []
    for seq, x in source.get("items", {}).items():
        if x.get("lat") is None or x.get("lng") is None or seq not in ids:
            continue
        name = str(x.get("name", ""))
        rv = road.get(str(seq)) or {}
        out.append({
            "id": str(ids[seq]), "name": name, "memo": str(x.get("memo", "")),
            "lat": float(x["lat"]), "lng": float(x["lng"]),
            "cat": "spot" if any(s.replace(" ", "") in name.replace(" ", "") for s in SPOTS) else "canoe",
            "rv": bool(rv.get("rv")), "rvline": rv.get("line"),
        })
    return out


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    target = DATA / "synced_seqs.json"
    if action == "pull":
        source = call({"action": "get", "adminKey": admin_key()})
        target.write_text(json.dumps(source, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"복원: {len(source.get('items', {}))}곳 -> {target}")
    elif action == "push":
        source = json.loads(target.read_text(encoding="utf-8"))
        recs = records(source)
        result = call({"action": "sync", "adminKey": admin_key(), "source": source, "records": recs})
        print(f"동기화: {result.get('count', 0)}곳")
    else:
        raise SystemExit("push 또는 pull 필요")


if __name__ == "__main__":
    main()
