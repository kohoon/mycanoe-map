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
# 브라우저가 V-World를 직접 호출(JSONP). 키는 도메인잠금 상태로 공개됨(사용자 승인).
_kf = BASE / "vworld_key.txt"
VKEY = (_kf.read_text(encoding="utf-8").strip() if _kf.exists() else "")

# 카카오 로그인 OAuth Worker (Redirect URI 와 동일, 끝 슬래시 포함)
WORKER_URL = "https://mycanoe-map.kohoon0140.workers.dev/"
# 어드민(장소등록 권한) 카카오 ID. 고훈 본인 ID. 비면 어드민 없음.
ADMIN_ID = "4936913088"
# GA4 측정 ID (G-XXXXXXXXXX). 받으면 채움. 비면 추적 비활성(no-op).
GA_ID = "G-W75JHWTDYS"
if GA_ID.startswith("G-"):
    GTAG = ('<script async src="https://www.googletagmanager.com/gtag/js?id=' + GA_ID + '"></script>\n'
            '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
            'gtag("js",new Date());gtag("config","' + GA_ID + '");</script>')
else:
    GTAG = '<script>function gtag(){}</script>'

items = json.loads((BASE / "synced_seqs.json").read_text(encoding="utf-8"))["items"]
pfeats = [{"type": "Feature",
           "geometry": {"type": "Point", "coordinates": [v["lng"], v["lat"]]},
           "properties": {"name": v.get("name", ""), "memo": v.get("memo", "")}}
          for v in items.values() if v.get("lat") is not None]
points = {"type": "FeatureCollection", "features": pfeats}
polygons = json.loads((BASE / "protect_polygons.geojson").read_text(encoding="utf-8"))
_cf = BASE / "courses.geojson"
courses = json.loads(_cf.read_text(encoding="utf-8")) if _cf.exists() else {"type": "FeatureCollection", "features": []}
print(f"점 {len(pfeats)} / 면 {len(polygons['features'])} / 코스 {len(courses['features'])} / VKEY {'있음' if VKEY else '없음'}")

HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>카누 지도 — 상수원보호구역 / 즐겨찾기</title>
__GTAG__
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
  #hint{position:absolute;left:50%;bottom:10px;transform:translateX(-50%);z-index:1000;
        background:rgba(0,0,0,.62);color:#fff;padding:5px 12px;border-radius:14px;
        font:12px sans-serif;transition:opacity .6s;pointer-events:none}
  .leaflet-control-zoom a{width:40px;height:40px;line-height:40px;font-size:22px}
  .measbtn{cursor:pointer;font:600 13px sans-serif;background:#fff;color:#222;padding:8px 12px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);white-space:nowrap;user-select:none}
  .measbtn.on{background:#ff7043;color:#fff}
  .measbtn .mx{margin-left:8px;background:rgba(255,255,255,.35);border-radius:8px;padding:1px 7px;cursor:pointer}
  .meas-pill{background:#ff7043;color:#fff;border-radius:11px;padding:2px 8px;font:700 12px sans-serif;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.35);cursor:pointer;text-align:center}
  .locbtn{cursor:pointer;font-size:20px;background:#fff;width:40px;height:40px;line-height:40px;text-align:center;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);user-select:none}
  .locbtn.loading{opacity:.45}
  .loc-dot{filter:drop-shadow(0 0 3px rgba(25,118,210,.6))}
  .addplace-btn{margin-top:7px;background:#00b894;color:#fff;border:0;border-radius:6px;padding:6px 11px;font:600 12px sans-serif;cursor:pointer}
  .addform #apName{width:100%;box-sizing:border-box;padding:6px;margin:6px 0;border:1px solid #bbb;border-radius:4px;font-size:13px}
  .addform .aprow{font:12px sans-serif;margin-bottom:8px;display:flex;flex-direction:column;gap:3px}
  .addform #apSave{background:#00b894;color:#fff;border:0;border-radius:5px;padding:6px 13px;font:600 13px sans-serif;cursor:pointer}
  .addform #apMsg{font-size:12px;color:#666;margin-left:6px}
  .canoe-pin-in{width:26px;height:26px;border-radius:50%;background:#2196f3;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center}
  .canoe-pin-in svg{width:17px;height:auto}
  .authbox{font:600 13px sans-serif}
  .authbox button{background:#FEE500;color:#191600;border:0;border-radius:6px;padding:8px 12px;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.3)}
  .authbox .who{display:inline-block;background:#fff;border-radius:6px;padding:7px 10px;box-shadow:0 1px 4px rgba(0,0,0,.3);max-width:46vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .authbox .who a{color:#1565c0;margin-left:8px;text-decoration:none;cursor:pointer}
  #gate{position:fixed;inset:0;z-index:3000;display:flex;align-items:center;justify-content:center;overflow:hidden;
    background:radial-gradient(125% 90% at 50% 0%,#bfe3ff 0%,#dff1e6 55%,#eef7f0 100%)}
  #gate::before,#gate::after{content:"";position:absolute;border-radius:50%;filter:blur(10px);opacity:.45;pointer-events:none}
  #gate::before{width:260px;height:260px;background:#9ad0ff;top:-70px;left:-60px}
  #gate::after{width:300px;height:300px;background:#bfe6c4;bottom:-90px;right:-70px}
  .gate-card{position:relative;background:rgba(255,255,255,.92);backdrop-filter:blur(6px);border-radius:22px;
    padding:34px 26px 28px;max-width:352px;width:86%;text-align:center;box-shadow:0 18px 50px rgba(20,60,90,.22);animation:gateIn .5s ease}
  @keyframes gateIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
  .gate-logo{width:74px;height:74px;margin:0 auto;border-radius:50%;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(150deg,#2196f3,#00b894);box-shadow:0 8px 20px rgba(0,150,180,.35);animation:floaty 3s ease-in-out infinite}
  .canoe-ico{width:52px;height:auto;filter:drop-shadow(0 2px 3px rgba(0,0,0,.18))}
  @keyframes floaty{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
  .gate-card h1{margin:16px 0 4px;font:800 23px sans-serif;color:#13312a;letter-spacing:-.3px}
  .gate-sub{color:#5a6b62;font:14px sans-serif;margin:0 0 18px}
  .gate-feats{list-style:none;margin:0 0 22px;padding:0;text-align:left;display:inline-block}
  .gate-feats li{display:flex;align-items:center;gap:10px;margin:9px 0;font:13.5px sans-serif;color:#33473e}
  .gate-feats li span:first-child{width:26px;height:26px;flex:none;border-radius:8px;background:#eef5f1;display:flex;align-items:center;justify-content:center;font-size:15px}
  .kakao-btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;background:#FEE500;color:#191600;border:0;
    border-radius:12px;padding:14px 18px;font:700 15.5px sans-serif;cursor:pointer;box-shadow:0 6px 16px rgba(254,229,0,.5);transition:transform .08s}
  .kakao-btn:active{transform:translateY(1px)}
  .kakao-ico{width:20px;height:20px;fill:#191600}
  .gate-card small{display:block;margin-top:14px;color:#9aa6a0;font-size:11.5px}
</style>
</head>
<body>
<div id="map"></div>
<div id="hint"></div>
<div id="gate">
  <div class="gate-card">
    <div class="gate-logo"><svg class="canoe-ico" viewBox="0 0 64 40" aria-hidden="true">
      <path d="M2 20C2 13 16 10 32 10C48 10 62 13 62 20C62 27 48 30 32 30C16 30 2 27 2 20Z" fill="#fff"/>
      <path d="M9.5 20C9.5 15.7 19.5 13.8 32 13.8C44.5 13.8 54.5 15.7 54.5 20C54.5 24.3 44.5 26.2 32 26.2C19.5 26.2 9.5 24.3 9.5 20Z" fill="#dfeefb"/>
      <path d="M23 15.2V24.8M41 15.2V24.8" stroke="#bcd6ea" stroke-width="1.5" stroke-linecap="round"/>
    </svg></div>
    <h1>마이카누 지도</h1>
    <p class="gate-sub">전국 카누 명소를 한눈에</p>
    <ul class="gate-feats">
      <li><span>💧</span><span>상수원보호구역 안내</span></li>
      <li><span>📍</span><span>카누 런칭·랜딩 장소</span></li>
      <li><span>🛶</span><span>카누잉 추천 코스</span></li>
      <li><span>📏</span><span>물길 거리 측정</span></li>
    </ul>
    <button id="gateLogin" class="kakao-btn"><svg class="kakao-ico" viewBox="0 0 24 24"><path d="M12 3.4C6.7 3.4 2.4 6.9 2.4 11.1c0 2.7 1.8 5.1 4.5 6.5-.2.7-.7 2.5-.8 2.9-.1.5.2.5.4.4.2-.1 2.5-1.7 3.5-2.4.5.1 1 .2 1.5.2 5.3 0 9.6-3.4 9.6-7.6S17.3 3.4 12 3.4z"/></svg>카카오로 시작하기</button>
    <small>로그인 후 바로 이용할 수 있어요</small>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const POINTS = __POINTS__;
const POLYS = __POLYS__;
const COURSES = __COURSES__;
const VKEY = "__VKEY__";   // V-World 키(도메인잠금). 브라우저가 직접 호출. 비면 Nominatim
const WORKER_URL = "__WORKER__";  // 카카오 로그인 OAuth Worker
const GA_ID = "__GA_ID__";        // GA4 측정 ID(비면 추적 off)
const ADMIN_ID = "__ADMIN__";     // 어드민 카카오 ID(장소등록 권한)
function isAdmin(){ const u=getUser(); return !!(u&&u.uid&&ADMIN_ID&&String(u.uid)===String(ADMIN_ID)); }

// ---- 사용량 추적 + 카카오 로그인 세션 ----
function gaEvent(name, params){ try{ if(window.gtag) gtag('event', name, params||{}); }catch(e){} }
function getUser(){ try{ return JSON.parse(localStorage.getItem('mc_user')||'null'); }catch(e){ return null; } }
function setUser(u){ try{ u?localStorage.setItem('mc_user',JSON.stringify(u)):localStorage.removeItem('mc_user'); }catch(e){} }
function logVisit(){   // 접속(자동로그인 재접속)마다 기록 → Worker → 시트
  try{ const u=getUser(); if(!u||!u.uid) return;
    fetch(WORKER_URL.replace(/\/+$/,'')+'/log',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:u.uid, nick:u.nick||'', type:'visit'})}).catch(function(){});
  }catch(e){}
}
(function(){   // 로그인 콜백(#login=ID&nick=NICK) 처리 + 세션 복원
  const h=location.hash||'', m=h.match(/login=([^&]+)/), nk=h.match(/nick=([^&]*)/);
  if(m){
    const uid=decodeURIComponent(m[1]), nick=nk?decodeURIComponent(nk[1]):'';
    setUser({uid:uid, nick:nick, t:Date.now()});
    history.replaceState(null,'',location.pathname+location.search);
    if(window.gtag) gtag('set',{user_id:uid});
    gaEvent('login',{method:'kakao'});
  } else { const u=getUser(); if(u&&u.uid){ if(window.gtag) gtag('set',{user_id:u.uid}); logVisit(); } }
})();
// 로그인 관문: 미로그인 시 지도 차단(로그인 화면 표시)
function showGate(){ const g=document.getElementById('gate'); if(g) g.style.display='flex'; }
function hideGate(){ const g=document.getElementById('gate'); if(g) g.style.display='none'; }
(function(){
  const gb=document.getElementById('gateLogin');
  if(gb) gb.onclick=function(){ gaEvent('login_start'); location.href=WORKER_URL; };
  const u=getUser(); (u&&u.uid)?hideGate():showGate();
})();
function renderAuth(){
  const d=document.getElementById('authbox'); if(!d) return;
  const u=getUser();
  if(u&&u.uid){
    d.innerHTML='<span class="who">👤 '+(u.nick||'사용자').replace(/[<>]/g,'')+' <a id="logoutA">로그아웃</a></span>';
    const lo=document.getElementById('logoutA'); if(lo) L.DomEvent.on(lo,'click',function(e){ L.DomEvent.stop(e); setUser(null); gaEvent('logout'); renderAuth(); showGate(); });
  } else {
    d.innerHTML='<button id="loginA">카카오 로그인</button>';
    const lb=document.getElementById('loginA'); if(lb) L.DomEvent.on(lb,'click',function(e){ L.DomEvent.stop(e); gaEvent('login_start'); location.href=WORKER_URL; });
  }
}
const AuthCtl=L.Control.extend({ options:{position:'topright'},
  onAdd:function(){ const d=L.DomUtil.create('div','authbox'); d.id='authbox'; L.DomEvent.disableClickPropagation(d); setTimeout(renderAuth,0); return d; } });

const ua = navigator.userAgent;
const isiOS = /iphone|ipad|ipod/i.test(ua);
const isAndroid = /android/i.test(ua);

const map = L.map('map', {preferCanvas:true, zoomControl:false}).setView([36.3, 127.8], 7);
window.map = map;
let measureMode = false;   // 물길 거리측정 모드
L.control.zoom({position:'bottomleft'}).addTo(map);
map.addControl(new AuthCtl());   // 카카오 로그인 박스(우상단)

const baseOSM = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'© OpenStreetMap'}).addTo(map);
const baseSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:19, attribution:'Tiles © Esri'});

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

// ---- 역지오코딩: V-World 직접 호출(JSONP, 지번) → 실패시 Nominatim ----
let _jpId=0;
function vworldReverse(lat,lng){
  return new Promise(function(resolve){
    if(!VKEY){ resolve(null); return; }
    const name='__vw'+(_jpId++); let done=false;
    const s=document.createElement('script');
    function cleanup(){ try{ delete window[name]; }catch(e){} if(s.parentNode) s.parentNode.removeChild(s); }
    const timer=setTimeout(function(){ if(!done){ done=true; cleanup(); resolve(null);} }, 6000);
    window[name]=function(d){ if(done) return; done=true; clearTimeout(timer);
      try{ const r=d.response;
        if(r&&r.status==='OK'&&r.result&&r.result.length){
          const par=r.result.find(function(x){return x.type==='parcel';});
          const road=r.result.find(function(x){return x.type==='road';});
          resolve({parcel:par?par.text:'', road:road?road.text:''});
        } else resolve(null);
      }catch(e){ resolve(null); } cleanup();
    };
    s.onerror=function(){ if(!done){ done=true; clearTimeout(timer); cleanup(); resolve(null);} };
    s.src='https://api.vworld.kr/req/address?service=address&request=getAddress&version=2.0&crs=EPSG:4326'+
          '&type=both&format=json&point='+lng+','+lat+'&key='+VKEY+'&callback='+name;
    document.body.appendChild(s);
  });
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
let _lastAddr=0;
async function showAddress(lat,lng){
  const now=Date.now(); if(now-_lastAddr<800) return; _lastAddr=now;   // 중복 호출 방지
  const pop=L.popup().setLatLng([lat,lng]).setContent('주소 조회 중…').openOn(map);
  let r=await vworldReverse(lat,lng);
  let main='', sub='';
  if(r&&(r.parcel||r.road)){ main=r.parcel||r.road; if(r.road&&r.parcel) sub='도로명: '+r.road; }
  else { main=await nominatimReverse(lat,lng); }
  let h='<b>'+(main||'주소를 찾지 못함')+'</b>';
  if(sub) h+='<br><small>'+sub+'</small>';
  h+='<br><small>'+lat.toFixed(5)+', '+lng.toFixed(5)+'</small>'+extLinks(lat,lng,main||'위치');
  window._curAddr={lat:lat, lng:lng, name:main||''};
  if(isAdmin()) h+='<br><button class="addplace-btn" onclick="addPlace()">📌 장소 등록</button>';
  pop.setContent(h);
}
// ---- 어드민: 장소 등록 ----
const regLayer=L.layerGroup().addTo(map);
function placeColors(cat){ const pink=(cat==='명소'); return {pink:pink,r:pink?7:5,line:pink?'#ad1457':'#1565c0',fill:pink?'#ec407a':'#2196f3'}; }
function addPlaceMarker(pl){ const c=placeColors(pl.cat);
  L.circleMarker([pl.lat,pl.lng],{radius:c.r,color:c.line,weight:1,fillColor:c.fill,fillOpacity:.95}).addTo(regLayer)
   .bindPopup('<b>'+(pl.name||'')+'</b>'+extLinks(pl.lat,pl.lng,pl.name||'위치')); }
function loadPlaces(){ if(!WORKER_URL) return;
  fetch(WORKER_URL.replace(/\/+$/,'')+'/places').then(function(r){return r.json();})
    .then(function(list){ (list||[]).forEach(addPlaceMarker); }).catch(function(){}); }
loadPlaces();
function addPlace(){
  if(!isAdmin()) return; const a=window._curAddr; if(!a) return;
  const html='<div class="addform"><b>장소 등록</b>'
    +'<input id="apName" placeholder="장소 이름" value="'+(a.name||'').replace(/["<>]/g,'')+'">'
    +'<div class="aprow"><label><input type="radio" name="apc" value="명소">카누명소(핑크)</label>'
    +'<label><input type="radio" name="apc" value="런칭랜딩" checked>런칭/랜딩(파랑)</label></div>'
    +'<button id="apSave">저장</button> <span id="apMsg"></span></div>';
  L.popup({minWidth:240}).setLatLng([a.lat,a.lng]).setContent(html).openOn(map);
  setTimeout(function(){ const sv=document.getElementById('apSave'); if(!sv) return;
    sv.onclick=async function(){
      const nm=(document.getElementById('apName').value||'').trim(); if(!nm){ document.getElementById('apMsg').textContent='이름 입력'; return; }
      const cc=document.querySelector('input[name=apc]:checked'); const cat=cc?cc.value:'런칭랜딩';
      const msg=document.getElementById('apMsg'); msg.textContent='저장 중…'; const u=getUser();
      try{ const r=await fetch(WORKER_URL.replace(/\/+$/,'')+'/places',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({id:u.uid,nick:u.nick||'',name:nm,cat:cat,lat:a.lat,lng:a.lng})});
        if(r.ok){ msg.textContent='완료!'; addPlaceMarker({name:nm,cat:cat,lat:a.lat,lng:a.lng}); gaEvent('place_add',{cat:cat}); setTimeout(function(){map.closePopup();},700); }
        else { msg.textContent=(r.status===403?'권한 없음':'실패'); }
      }catch(e){ msg.textContent='오류'; }
    };
  },0);
}
map.on('contextmenu', e=>showAddress(e.latlng.lat, e.latlng.lng));   // 데스크톱 우클릭

// ---- 모바일: 더블탭 → 우클릭과 동일하게 주소 표시 (롱프레스는 기본기능과 충돌) ----
const isTouch = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
if(isTouch){
  map.doubleClickZoom.disable();   // 더블탭 줌 끄고 주소 보기로 사용(줌은 좌하단 버튼)
  const el=map.getContainer(); let lastTap=0, lx=0, ly=0;
  el.addEventListener('touchend', function(e){
    if(measureMode) return;
    if(e.changedTouches.length!==1) return;
    const t=e.changedTouches[0], now=Date.now();
    if(now-lastTap<320 && Math.abs(t.clientX-lx)<24 && Math.abs(t.clientY-ly)<24){
      const r=el.getBoundingClientRect();
      const ll=map.containerPointToLatLng(L.point(t.clientX-r.left, t.clientY-r.top));
      showAddress(ll.lat, ll.lng);
      lastTap=0;
    } else { lastTap=now; lx=t.clientX; ly=t.clientY; }
  }, {passive:true});
}

// 안내 토스트 (잠깐 표시 후 사라짐)
(function(){
  const h=document.getElementById('hint');
  h.textContent = isTouch ? '지도를 더블탭해 주소 보기' : '지도를 우클릭해 주소 보기';
  setTimeout(function(){ h.style.opacity='0'; }, 4500);
})();

// ---- 상수원보호구역 면 ----
const protectLayer = L.geoJSON(POLYS, {
  style:{color:'#c62828', weight:1, fillColor:'#e53935', fillOpacity:0.25},
  onEachFeature:(f,l)=>{ if(f.properties&&f.properties.s) l.bindPopup('<b>상수원보호구역</b><br>'+f.properties.s); }
}).addTo(map);

// ---- 카누잉코스 (물길 따라, 에메랄드 단일색 + 외곽선) ----
const EMERALD = '#00b894';
function courseSubcat(name){ const m=(name||'').match(/^([^#0-9]+)/); return (m?m[1]:'코스').trim()||'코스'; }
const _courseGroups={};   // 서브카테고리 -> features
COURSES.features.forEach(function(f){ const sc=courseSubcat((f.properties||{}).name);
  (_courseGroups[sc]=_courseGroups[sc]||[]).push(f); });
const courseLayers={};    // 서브카테고리 -> layerGroup
Object.keys(_courseGroups).forEach(function(sc){
  const fc={type:'FeatureCollection',features:_courseGroups[sc]};
  const casing=L.geoJSON(fc,{style:{color:'#05382f',weight:8,opacity:0.5}});
  const line=L.geoJSON(fc,{style:{color:EMERALD,weight:5,opacity:0.95},
    onEachFeature:(f,l)=>{ const p=f.properties||{};
      const html='<b>'+(p.name||'카누잉코스')+'</b>'+(p.km?'<br>약 '+p.km+'km':'');
      l.bindPopup(html); l.bindTooltip(html,{sticky:true,direction:'top',opacity:0.95}); }
  });
  courseLayers[sc]=L.layerGroup([casing,line]).addTo(map);
});

// ---- 카누 점: 명소(핑크) vs 런칭/랜딩(파랑) ----
const SPOTS=['마이카누','라온카누','캐나디언카누클럽','장자늪카누체험장','올리버보트'];
function isSpot(nm){ nm=(nm||'').replace(/\s/g,''); return SPOTS.some(function(s){ return nm.indexOf(s.replace(/\s/g,''))>=0; }); }
function ptPopup(f){ const p=f.properties, c=f.geometry.coordinates;
  let h='<b>'+(p.name||'(이름없음)')+'</b>'; if(p.memo) h+='<br>'+p.memo;
  h+=extLinks(c[1],c[0],p.name); return h; }
const spotFeats={type:'FeatureCollection',features:POINTS.features.filter(function(f){return isSpot(f.properties.name);})};
const landFeats={type:'FeatureCollection',features:POINTS.features.filter(function(f){return !isSpot(f.properties.name);})};
const CANOE_SVG='<svg viewBox="0 0 64 40"><path d="M2 20C2 13 16 10 32 10C48 10 62 13 62 20C62 27 48 30 32 30C16 30 2 27 2 20Z" fill="#fff"/><path d="M9.5 20C9.5 15.7 19.5 13.8 32 13.8C44.5 13.8 54.5 15.7 54.5 20C54.5 24.3 44.5 26.2 32 26.2C19.5 26.2 9.5 24.3 9.5 20Z" fill="#cfe3f5"/><path d="M23 15.5V24.5M41 15.5V24.5" stroke="#5a9bd4" stroke-width="2.2" stroke-linecap="round"/></svg>';
function canoeIcon(){ return L.divIcon({className:'canoe-pin',html:'<span class="canoe-pin-in">'+CANOE_SVG+'</span>',iconSize:[26,26],iconAnchor:[13,13]}); }
const famousLayer = L.geoJSON(spotFeats, {
  pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:7,color:'#ad1457',weight:1,fillColor:'#ec407a',fillOpacity:0.95}),
  onEachFeature:(f,l)=>l.bindPopup(ptPopup(f))
}).addTo(map);
const canoeLayer = L.geoJSON(landFeats, {
  pointToLayer:(f,ll)=>L.marker(ll,{icon:canoeIcon()}),
  onEachFeature:(f,l)=>l.bindPopup(ptPopup(f))
}).addTo(map);

// ---- 레이어 토글 ----
const _ov = {};
_ov['상수원보호구역(면)'] = protectLayer;
Object.keys(courseLayers).forEach(function(sc){ _ov['카누잉코스 · '+sc+'('+_courseGroups[sc].length+')']=courseLayers[sc]; });
_ov['카누명소('+spotFeats.features.length+'곳)'] = famousLayer;
_ov['카누 런칭/랜딩('+landFeats.features.length+'곳)'] = canoeLayer;
_ov['등록장소'] = regLayer;
L.control.layers({'일반지도':baseOSM, '위성지도':baseSat}, _ov, {collapsed:true, position:'topright'}).addTo(map);

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
  if(!q) return; box.textContent='검색 중…'; gaEvent('search',{q:q.slice(0,40)});
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

// ---- 물길 거리측정 (두 점 클릭 → 강 따라 거리) ----
// 출발→경유…→완료. 완료한 측정은 유지(호버 거리표시 + ✕닫기), 여러 개 동시.
let measPts=[], measSegs=[];
const measDraft=L.layerGroup().addTo(map);   // 측정 중 임시 표시
const measDone=L.layerGroup().addTo(map);    // 완료된 측정(영구)
const MeasureCtl = L.Control.extend({ options:{position:'topleft'},
  onAdd:function(){
    const d=L.DomUtil.create('div','measbtn'); d.id='measBtnBox'; d.innerHTML='📏 거리측정';
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    L.DomEvent.on(d,'click',function(e){ L.DomEvent.preventDefault(e); measureMode?finishMeasure():startMeasure(); });
    return d;
  }
});
map.addControl(new MeasureCtl());
function updateMeasBtn(){
  const b=document.getElementById('measBtnBox'); if(!b) return;
  b.classList.toggle('on', measureMode);
  if(!measureMode){ b.innerHTML='📏 거리측정'; return; }
  const km=measSegs.reduce(function(s,x){return s+x.km;},0);
  b.innerHTML = (measPts.length<1) ? '📍 출발점 클릭'
    : '🏁 완료 ('+km.toFixed(1)+'km)<span class="mx" id="measCancel">취소</span>';
  const c=document.getElementById('measCancel');
  if(c) L.DomEvent.on(c,'click',function(e){ L.DomEvent.stop(e); cancelMeasure(); });
}
function startMeasure(){ measureMode=true; measPts=[]; measSegs=[]; measDraft.clearLayers(); map.getContainer().style.cursor='crosshair'; updateMeasBtn(); }
function cancelMeasure(){ measureMode=false; measPts=[]; measSegs=[]; measDraft.clearLayers(); map.getContainer().style.cursor=''; updateMeasBtn(); }
map.on('click', async function(e){
  if(!measureMode) return;
  const pt=e.latlng;
  if(measPts.length===0){
    measPts.push(pt);
    L.circleMarker(pt,{radius:5,color:'#bf360c',fillColor:'#ff7043',fillOpacity:1}).addTo(measDraft);
    updateMeasBtn(); return;
  }
  const tmp=L.circleMarker(pt,{radius:4,color:'#bf360c',fillColor:'#ffab91',fillOpacity:1}).addTo(measDraft);
  const b=document.getElementById('measBtnBox'); if(b) b.innerHTML='⏳ 물길 계산 중…';
  let seg=null; try{ seg=await waterRoute(measPts[measPts.length-1], pt); }catch(err){ seg={err:'overpass'}; }
  if(!seg || seg.err){
    measDraft.removeLayer(tmp);
    L.popup({closeButton:false}).setLatLng(pt).setContent(seg&&seg.err==='overpass'?'서버 혼잡 — 잠시 후 다시 클릭':'이 구간 물길 못 찾음<br><small>더 가까운 점/경유지를 찍어보세요</small>').openOn(map);
    updateMeasBtn(); return;
  }
  L.polyline(seg.coords,{color:'#ff7043',weight:4,opacity:.85,dashArray:seg.straight?'6,8':null}).addTo(measDraft);
  measSegs.push(seg); measPts.push(pt); updateMeasBtn();
});
function finishMeasure(){
  if(measPts.length<2){ cancelMeasure(); return; }
  const km=measSegs.reduce(function(s,x){return s+x.km;},0);
  measDraft.clearLayers();
  const grp=L.layerGroup().addTo(measDone);
  measSegs.forEach(function(sg){
    L.polyline(sg.coords,{color:'#ff7043',weight:5,opacity:.95,lineCap:'round',dashArray:sg.straight?'6,8':null})
      .bindTooltip('거리 '+km.toFixed(1)+'km',{sticky:true,opacity:.95}).addTo(grp);
  });
  measPts.forEach(function(p){ L.circleMarker(p,{radius:4,color:'#bf360c',fillColor:'#ff7043',fillOpacity:1}).addTo(grp); });
  const end=measPts[measPts.length-1];
  const pill=L.marker(end,{icon:L.divIcon({className:'meas-pill',html:km.toFixed(1)+'km&nbsp;✕',iconSize:[64,22],iconAnchor:[32,30]}),riseOnHover:true}).addTo(grp);
  pill.on('click', function(){ measDone.removeLayer(grp); });
  pill.bindTooltip('클릭하면 이 측정 삭제',{direction:'top'});
  gaEvent('measure_done',{km:Math.round(km*10)/10, points:measPts.length});
  measureMode=false; measPts=[]; measSegs=[]; map.getContainer().style.cursor=''; updateMeasBtn();
}
// Overpass 미러 + 재시도 (서버 혼잡 대응)
async function overpassFetch(q){
  const mirrors=['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter','https://overpass.private.coffee/api/interpreter'];
  for(let i=0;i<6;i++){
    try{
      const ctrl=new AbortController(); const tid=setTimeout(()=>ctrl.abort(), 18000);
      const r=await fetch(mirrors[i%mirrors.length],{method:'POST',signal:ctrl.signal,headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'data='+encodeURIComponent(q)});
      clearTimeout(tid);
      if(r.ok){ const t=await r.text(); try{ return JSON.parse(t); }catch(e){} }
    }catch(e){}
    await new Promise(res=>setTimeout(res, 1000+i*500));
  }
  return null;
}
async function waterRoute(p1,p2){
  const pad=Math.max(0.05, Math.abs(p1.lat-p2.lat)*0.4, Math.abs(p1.lng-p2.lng)*0.4);  // 멀수록 넓게(굽이 포함)
  const s=Math.min(p1.lat,p2.lat)-pad, w=Math.min(p1.lng,p2.lng)-pad, n=Math.max(p1.lat,p2.lat)+pad, e=Math.max(p1.lng,p2.lng)+pad;
  const q='[out:json][timeout:60];(way["waterway"~"river|stream|canal"]('+s+','+w+','+n+','+e+'););out geom;';
  const j=await overpassFetch(q);
  if(!j) return {err:'overpass'};
  const nodes={}, adj={}, toR=Math.PI/180;
  function key(la,ln){ const k=la.toFixed(4)+','+ln.toFixed(4); if(!(k in nodes)) nodes[k]=[la,ln]; return k; }  // 11m 병합(합류부 연결)
  function hav(a,b){ const R=6371000, dla=(b[0]-a[0])*toR, dlo=(b[1]-a[1])*toR, la1=a[0]*toR, la2=b[0]*toR;
    const h=Math.sin(dla/2)*Math.sin(dla/2)+Math.cos(la1)*Math.cos(la2)*Math.sin(dlo/2)*Math.sin(dlo/2); return 2*R*Math.asin(Math.sqrt(h)); }
  for(const el of (j.elements||[])){ if(el.type!=='way'||!el.geometry) continue; let prev=null;
    for(const p of el.geometry){ const k=key(p.lat,p.lon); if(prev&&prev!==k){ const d=hav(nodes[prev],nodes[k]);
      (adj[prev]=adj[prev]||[]).push([k,d]); (adj[k]=adj[k]||[]).push([prev,d]); } prev=k; } }
  function nearest(pt){ let best=null,bd=1e18; for(const k in nodes){ const d=hav(nodes[k],[pt.lat,pt.lng]); if(d<bd){bd=d;best=k;} } return best; }
  // 물길을 못 찾는 경우엔 항상 두 점을 직선으로 연결(거리=직선)
  const straight=function(){ return {coords:[[p1.lat,p1.lng],[p2.lat,p2.lng]], km: hav([p1.lat,p1.lng],[p2.lat,p2.lng])/1000, straight:true}; };
  const s1=nearest(p1), s2=nearest(p2); if(!s1||!s2) return straight();
  // 두 점이 강에서 멀면(호수/열린수면) 강 중심선 추적 대신 직선으로
  const od1=hav([p1.lat,p1.lng],nodes[s1]), od2=hav([p2.lat,p2.lng],nodes[s2]);
  if(od1>150 || od2>150) return straight();
  const dist={}, prev={}; dist[s1]=0; const heap=new MinHeap(); heap.push(0,s1);
  while(heap.size()){ const top=heap.pop(); const d=top[0], u=top[1]; if(u===s2) break; if(d>(dist[u]===undefined?1e18:dist[u])) continue;
    for(const vw of (adj[u]||[])){ const v=vw[0], nd=d+vw[1]; if(nd<(dist[v]===undefined?1e18:dist[v])){ dist[v]=nd; prev[v]=u; heap.push(nd,v); } } }
  if(dist[s2]===undefined) return straight();
  const path=[s2]; while(path[path.length-1]!==s1){ const pp=prev[path[path.length-1]]; if(pp===undefined) return straight(); path.push(pp); } path.reverse();
  // 클릭한 실제 점까지 연결 + 그 거리 포함(점-to-점)
  const d1=hav([p1.lat,p1.lng],nodes[s1]), d2=hav([p2.lat,p2.lng],nodes[s2]);
  const coords=[[p1.lat,p1.lng]].concat(path.map(k=>nodes[k])).concat([[p2.lat,p2.lng]]);
  return {coords, km:(dist[s2]+d1+d2)/1000};
}
function MinHeap(){ this.a=[]; }
MinHeap.prototype.size=function(){ return this.a.length; };
MinHeap.prototype.push=function(p,v){ const a=this.a; a.push([p,v]); let i=a.length-1;
  while(i>0){ const par=(i-1)>>1; if(a[par][0]<=a[i][0]) break; const t=a[par]; a[par]=a[i]; a[i]=t; i=par; } };
MinHeap.prototype.pop=function(){ const a=this.a, top=a[0], last=a.pop();
  if(a.length){ a[0]=last; let i=0; const n=a.length;
    while(true){ let l=2*i+1, r=2*i+2, m=i; if(l<n&&a[l][0]<a[m][0])m=l; if(r<n&&a[r][0]<a[m][0])m=r; if(m===i)break; const t=a[m]; a[m]=a[i]; a[i]=t; i=m; } }
  return top; };

// ---- 내 위치 ----
let _locMarker=null, _locCircle=null;
const LocateCtl=L.Control.extend({ options:{position:'bottomleft'},
  onAdd:function(){ const d=L.DomUtil.create('div','locbtn'); d.id='locBtn'; d.title='내 위치'; d.innerHTML='📍';
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    L.DomEvent.on(d,'click',function(e){ L.DomEvent.preventDefault(e); locateMe(); });
    return d; }
});
map.addControl(new LocateCtl());
function locateMe(){
  if(!navigator.geolocation){ L.popup().setLatLng(map.getCenter()).setContent('이 브라우저는 위치를 지원하지 않습니다').openOn(map); return; }
  const b=document.getElementById('locBtn'); if(b) b.classList.add('loading');
  map.locate({setView:true, maxZoom:16, enableHighAccuracy:true, timeout:10000});
}
map.on('locationfound', function(e){
  const b=document.getElementById('locBtn'); if(b) b.classList.remove('loading');
  if(_locMarker) map.removeLayer(_locMarker); if(_locCircle) map.removeLayer(_locCircle);
  _locCircle=L.circle(e.latlng,{radius:Math.min(e.accuracy,2000),color:'#1976d2',weight:1,fillColor:'#42a5f5',fillOpacity:.15}).addTo(map);
  _locMarker=L.circleMarker(e.latlng,{radius:7,color:'#fff',weight:3,fillColor:'#1976d2',fillOpacity:1,className:'loc-dot'}).addTo(map).bindPopup('현재 위치').openPopup();
  gaEvent('locate');
});
map.on('locationerror', function(){
  const b=document.getElementById('locBtn'); if(b) b.classList.remove('loading');
  L.popup().setLatLng(map.getCenter()).setContent('위치를 가져올 수 없습니다.<br><small>브라우저 위치 권한을 허용해 주세요</small>').openOn(map);
});

// ---- 범례 ----
const legend = L.control({position:'bottomright'});
legend.onAdd=function(){ const d=L.DomUtil.create('div','legend');
  d.innerHTML='<b>범례</b>'+
    '<span class="sw" style="background:#ec407a"></span>카누명소<br>'+
    '<span class="sw" style="background:#2196f3"></span>카누 런칭/랜딩 장소<br>'+
    '<span class="sw" style="background:rgba(229,57,53,.4)"></span>상수원보호구역(진입금지)'+
    (COURSES.features.length?'<br><span class="sw" style="width:16px;height:4px;background:#00b894"></span>카누잉코스':'')+
    '<br><span class="sw" style="width:16px;height:4px;background:#ff7043"></span>거리측정(물길)';
  return d; };
legend.addTo(map);
</script>
</body>
</html>
"""

html = (HTML
        .replace("__POINTS__", json.dumps(points, ensure_ascii=False, separators=(",", ":")))
        .replace("__POLYS__", json.dumps(polygons, ensure_ascii=False, separators=(",", ":")))
        .replace("__COURSES__", json.dumps(courses, ensure_ascii=False, separators=(",", ":")))
        .replace("__VKEY__", VKEY)
        .replace("__GTAG__", GTAG)
        .replace("__WORKER__", WORKER_URL)
        .replace("__GA_ID__", GA_ID)
        .replace("__ADMIN__", ADMIN_ID))
out = BASE / "map.html"
out.write_text(html, encoding="utf-8")
print(f"생성: map.html ({out.stat().st_size/1024:.0f} KB) — VKEY {'포함(공개)' if VKEY else '없음'}")
