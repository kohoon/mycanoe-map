#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자체포함 Leaflet 지도 map.html 생성 (키/서버 불필요 → 어디서나 공유 가능).
- 베이스: OpenStreetMap
- 상수원보호구역 면: protect_polygons.geojson 임베드
- 카누 즐겨찾기 점: synced_seqs.json 임베드 (이름/메모 팝업)
"""
import json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent

# 점
items = json.loads((BASE / "synced_seqs.json").read_text(encoding="utf-8"))["items"]
pfeats = [{"type": "Feature",
           "geometry": {"type": "Point", "coordinates": [v["lng"], v["lat"]]},
           "properties": {"name": v.get("name", ""), "memo": v.get("memo", "")}}
          for v in items.values() if v.get("lat") is not None]
points = {"type": "FeatureCollection", "features": pfeats}

# 면
polygons = json.loads((BASE / "protect_polygons.geojson").read_text(encoding="utf-8"))
print(f"점 {len(pfeats)} / 면 {len(polygons['features'])}")

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>카누 지도 — 상수원보호구역 / 즐겨찾기</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html,body,#map{height:100%;margin:0}
  .legend{background:#fff;padding:8px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font:13px/1.5 sans-serif}
  .legend b{display:block;margin-bottom:4px}
  .sw{display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:5px;border-radius:2px}
  .leaflet-popup-content{font:13px/1.5 sans-serif}
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const POINTS = __POINTS__;
const POLYS = __POLYS__;

const map = L.map('map', {preferCanvas:true}).setView([36.3, 127.8], 7);
window.map = map;

const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'© OpenStreetMap'}).addTo(map);

// 상수원보호구역 면
const protect = L.geoJSON(POLYS, {
  style:{color:'#c62828', weight:1, fillColor:'#e53935', fillOpacity:0.25},
  onEachFeature:(f,l)=>{ if(f.properties && f.properties.s) l.bindPopup('<b>상수원보호구역</b><br>'+f.properties.s); }
}).addTo(map);

// 카누 즐겨찾기 점
const canoe = L.geoJSON(POINTS, {
  pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:5,color:'#1565c0',weight:1,fillColor:'#2196f3',fillOpacity:0.9}),
  onEachFeature:(f,l)=>{ const p=f.properties; let h='<b>'+(p.name||'(이름없음)')+'</b>'; if(p.memo) h+='<br>'+p.memo; l.bindPopup(h); }
}).addTo(map);

const overlays = {'상수원보호구역(면)':protect};
overlays['카누 즐겨찾기('+POINTS.features.length+'곳)'] = canoe;
L.control.layers({'OpenStreetMap':osm}, overlays, {collapsed:false}).addTo(map);

const legend = L.control({position:'bottomright'});
legend.onAdd = function(){
  const d = L.DomUtil.create('div','legend');
  d.innerHTML = '<b>범례</b>'+
    '<span class="sw" style="background:#2196f3"></span>카누 런칭/랜딩 장소<br>'+
    '<span class="sw" style="background:rgba(229,57,53,.4)"></span>상수원보호구역(진입금지)';
  return d;
};
legend.addTo(map);
</script>
</body>
</html>
"""

html = (HTML
        .replace("__POINTS__", json.dumps(points, ensure_ascii=False, separators=(",", ":")))
        .replace("__POLYS__", json.dumps(polygons, ensure_ascii=False, separators=(",", ":"))))
out = BASE / "map.html"
out.write_text(html, encoding="utf-8")
print(f"생성: map.html ({out.stat().st_size/1024:.0f} KB) — 키/서버 불필요, 더블클릭·호스팅 모두 가능")
