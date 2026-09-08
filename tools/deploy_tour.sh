#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
STAGE_DIR=$(mktemp -d /tmp/mycanoe-tour.XXXXXX)
cleanup() {
  case "$STAGE_DIR" in
    /tmp/mycanoe-tour.*) rm -rf -- "$STAGE_DIR" ;;
  esac
}
trap cleanup EXIT

cd "$ROOT_DIR"
python3 tools/build_map.py
cp tour/index.html "$STAGE_DIR/index.html"
cp protect_polygons.geojson wlz.geojson waterplay.geojson rivers.geojson roads.geojson og.png "$STAGE_DIR/"
npx --yes wrangler pages deploy "$STAGE_DIR" --project-name mycanoe-tour --branch main --commit-dirty=true
