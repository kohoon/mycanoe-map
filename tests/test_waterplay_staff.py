#!/usr/bin/env python3
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    features = json.loads((ROOT / "waterplay.geojson").read_text(encoding="utf-8"))["features"]
    by_id = {f["properties"]["id"]: f["properties"] for f in features}

    current_inje = {390, 391, 392, 393, 394, 395, 396, 397, 399, 400, 402,
                    404, 405, 406, 407, 408, 409, 410, 411, 413, 414, 415,
                    416, 417, 418, 419}
    stale_inje = {398, 401, 403, 412}

    assert all((by_id[i].get("staff") or {}).get("confidence") == "jurisdiction-program"
               for i in current_inje)
    assert all(by_id[i].get("staff") is None for i in stale_inje)
    print("waterplay staffing regression: ok")


if __name__ == "__main__":
    main()
