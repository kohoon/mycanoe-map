#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자체포함 Leaflet 지도 map.html 생성 (키 노출 없음).
- 베이스: OpenStreetMap
- 상수원보호구역 면: protect_polygons.geojson 임베드
- 카누 즐겨찾기 점: synced_seqs.json 임베드
- 주소: 프록시(Cloudflare Worker)를 통한 V-World 역지오코딩(지번) + Nominatim 폴백
- 외부지도 딥링크: 모바일 앱(intent/scheme) / 데스크톱 웹
PROXY_URL 은 proxy_url.txt 에서 읽음(없으면 Nominatim 폴백만).
"""
import json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
_pf = BASE / "proxy_url.txt"
PROXY = (_pf.read_text(encoding="utf-8").strip() if _pf.exists() else "")

items = json.loads((BASE / "synced_seqs.json").read_text(encoding="utf-8"))["items"]
pfeats = [{"type": "Feature",
           "geometry": {"type": "Point", "coordinates": [v["lng"], v["lat"]]},
           "properties": {"name": v.get("name", ""), "memo": v.get("memo", "")}}
          for v in items.values() if v.get("lat") is not None]
points = {"type": "FeatureCollection", "features": pfeats}
polygons = json.loads((BASE / "protect_polygons.geojson").read_text(encoding="utf-8"))
print(f"점 {len(pfeats)} / 면 {len(polygons['features'])} / 프록시 {'설정됨' if PROXY else '없음(Nominatim 폴백)'}")

HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>카누 지도 — 상수원보호구역 / 즐겨찾기</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html,body,#map{height:100%;margin:0}
  .legend{background:#fff;padding:8px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font:13px/1.5 sans-serif}
  .legend b{display:block;margin-bottom:4px}
  .sw{display:inline-block;width:12px;height:12px;vertical-align:middle;margin-right:5px;border-radius:2px}
  .leaflet-popup-content{font:13px/1.55 sans-serif}
  .search input{padding:5px 6px;border:1px solid #bbb;border-radius:3px;width:44vw;max-width:200px;font-size:13px}
  .search button{padding:5px 9px;margin-left:3px;cursor:pointer;font-size:13px}
  .sr-item{margin-top:5px;font-size:12px}
  .sr-item a{color:#1565c0;text-decoration:none}
  .addrbtn a{font:600 14px/34px sans-serif;padding:0 12px;display:block;white-space:nowrap}
  #xhair{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:600;
         pointer-events:none;color:#d32f2f;font-size:26px;text-shadow:0 0 2px #fff;opacity:.85}
  .leaflet-control-zoom a{width:40px;height:40px;line-height:40px;font-size:22px}
</style>
</head>
<body>
<div id="map"></div>
<div id="xhair">✛</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const POINTS = __POINTS__;
const POLYS = __POLYS__;
const PROXY = "__PROXY__";   // 역지오코딩 프록시(Cloudflare Worker). 비어있으면 Nominatim 사용

const ua = navigator.userAgent;
const isiOS = /iphone|ipad|ipod/i.test(ua);
const isAndroid = /android/i.test(ua);

const map = L.map('map', {preferCanvas:true, zoomControl:false}).setView([36.3, 127.8], 7);
window.map = map;
L.control.zoom({position:'bottomleft'}).addTo(map);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'© OpenStreetMap'}).addTo(map);

// ---- 외부 지도 딥링크 (안드로이드 intent / iOS scheme / 데스크톱 웹) ----
function extLinks(lat,lng,label){
  const nm=(label||'위치').replace(/,/g,' ').trim().slice(0,30)||'위치';
  const enc=encodeURIComponent(nm);
  let k,n,tgt='';
  if(isAndroid){
    k='intent://look?p='+lat+','+lng+'#Intent;scheme=kakaomap;package=net.daum.android.map;S.browser_fallback_url='+encodeURIComponent('https://map.kakao.com/link/map/'+enc+','+lat+','+lng)+';end';
    n='intent://place?lat='+lat+'&lng='+lng+'&name='+enc+'&appname=kohoon.github.io#Intent;scheme=nmap;package=com.nhn.android.nmap;S.browser_fallback_url='+encodeURIComponent('https://map.naver.com/p/search/'+lat+','+lng)+';end';
  }else if(isiOS){
    k='kakaomap://look?p='+lat+','+lng;
    n='nmap://place?lat='+lat+'&lng='+lng+'&name='+enc+'&appname=kohoon.github.io';
  }else{
    k='https://map.kakao.com/link/map/'+enc+','+lat+','+lng;
    n='https://map.naver.com/p/search/'+lat+','+lng;
    tgt=' target="_blank" rel="noopener"';
  }
  return '<br><a href="'+k+'"'+tgt+'>카카오맵</a> &middot; <a href="'+n+'"'+tgt+'>네이버맵</a>';
}

// ---- 역지오코딩: 프록시(V-World 지번) → 실패시 Nominatim ----
async function proxyReverse(lat,lng){
  if(!PROXY) return null;
  try{
    const r=await fetch(PROXY+'?lat='+lat+'&lng='+lng);
    if(!r.ok) return null;
    const d=await r.json();
    if(d && (d.parcel||d.road)) return {parcel:d.parcel||'', road:d.road||''};
    return null;
  }catch(e){ return null; }
}
async function nominatimReverse(lat,lng){
  try{
    const r=await fetch('https://nominatim.openstreetmap.org/reverse?format=json&accept-language=ko&zoom=18&lat='+lat+'&lon='+lng);
    const d=await r.json();
    if(d&&d.address){
      const a=d.address;
      const o=[a.province||a.state, a.city||a.county, a.town||a.village||a.suburb, a.neighbourhood, a.road].filter(Boolean);
      if(o.length) return o.join(' ');
    }
    return d&&d.display_name ? d.display_name.split(',').reverse().map(s=>s.trim()).join(' ') : '';
  }catch(e){ return ''; }
}
async function showAddress(lat,lng){
  const pop=L.popup().setLatLng([lat,lng]).setContent('주소 조회 중…').openOn(map);
  let r=await proxyReverse(lat,lng);
  let main='', sub='';
  if(r&&(r.parcel||r.road)){ main=r.parcel||r.road; if(r.road&&r.parcel) sub='도로명: '+r.road; }
  else { main=await nominatimReverse(lat,lng); }
  let h='<b>'+(main||'주소를 찾지 못함')+'</b>';
  if(sub) h+='<br><small>'+sub+'</small>';
  h+='<br><small>'+lat.toFixed(5)+', '+lng.toFixed(5)+'</small>'+extLinks(lat,lng,main||'위치');
  pop.setContent(h);
}
map.on('contextmenu', e=>showAddress(e.latlng.lat, e.latlng.lng));   // 데스크톱 우클릭

// ---- 모바일 대체: 중앙 십자선 + '주소' 버튼 (지도 중앙 주소) ----
const AddrCtl = L.Control.extend({ options:{position:'bottomleft'},
  onAdd:function(){
    const d=L.DomUtil.create('div','leaflet-bar addrbtn');
    d.innerHTML='<a href="#" title="지도 중앙(✛) 주소 보기">📍 주소</a>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(d.querySelector('a'),'click',function(e){ L.DomEvent.preventDefault(e); const c=map.getCenter(); showAddress(c.lat,c.lng); });
    return d;
  }
});
map.addControl(new AddrCtl());

// ---- 상수원보호구역 면 ----
L.geoJSON(POLYS, {
  style:{color:'#c62828', weight:1, fillColor:'#e53935', fillOpacity:0.25},
  onEachFeature:(f,l)=>{ if(f.properties&&f.properties.s) l.bindPopup('<b>상수원보호구역</b><br>'+f.properties.s); }
}).addTo(map);

// ---- 카누 즐겨찾기 점 ----
L.geoJSON(POINTS, {
  pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:5,color:'#1565c0',weight:1,fillColor:'#2196f3',fillOpacity:0.9}),
  onEachFeature:(f,l)=>{ const p=f.properties; const c=f.geometry.coordinates;
    let h='<b>'+(p.name||'(이름없음)')+'</b>'; if(p.memo) h+='<br>'+p.memo;
    h+=extLinks(c[1],c[0],p.name); l.bindPopup(h); }
}).addTo(map);

// ---- 장소 검색 (Nominatim) ----
const SearchCtl = L.Control.extend({ options:{position:'topleft'},
  onAdd:function(){
    const d=L.DomUtil.create('div','legend search');
    d.innerHTML='<form id="srchForm"><input id="srchQ" placeholder="장소 검색" autocomplete="off"><button type="submit">검색</button></form><div id="srchRes"></div>';
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    return d;
  }
});
map.addControl(new SearchCtl());
let _res=[];
document.getElementById('srchForm').addEventListener('submit', async (ev)=>{
  ev.preventDefault();
  const q=document.getElementById('srchQ').value.trim(); const box=document.getElementById('srchRes');
  if(!q) return; box.textContent='검색 중…';
  try{
    const r=await fetch('https://nominatim.openstreetmap.org/search?format=json&countrycodes=kr&accept-language=ko&limit=6&q='+encodeURIComponent(q));
    _res=await r.json();
    if(!_res.length){ box.textContent='결과 없음'; return; }
    box.innerHTML=_res.map((x,i)=>'<div class="sr-item"><a href="#" data-i="'+i+'">'+x.display_name.slice(0,38)+'</a></div>').join('');
    box.querySelectorAll('a').forEach(a=>a.addEventListener('click',(ze)=>{
      ze.preventDefault(); const x=_res[a.dataset.i]; const lat=+x.lat,lng=+x.lon;
      map.setView([lat,lng],14);
      L.popup().setLatLng([lat,lng]).setContent('<b>'+x.display_name.slice(0,50)+'</b>'+extLinks(lat,lng,q)).openOn(map);
    }));
  }catch(err){ box.textContent='검색 실패'; }
});

// ---- 범례 ----
const legend = L.control({position:'bottomright'});
legend.onAdd=function(){ const d=L.DomUtil.create('div','legend');
  d.innerHTML='<b>범례</b>'+
    '<span class="sw" style="background:#2196f3"></span>카누 런칭/랜딩 장소<br>'+
    '<span class="sw" style="background:rgba(229,57,53,.4)"></span>상수원보호구역(진입금지)';
  return d; };
legend.addTo(map);
</script>
</body>
</html>
"""

html = (HTML
        .replace("__POINTS__", json.dumps(points, ensure_ascii=False, separators=(",", ":")))
        .replace("__POLYS__", json.dumps(polygons, ensure_ascii=False, separators=(",", ":")))
        .replace("__PROXY__", PROXY))
out = BASE / "map.html"
out.write_text(html, encoding="utf-8")
print(f"생성: map.html ({out.stat().st_size/1024:.0f} KB) — 키 없음")
