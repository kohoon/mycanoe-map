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
  .search input{padding:3px 5px;border:1px solid #bbb;border-radius:3px;width:150px;font-size:12px}
  .search button{padding:3px 8px;margin-left:3px;cursor:pointer;font-size:12px}
  .sr-item{margin-top:4px;font-size:12px}
  .sr-item a{color:#1565c0;text-decoration:none}
  .hint{position:absolute;left:50%;transform:translateX(-50%);bottom:8px;z-index:1000;
        background:rgba(0,0,0,.6);color:#fff;padding:3px 10px;border-radius:12px;font:12px sans-serif}
</style>
</head>
<body>
<div id="map"></div>
<div class="hint">지도를 <b>우클릭</b>하면 주소가 표시됩니다</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const POINTS = __POINTS__;
const POLYS = __POLYS__;

const map = L.map('map', {preferCanvas:true}).setView([36.3, 127.8], 7);
window.map = map;

// 외부 지도 딥링크 (모바일=앱 스킴 / 데스크톱=웹). 좌표로 정확히 센터링.
function isMobile(){ return /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent); }
function extLinks(lat,lng,label){
  // 이름의 쉼표/줄바꿈 제거 (카카오 링크는 쉼표 구분이라 깨짐 방지)
  const nm = (label||'위치').replace(/,/g,' ').trim().slice(0,30) || '위치';
  const enc = encodeURIComponent(nm);
  let k, n, tgt;
  if(isMobile()){
    k = 'kakaomap://look?p='+lat+','+lng;
    n = 'nmap://place?lat='+lat+'&lng='+lng+'&name='+enc+'&appname=kohoon.github.io';
    tgt = '';
  }else{
    k = 'https://map.kakao.com/link/map/'+enc+','+lat+','+lng;
    n = 'https://map.naver.com/p/search/'+lat+','+lng;
    tgt = ' target="_blank" rel="noopener"';
  }
  return '<br><a href="'+k+'"'+tgt+'>카카오맵</a> · <a href="'+n+'"'+tgt+'>네이버맵</a>';
}

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
  onEachFeature:(f,l)=>{ const p=f.properties; const c=f.geometry.coordinates;
    let h='<b>'+(p.name||'(이름없음)')+'</b>'; if(p.memo) h+='<br>'+p.memo;
    h+=extLinks(c[1],c[0],p.name); l.bindPopup(h); }
}).addTo(map);

const overlays = {'상수원보호구역(면)':protect};
overlays['카누 즐겨찾기('+POINTS.features.length+'곳)'] = canoe;
L.control.layers({'OpenStreetMap':osm}, overlays, {collapsed:false}).addTo(map);

// 우클릭 → 역지오코딩(주소보기)  [OSM Nominatim, 키 불필요]
map.on('contextmenu', async (e)=>{
  const lat=e.latlng.lat, lng=e.latlng.lng;
  const pop=L.popup().setLatLng(e.latlng).setContent('주소 조회 중…').openOn(map);
  try{
    const r=await fetch('https://nominatim.openstreetmap.org/reverse?format=json&zoom=18&accept-language=ko&lat='+lat+'&lon='+lng);
    const d=await r.json();
    const addr=(d&&d.display_name)?d.display_name:'주소를 찾지 못함';
    pop.setContent('<b>'+addr+'</b><br><small>'+lat.toFixed(5)+', '+lng.toFixed(5)+'</small>'+extLinks(lat,lng,addr));
  }catch(err){ pop.setContent('주소 조회 실패'); }
});

// 장소 검색 박스 (좌상단)  [Nominatim, 한국 지명/랜드마크]
const SearchCtl = L.Control.extend({ options:{position:'topleft'},
  onAdd:function(){
    const d=L.DomUtil.create('div','legend search');
    d.innerHTML='<form id="srchForm"><input id="srchQ" placeholder="장소 검색(강·유원지 등)" autocomplete="off">'+
      '<button type="submit">검색</button></form><div id="srchRes"></div>';
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    return d;
  }
});
map.addControl(new SearchCtl());
let _res=[];
document.getElementById('srchForm').addEventListener('submit', async (ev)=>{
  ev.preventDefault();
  const q=document.getElementById('srchQ').value.trim(); const box=document.getElementById('srchRes');
  if(!q){ return; } box.textContent='검색 중…';
  try{
    const r=await fetch('https://nominatim.openstreetmap.org/search?format=json&countrycodes=kr&accept-language=ko&limit=6&q='+encodeURIComponent(q));
    _res=await r.json();
    if(!_res.length){ box.textContent='결과 없음'; return; }
    box.innerHTML=_res.map((x,i)=>'<div class="sr-item"><a href="#" data-i="'+i+'">'+x.display_name.slice(0,38)+'</a></div>').join('');
    box.querySelectorAll('a').forEach(a=>a.addEventListener('click',(ze)=>{
      ze.preventDefault(); const x=_res[a.dataset.i]; const lat=+x.lat, lng=+x.lon;
      map.setView([lat,lng],14);
      L.popup().setLatLng([lat,lng]).setContent('<b>'+x.display_name.slice(0,50)+'</b>'+extLinks(lat,lng,q)).openOn(map);
    }));
  }catch(err){ box.textContent='검색 실패'; }
});

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
