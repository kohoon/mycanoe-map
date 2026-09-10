#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location("build_waterplay", ROOT / "tools" / "build_waterplay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_raise(function, *args):
    try:
        function(*args)
    except RuntimeError:
        return
    raise AssertionError("RuntimeError가 발생해야 합니다")


def main():
    payload = json.loads((ROOT / "waterplay.geojson").read_text(encoding="utf-8"))
    features = payload["features"]
    overrides = json.loads((ROOT / "data" / "waterplay_coord_overrides.json").read_text(encoding="utf-8"))
    by_id = {str(feature["properties"]["id"]): feature for feature in features}

    assert len(features) == payload["meta"]["count"] == 1336
    assert len(by_id) == len(features)
    assert payload["meta"]["sourceYear"] == 2025
    assert payload["meta"]["sourceUpdated"] == "2025-07-25"
    assert payload["meta"]["latestVerifiedAt"] == "2026-09-10"
    assert payload["meta"]["coordinateCorrections"] == len(overrides) == 34

    for oid, override in overrides.items():
        feature = by_id[oid]
        assert feature["properties"]["coordinateCorrected"] is True
        assert feature["properties"]["name"] == override["name"]
        assert feature["geometry"]["coordinates"] == [override["lng"], override["lat"]]

    for feature in features:
        lng, lat = feature["geometry"]["coordinates"]
        assert 124 <= lng <= 132 and 33 <= lat <= 39.5

    # 원본에서 서로 다른 장소가 한 점으로 복사됐던 대표 회귀 사례.
    assert len({tuple(by_id[oid]["geometry"]["coordinates"]) for oid in ("49", "50", "51")}) == 3
    assert len({tuple(by_id[oid]["geometry"]["coordinates"]) for oid in ("345", "346", "347", "348")}) == 4
    assert len({tuple(by_id[oid]["geometry"]["coordinates"]) for oid in ("415", "416", "417")}) == 3
    assert len({tuple(by_id[oid]["geometry"]["coordinates"]) for oid in ("1206", "1208", "1215")}) == 3
    assert by_id["1263"]["geometry"]["coordinates"][1] < 35.1

    builder = load_builder()
    must_raise(builder.validate_inputs, [{"objt_id": 1, "plc_nm": "A"}, {"objt_id": 1, "plc_nm": "A"}], {})
    must_raise(builder.validate_inputs, [{"objt_id": 1, "plc_nm": "A"}], {"2": {}})
    must_raise(
        builder.validate_features,
        [{"properties": {"id": 1}, "geometry": {"coordinates": [0, 0]}}],
    )
    print("waterplay coordinate regression: ok")


if __name__ == "__main__":
    main()
