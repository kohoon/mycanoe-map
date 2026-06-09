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
<title>마이카누 지도 — 카누 명소·코스·물길 거리측정</title>
<meta property="og:type" content="website">
<meta property="og:url" content="https://kohoon.github.io/mycanoe-map/">
<meta property="og:title" content="마이카누 지도">
<meta property="og:description" content="전국 카누 명소·런칭/랜딩·카누잉 코스·물길 거리측정. 카누 타는 곳을 한눈에.">
<meta property="og:image" content="https://kohoon.github.io/mycanoe-map/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="마이카누 지도">
<meta name="twitter:description" content="전국 카누 명소·코스·물길 거리측정">
<meta name="twitter:image" content="https://kohoon.github.io/mycanoe-map/og.png">
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
  .locbtn{cursor:pointer;background:#fff;width:40px;height:40px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);user-select:none;display:flex;align-items:center;justify-content:center}
  .locbtn.loading{opacity:.45}
  .loc-dot{filter:drop-shadow(0 0 3px rgba(25,118,210,.6))}
  .addplace-btn{margin-top:7px;background:#00b894;color:#fff;border:0;border-radius:6px;padding:6px 11px;font:600 12px sans-serif;cursor:pointer}
  .addplace-btn.sugg{background:#1565c0}
  .addform #apName{width:100%;box-sizing:border-box;padding:6px;margin:6px 0;border:1px solid #bbb;border-radius:4px;font-size:13px}
  .addform .aprow{font:12px sans-serif;margin-bottom:8px;display:flex;flex-direction:column;gap:3px}
  .addform #apSave{background:#00b894;color:#fff;border:0;border-radius:5px;padding:6px 13px;font:600 13px sans-serif;cursor:pointer}
  .addform #apMsg{font-size:12px;color:#666;margin-left:6px}
  .canoe-pin-in{width:26px;height:26px;border-radius:50%;background:#2196f3;border:1.5px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center}
  .canoe-pin-in svg{width:17px;height:auto}
  .cafecard{display:flex;align-items:center;gap:8px;width:150px;box-sizing:border-box;background:#fff;padding:7px 12px 7px 7px;border-radius:12px;box-shadow:0 3px 12px rgba(0,0,0,.2);text-decoration:none;cursor:pointer}
  .cafecard .cf-badge{width:30px;height:30px;flex:none;border-radius:8px;background:#03C75A;display:flex;align-items:center;justify-content:center}
  .cafecard .cf-badge svg{width:20px;height:auto}
  .cafecard .cf-t{font:800 13px sans-serif;color:#1f2d25;white-space:nowrap}
  .legend-c{width:150px;box-sizing:border-box}
  .spot-pin-in{width:30px;height:30px;border-radius:50%;background:#ec407a;border:1.5px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center}
  .spot-pin-in svg{width:19px;height:auto}
  .wreck-in{width:34px;height:34px;border-radius:50%;background:#c62828;border:2px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;overflow:hidden}
  .wreck-in svg{width:30px;height:30px}
  .dotpin{border-radius:50%;border:1.5px solid #fff;box-sizing:border-box;box-shadow:0 0 3px rgba(0,0,0,.5)}
  .dot-canoe{background:#2196f3}
  .dot-spot{background:#ec407a}
  .dot-wreck{background:#c62828}
  .locbtn svg{width:22px;height:22px;display:block;margin:auto}
  .pmodal-wrap{position:fixed;inset:0;z-index:3500;display:none;align-items:flex-end;justify-content:center}
  .pmodal-wrap.open{display:flex}
  .pmodal-bg{position:absolute;inset:0;background:rgba(0,0,0,.45)}
  .pmodal{position:relative;background:#fff;width:100%;max-width:460px;max-height:82vh;overflow:auto;border-radius:16px 16px 0 0;padding:20px 18px 24px;box-shadow:0 -6px 30px rgba(0,0,0,.25);animation:pmUp .25s ease}
  @keyframes pmUp{from{transform:translateY(30px);opacity:.6}to{transform:none;opacity:1}}
  @media(min-width:520px){.pmodal-wrap{align-items:center}.pmodal{border-radius:16px}}
  .pmodal-x{position:absolute;top:12px;right:12px;border:0;background:#eee;border-radius:50%;width:30px;height:30px;font-size:15px;cursor:pointer}
  .pmodal h3{margin:0 30px 8px 0;font-size:18px;color:#1b3a2b}
  #pmLinks{font-size:13px;margin-bottom:10px}
  .pm-memo{color:#556;font-size:13px;margin-top:6px}
  .pm-adminbox{background:#e8f7f1;border-left:3px solid #00b894;border-radius:6px;padding:8px 10px;margin:8px 0;font-size:13px;white-space:pre-wrap;word-break:break-word}
  .pm-admedit{background:#00b894;color:#fff;border:0;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;margin:4px 0 8px}
  .pm-cmts-h{font-weight:700;font-size:14px;border-top:1px solid #eee;padding-top:12px;margin-top:8px}
  .pm-cmts{margin:8px 0}
  .pm-cmt{padding:7px 0;border-bottom:1px solid #f0f0f0}
  .pm-cmt-h b{font-size:12.5px;color:#1565c0}
  .pm-cmt-b{font-size:13.5px;color:#222;margin-top:2px;word-break:break-word}
  .pm-empty{color:#999;font-size:13px;padding:10px 0}
  .pm-form{display:flex;gap:6px;margin-top:8px}
  .pm-form input{flex:1;min-width:0;padding:9px;border:1px solid #ccc;border-radius:8px;font-size:14px}
  .pm-form button{background:#1565c0;color:#fff;border:0;border-radius:8px;padding:9px 14px;font-weight:700;cursor:pointer}
  #pmMsg{font-size:12px;color:#888;margin-top:6px;min-height:14px}
  #sgBody h3{margin:0 30px 8px 0;font-size:18px;color:#1b3a2b}
  .sg-addr{font-size:13px;color:#445;background:#f3f7f4;border-radius:9px;padding:9px 12px;margin:4px 0 14px;word-break:break-all}
  .sg-label{font-size:12.5px;color:#778;font-weight:700;margin-bottom:6px}
  .seg{display:flex;gap:8px;margin-bottom:14px}
  .seg-b{flex:1;padding:12px;border:1.5px solid #d6dee2;background:#fff;border-radius:11px;font:600 14px sans-serif;cursor:pointer;color:#456}
  .seg-b.on{border-color:#1565c0;background:#e8f1fc;color:#0d47a1}
  #sgText{width:100%;box-sizing:border-box;padding:11px;border:1px solid #ccd;border-radius:11px;font-size:14px;resize:vertical;font-family:inherit}
  .sg-submit{width:100%;margin-top:13px;background:#1565c0;color:#fff;border:0;border-radius:11px;padding:14px;font:700 15px sans-serif;cursor:pointer}
  .sg-submit:active{transform:translateY(1px)}
  #sgMsg{font-size:13px;color:#1b8a5a;margin-top:9px;min-height:18px;text-align:center}
  /* TRIPCSS */
  #tripbar{position:absolute;left:50%;transform:translateX(-50%);bottom:18px;z-index:1200;display:flex;gap:8px}
  .tb-start{background:#ff3d00;color:#fff;border:0;border-radius:24px;padding:13px 20px;font:800 15px sans-serif;box-shadow:0 4px 14px rgba(255,61,0,.45);cursor:pointer;white-space:nowrap}
  #tripbar.rec .tb-start{background:#d32f2f;animation:recpulse 1.4s ease-in-out infinite}
  @keyframes recpulse{0%,100%{box-shadow:0 4px 14px rgba(211,47,47,.5)}50%{box-shadow:0 4px 22px rgba(211,47,47,.9)}}
  .tb-log{background:#fff;color:#1b3a2b;border:0;border-radius:24px;padding:13px 16px;font:700 14px sans-serif;box-shadow:0 3px 12px rgba(0,0,0,.25);cursor:pointer}
  .tm-tabs{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
  .tm-tab{background:#eef2f0;border:0;border-radius:14px;padding:6px 11px;font:600 12.5px sans-serif;cursor:pointer}
  .tm-tab.on{background:#1565c0;color:#fff}
  .tm-item{padding:9px 0;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;gap:8px}
  .tm-item .ti-main{cursor:pointer;flex:1;min-width:0}
  .tm-item .ti-t{font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tm-item .ti-s{font-size:12px;color:#777}
  .tm-btn{background:#eef2f0;border:0;border-radius:7px;padding:5px 9px;font-size:12px;cursor:pointer;white-space:nowrap}
  .tm-btn.on{background:#03C75A;color:#fff}
  .tm-btn.del{color:#c62828}
  .tm-stat{display:flex;gap:10px;margin:12px 0}
  .tm-stat>div{background:#f3f7f4;border-radius:10px;padding:11px 8px;text-align:center;flex:1}
  .tm-stat b{display:block;font-size:19px;color:#1b3a2b}
  .tm-stat span{font-size:11px;color:#778}
  .tm-row{display:flex;gap:6px;margin-top:10px}
  .tm-row input{flex:1;min-width:0;padding:9px;border:1px solid #ccc;border-radius:8px;font-size:14px}
  .tm-save{background:#1565c0;color:#fff;border:0;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer}
  .tm-toggle{display:flex;align-items:center;gap:7px;font-size:13px;margin:10px 0;color:#334}
  .tm-rank{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f0f0f0}
  .tm-rank .rk{width:22px;text-align:center;font-weight:800;color:#1565c0}
  .tm-empty{color:#999;font-size:13px;padding:14px 0;text-align:center}
  /* /TRIPCSS */
  .authbox{font:600 13px sans-serif}
  .authbox button{background:#FEE500;color:#191600;border:0;border-radius:6px;padding:8px 12px;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.3)}
  .authbox .who{display:inline-block;background:#fff;border-radius:6px;padding:7px 10px;box-shadow:0 1px 4px rgba(0,0,0,.3);max-width:46vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .authbox .who a{color:#1565c0;margin-left:8px;text-decoration:none;cursor:pointer}
  .authbox .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#2ecc71;margin-right:6px;vertical-align:middle}
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
  .beta-tag{display:inline-block;background:#ff7043;color:#fff;font:700 10px sans-serif;padding:2px 7px;border-radius:8px;vertical-align:middle;margin-left:7px}
  #welcomeBanner{position:absolute;top:62px;left:50%;transform:translateX(-50%);z-index:1500;display:none;align-items:center;gap:10px;max-width:min(90vw,400px);background:rgba(18,40,54,.93);color:#fff;padding:10px 15px;border-radius:18px;box-shadow:0 5px 18px rgba(0,0,0,.32);font:600 13px/1.45 'Malgun Gothic',sans-serif;backdrop-filter:blur(5px);transition:opacity .4s}
  #welcomeBanner.show{display:flex}
  #wbText{flex:1}
  #wbText b{color:#7fe3c0}
  #wbX{cursor:pointer;color:#9fd8ff;flex:none;font-size:14px;text-decoration:none}
  @media(max-width:520px){ #welcomeBanner{font-size:12px;top:58px;padding:9px 13px} }
  .gate-warn{display:flex;gap:8px;text-align:left;background:#fff8e1;border:1px solid #ffe082;border-left:4px solid #ffb300;border-radius:9px;padding:9px 11px;margin:0 0 16px;font:12px/1.5 sans-serif;color:#6d4c00}
  .gate-warn span:first-child{flex:none}
  .admin-badge{position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:3100;display:flex;align-items:center;gap:9px;background:#263238;color:#fff;padding:8px 14px;border-radius:22px;font:700 13px sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.3)}
  .admin-badge .ab-dot{width:8px;height:8px;border-radius:50%;background:#69f0ae;box-shadow:0 0 6px #69f0ae}
  .admin-badge a{color:#80d8ff;text-decoration:none;cursor:pointer;margin-left:4px}
  @media(max-width:520px){
    .measbtn{padding:8px 11px;font-size:12px}
    .search input{max-width:150px;font-size:12px}
    .search button{padding:5px 8px;font-size:12px}
    .leaflet-popup-content{font-size:12px;line-height:1.5}
    .authbox button{padding:7px 11px;font-size:12.5px}
    .authbox .who{font-size:12.5px;padding:6px 9px}
    .cafecard{width:138px;padding:6px 10px 6px 6px}
    .cafecard .cf-badge{width:27px;height:27px}
    .cafecard .cf-t{font-size:12px}
    .legend-c{width:138px;font-size:12px}
    .pmodal{padding:16px 14px 20px}
  }
</style>
</head>
<body>
<div id="map"></div>
<div id="hint"></div>
<div id="welcomeBanner"><span id="wbText"></span><a id="wbX">✕</a></div>
<div id="gate">
  <div class="gate-card">
    <div class="gate-logo"><svg class="canoe-ico" viewBox="0 0 64 40" aria-hidden="true">
      <path d="M2 20C2 13 16 10 32 10C48 10 62 13 62 20C62 27 48 30 32 30C16 30 2 27 2 20Z" fill="#fff"/>
      <path d="M9.5 20C9.5 15.7 19.5 13.8 32 13.8C44.5 13.8 54.5 15.7 54.5 20C54.5 24.3 44.5 26.2 32 26.2C19.5 26.2 9.5 24.3 9.5 20Z" fill="#dfeefb"/>
      <path d="M23 15.2V24.8M41 15.2V24.8" stroke="#bcd6ea" stroke-width="1.5" stroke-linecap="round"/>
    </svg></div>
    <h1>마이카누 지도<span class="beta-tag">BETA</span></h1>
    <p class="gate-sub">전국 카누 명소를 한눈에</p>
    <ul class="gate-feats">
      <li><span>💧</span><span>상수원보호구역 안내</span></li>
      <li><span>📍</span><span>카누 런칭·랜딩 장소</span></li>
      <li><span>🛶</span><span>카누잉 추천 코스</span></li>
      <li><span>📏</span><span>물길 거리 측정</span></li>
    </ul>
    <div class="gate-warn"><span>⚠️</span><span>베타 서비스입니다. 접속·속도가 불안정할 수 있고, 남긴 코멘트가 사라질 수 있어요.</span></div>
    <button id="gateLogin" class="kakao-btn"><svg class="kakao-ico" viewBox="0 0 24 24"><path d="M12 3.4C6.7 3.4 2.4 6.9 2.4 11.1c0 2.7 1.8 5.1 4.5 6.5-.2.7-.7 2.5-.8 2.9-.1.5.2.5.4.4.2-.1 2.5-1.7 3.5-2.4.5.1 1 .2 1.5.2 5.3 0 9.6-3.4 9.6-7.6S17.3 3.4 12 3.4z"/></svg>카카오로 시작하기</button>
    <small>로그인 후 바로 이용할 수 있어요</small>
  </div>
</div>
<div id="pmodal" class="pmodal-wrap">
  <div class="pmodal-bg" onclick="closePlaceModal()"></div>
  <div class="pmodal">
    <button class="pmodal-x" onclick="closePlaceModal()">✕</button>
    <h3 id="pmTitle"></h3>
    <div id="pmLinks"></div>
    <div id="pmAdmin"></div>
    <div class="pm-cmts-h">코멘트 <span id="pmCnt"></span></div>
    <div id="pmCmts" class="pm-cmts"></div>
    <div class="pm-form"><input id="pmInput" maxlength="100" placeholder="한줄 코멘트 (최대 100자)"><button id="pmSend">등록</button></div>
    <div id="pmMsg"></div>
  </div>
</div>
<div id="sgmodal" class="pmodal-wrap">
  <div class="pmodal-bg" onclick="closeSg()"></div>
  <div class="pmodal"><button class="pmodal-x" onclick="closeSg()">✕</button><div id="sgBody"></div></div>
</div>
<!-- TRIPHTML -->
<div id="tripbar"><button id="tripStart" class="tb-start">▶ 카누잉 시작</button><button id="tripLog" class="tb-log">📋 기록</button></div>
<div id="tmodal" class="pmodal-wrap">
  <div class="pmodal-bg" onclick="closeTModal()"></div>
  <div class="pmodal"><button class="pmodal-x" onclick="closeTModal()">✕</button><div id="tmBody"></div></div>
</div>
<!-- /TRIPHTML -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const POINTS = __POINTS__;
const POLYS = __POLYS__;
const COURSES = __COURSES__;
const VKEY = "__VKEY__";   // V-World 키(도메인잠금). 브라우저가 직접 호출. 비면 Nominatim
const WORKER_URL = "__WORKER__";  // 카카오 로그인 OAuth Worker
const GA_ID = "__GA_ID__";        // GA4 측정 ID(비면 추적 off)
// 관리자 백도어(키 인증). 키는 공개 코드에 없음 — 서버(Cloudflare Secret)가 검증
let _adminOk=false;
function adminKey(){ try{ return localStorage.getItem('mc_admin')||''; }catch(e){ return ''; } }
function isAdmin(){ return _adminOk; }
async function _adminVerify(k){ try{ const r=await fetch(WORKER_URL.replace(/\/+$/,'')+'/admincheck',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k})}); const d=await r.json(); return !!(d&&d.ok); }catch(e){ return false; } }
function _adminBadge(on){ let el=document.getElementById('adminBadge');
  if(on){ if(!el){ el=document.createElement('div'); el.id='adminBadge'; el.className='admin-badge';
    el.innerHTML='<span class="ab-dot"></span>🔧 관리자 모드 <a id="adminOff">해제</a>'; document.body.appendChild(el);
    document.getElementById('adminOff').onclick=function(){ try{localStorage.removeItem('mc_admin');}catch(e){} _adminOk=false; _adminBadge(false); }; } }
  else if(el){ el.remove(); } }
function _setAdmin(on){ _adminOk=on; _adminBadge(on); }
function openAdminAuth(){ const k=prompt('관리자 키를 입력하세요'); if(k===null||!k) return;
  _adminVerify(k).then(function(ok){ if(ok){ try{localStorage.setItem('mc_admin',k);}catch(e){} _setAdmin(true); alert('🔧 관리자 모드 ON'); } else alert('관리자 키가 올바르지 않습니다'); }); }
function _maybeAdmin(){ if(/admin/.test(location.hash||'')){ try{history.replaceState(null,'',location.pathname+location.search);}catch(e){} openAdminAuth(); } }
window.addEventListener('hashchange', _maybeAdmin);   // 새로고침 없이 #admin 붙여도 동작
(function(){
  if(/admin/.test(location.hash||'')){ try{history.replaceState(null,'',location.pathname+location.search);}catch(e){} setTimeout(openAdminAuth, 600); }
  const k=adminKey(); if(k) _adminVerify(k).then(function(ok){ _setAdmin(ok); if(!ok){ try{localStorage.removeItem('mc_admin');}catch(e){} } });
})();

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
// ---- 환영 배너: 공유 안내 + 카누잉 한마디(랜덤 순환) ----
const WB_CTA='🛶 <b>나만 아는 카누잉 장소</b>를 지도에 우클릭(모바일 더블탭)해 공유해주세요!';
const WB_QUOTES=['"강은 서두르지 않아도 언젠가 바다에 닿는다."','"노를 젓는 만큼 물길이 열린다."','"급할수록, 강물처럼 흘러라."','"물결을 거스르지 말고, 물결을 읽어라."','"카누는 자연으로 들어가는 가장 조용한 문이다."','"한 번의 패들이 하루를 바꾼다."','"고요한 수면 아래 가장 깊은 평온이 있다."','"오늘 젓지 않으면 그 물길은 영원히 모른다."','"바람은 방향을, 노는 의지를 정한다."','"젖는 걸 두려워하면 강을 건널 수 없다."'];
function showWelcome(){
  try{ if(sessionStorage.getItem('mc_wb')) return; }catch(e){}
  const el=document.getElementById('welcomeBanner'), tx=document.getElementById('wbText'); if(!el||!tx) return;
  const q=WB_QUOTES.slice().sort(function(){return Math.random()-0.5;});
  const msgs=[WB_CTA].concat(q); let i=0;
  tx.innerHTML=msgs[0]; el.classList.add('show');
  const tid=setInterval(function(){ i=(i+1)%msgs.length; tx.innerHTML=msgs[i]; }, 6000);
  function closeWB(){ el.classList.remove('show'); clearInterval(tid); }
  const x=document.getElementById('wbX'); if(x) x.onclick=function(){ closeWB(); try{sessionStorage.setItem('mc_wb','1');}catch(e){} };
  setTimeout(closeWB, 32000);
}
(function(){
  const gb=document.getElementById('gateLogin');
  if(gb) gb.onclick=function(){ gaEvent('login_start'); location.href=WORKER_URL; };
  const u=getUser(); if(u&&u.uid){ hideGate(); setTimeout(showWelcome, 900); } else showGate();
})();
function renderAuth(){
  const d=document.getElementById('authbox'); if(!d) return;
  const u=getUser();
  if(u&&u.uid){
    d.innerHTML='<span class="who"><span class="dot"></span>로그인됨 <a id="logoutA">로그아웃</a></span>';
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
const isTouch = ('ontouchstart' in window) || navigator.maxTouchPoints > 0;   // 모바일/터치 여부
L.control.zoom({position:'bottomleft'}).addTo(map);
map.addControl(new AuthCtl());   // 카카오 로그인 박스(우상단)
const CafeCtl=L.Control.extend({ options:{position:'bottomright'},
  onAdd:function(){ const d=L.DomUtil.create('a','cafecard'); d.href='https://cafe.naver.com/mytalon'; d.target='_blank'; d.rel='noopener';
    d.innerHTML='<span class="cf-badge">'+CANOE_SVG+'</span><span class="cf-t">마이카누 카페</span>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.on(d,'click',function(){ gaEvent('cafe_click'); });
    return d; } });

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
  else if(getUser()&&getUser().uid) h+='<br><button class="addplace-btn sugg" onclick="suggestPlace()">💡 장소 제안</button>';
  pop.setContent(h);
}
// ---- 어드민: 장소 등록 ----
// 일반 사용자: 장소 제안(런칭지/랜딩지/기타 + 코멘트) → 시트
function closeSg(){ document.getElementById('sgmodal').classList.remove('open'); }
function suggestPlace(){
  const a=window._curAddr; if(!a) return; const u=getUser(); if(!u||!u.uid) return;
  map.closePopup();
  document.getElementById('sgBody').innerHTML=
    '<h3>장소 제안</h3>'
    +'<div class="sg-addr">📍 '+pmEsc(a.name||'선택한 위치')+'</div>'
    +'<div class="sg-label">유형 선택</div>'
    +'<div class="seg" id="sgSeg"><button type="button" class="seg-b on" data-v="런칭/랜딩">🛶 런칭/랜딩</button><button type="button" class="seg-b" data-v="기타">📍 기타</button></div>'
    +'<textarea id="sgText" rows="3" maxlength="200" placeholder="설명/코멘트 (예: 진입로·주차 정보)"></textarea>'
    +'<button class="sg-submit" id="sgSave">제안 보내기</button><div id="sgMsg"></div>';
  document.getElementById('sgmodal').classList.add('open');
  const seg=document.getElementById('sgSeg');
  seg.onclick=function(e){ const t=e.target.closest('.seg-b'); if(!t) return;
    Array.prototype.forEach.call(seg.children,function(c){c.classList.remove('on');}); t.classList.add('on'); };
  document.getElementById('sgSave').onclick=async function(){
    const on=seg.querySelector('.seg-b.on'); const cat=on?on.getAttribute('data-v'):'런칭/랜딩';
    const text=(document.getElementById('sgText').value||'').trim().slice(0,200);
    const msg=document.getElementById('sgMsg'); msg.textContent='보내는 중…';
    try{ const r=await fetch(WORKER_URL.replace(/\/+$/,'')+'/suggest',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:u.uid,nick:u.nick||'',cat:cat,text:text,addr:a.name||'',lat:a.lat,lng:a.lng})});
      if(r.ok){ msg.textContent='✅ 감사합니다! 제안이 접수됐어요'; gaEvent('place_suggest',{cat:cat}); setTimeout(closeSg,1100); }
      else msg.textContent='전송 실패'; }
    catch(e){ msg.textContent='오류'; } };
}
// 등록장소는 별도 레이어 없이 카테고리(명소/런칭·랜딩) 레이어에 합쳐 표시
function addPlaceMarker(pl){ const k=(pl.cat==='명소')?'spot':'canoe';
  const m=makeMarker([pl.lat,pl.lng],k);
  m.on('click',function(){ openPlaceModal(pl); });
  m.addTo(k==='spot'?famousLayer:canoeLayer); }
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
          body:JSON.stringify({id:u.uid,adminKey:adminKey(),nick:u.nick||'',name:nm,cat:cat,lat:a.lat,lng:a.lng})});
        if(r.ok){ msg.textContent='완료!'; addPlaceMarker({name:nm,cat:cat,lat:a.lat,lng:a.lng}); gaEvent('place_add',{cat:cat}); setTimeout(function(){map.closePopup();},700); }
        else { msg.textContent=(r.status===403?'권한 없음':'실패'); }
      }catch(e){ msg.textContent='오류'; }
    };
  },0);
}
map.on('contextmenu', e=>showAddress(e.latlng.lat, e.latlng.lng));   // 데스크톱 우클릭

// ---- 모바일: 더블탭 → 우클릭과 동일하게 주소 표시 (롱프레스는 기본기능과 충돌) ----
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
const EMERALD = '#7c4dff';   // 카누잉코스 색(선명한 바이올렛 — 일반/위성 모두 잘 보임)
function courseSubcat(name){ const m=(name||'').match(/^([^#0-9]+)/); return (m?m[1]:'코스').trim()||'코스'; }
const _courseGroups={};   // 서브카테고리 -> features
COURSES.features.forEach(function(f){ const sc=courseSubcat((f.properties||{}).name);
  (_courseGroups[sc]=_courseGroups[sc]||[]).push(f); });
const courseLayers={};    // 서브카테고리 -> layerGroup
Object.keys(_courseGroups).forEach(function(sc){
  const fc={type:'FeatureCollection',features:_courseGroups[sc]};
  const casing=L.geoJSON(fc,{style:{color:'#2a0a4a',weight:8,opacity:0.55},interactive:false});
  const line=L.geoJSON(fc,{style:{color:EMERALD,weight:5,opacity:0.95},interactive:false});
  // 투명 넓은 탭 영역(어디를 탭/클릭해도 정보)
  const hit=L.geoJSON(fc,{style:{color:'#000',weight:22,opacity:0},
    onEachFeature:(f,l)=>{ const p=f.properties||{};
      const html='<b>'+(p.name||'카누잉코스')+'</b>'+(p.km?'<br>약 '+p.km+'km':'');
      l.bindPopup(html); if(!isTouch) l.bindTooltip(html,{sticky:true,direction:'top',opacity:0.95}); }
  });
  courseLayers[sc]=L.layerGroup([casing,line,hit]).addTo(map);
});

// ---- 장소 상세 모달 + 코멘트 ----
function placeSlug(lat,lng){ return lat.toFixed(5)+'_'+lng.toFixed(5); }
function pmEsc(s){ return (s||'').replace(/[<>&]/g,function(c){return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];}); }
function featPlace(f){ const p=f.properties||{},c=f.geometry.coordinates; return {name:p.name||'',lat:c[1],lng:c[0],memo:p.memo||'',cat:isSpot(p.name)?'명소':'런칭랜딩'}; }
let _pmPlace=null,_pmSlug=null;
function openPlaceModal(pl){
  _pmPlace=pl; _pmSlug=placeSlug(pl.lat,pl.lng);
  document.getElementById('pmTitle').textContent=pl.name||'장소';
  document.getElementById('pmLinks').innerHTML=extLinks(pl.lat,pl.lng,pl.name||'위치')+(pl.memo?'<div class="pm-memo">'+pmEsc(pl.memo)+'</div>':'');
  document.getElementById('pmAdmin').innerHTML='';
  document.getElementById('pmCmts').innerHTML='<div class="pm-empty">불러오는 중…</div>';
  document.getElementById('pmCnt').textContent=''; document.getElementById('pmInput').value=''; document.getElementById('pmMsg').textContent='';
  document.getElementById('pmodal').classList.add('open');
  gaEvent('place_open',{name:pl.name||''}); loadComments();
}
function closePlaceModal(){ document.getElementById('pmodal').classList.remove('open'); }
async function loadComments(){ if(!WORKER_URL||!_pmSlug) return;
  try{ const r=await fetch(WORKER_URL.replace(/\/+$/,'')+'/comments?place='+encodeURIComponent(_pmSlug)); renderComments(await r.json()); }
  catch(e){ renderComments({}); document.getElementById('pmCmts').innerHTML='<div class="pm-empty">코멘트를 불러오지 못했어요(잠시 후 다시)</div>'; } }
function renderComments(d){ d=d||{}; let ah='';
  if(d.admin) ah+='<div class="pm-adminbox"><b>📌 관리자</b><div>'+pmEsc(d.admin)+'</div></div>';
  if(isAdmin()) ah+='<button class="pm-admedit" onclick="editAdminComment()">관리자 코멘트 '+(d.admin?'수정':'작성')+'</button>';
  document.getElementById('pmAdmin').innerHTML=ah; window._pmAdminCur=d.admin||'';
  const list=d.list||[]; document.getElementById('pmCnt').textContent='('+list.length+')';
  document.getElementById('pmCmts').innerHTML = list.length? list.slice().reverse().map(function(c){
    return '<div class="pm-cmt"><div class="pm-cmt-h"><b>'+pmEsc(c.nick||'익명')+'</b></div><div class="pm-cmt-b">'+pmEsc(c.text)+'</div></div>';
  }).join('') : '<div class="pm-empty">첫 코멘트를 남겨보세요</div>';
}
async function submitComment(){ const u=getUser(); if(!u||!u.uid) return;
  const inp=document.getElementById('pmInput'); const t=(inp.value||'').trim().slice(0,100); if(!t) return;
  document.getElementById('pmMsg').textContent='등록 중…';
  try{ const r=await fetch(WORKER_URL.replace(/\/+$/,'')+'/comments',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({place:_pmSlug,name:(_pmPlace||{}).name||'',id:u.uid,nick:u.nick||'',text:t})});
    if(r.ok){ inp.value=''; document.getElementById('pmMsg').textContent=''; gaEvent('comment_add'); loadComments(); }
    else document.getElementById('pmMsg').textContent='등록 실패'; }
  catch(e){ document.getElementById('pmMsg').textContent='오류'; } }
function editAdminComment(){ if(!isAdmin()) return; const u=getUser();
  const t=prompt('관리자 코멘트 (이 장소 설명)', window._pmAdminCur||''); if(t===null) return;
  fetch(WORKER_URL.replace(/\/+$/,'')+'/comments',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({place:_pmSlug,name:(_pmPlace||{}).name||'',id:u.uid,adminKey:adminKey(),nick:u.nick||'',admin:true,text:t.slice(0,300)})})
    .then(function(r){ if(r.ok) loadComments(); }).catch(function(){}); }
(function(){ const s=document.getElementById('pmSend'); if(s) s.onclick=submitComment;
  const i=document.getElementById('pmInput'); if(i) i.addEventListener('keydown',function(e){ if(e.key==='Enter') submitComment(); }); })();

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
const WRECK_SVG='<svg viewBox="0 0 48 48"><path d="M0 27q6-4 12 0t12 0 12 0 12 0V48H0Z" fill="#4aa3e0"/><circle cx="11" cy="19" r="3.7" fill="#ffd2a6"/><path d="M7.5 23 L4 18 M14.5 23 L18 18" stroke="#ffd2a6" stroke-width="2.6" stroke-linecap="round"/><g transform="rotate(-20 30 27)"><path d="M16 25Q31 17 44 25Q41 31 30 32Q19 31 16 25Z" fill="#fff"/><path d="M20 25Q31 20 40 25" fill="none" stroke="#bcd6ea" stroke-width="1.4"/></g><path d="M0 31q6-4 12 0t12 0 12 0 12 0V48H0Z" fill="#2f80c9"/></svg>';
function wreckIcon(){ return L.divIcon({className:'wreck-pin',html:'<span class="wreck-in">'+WRECK_SVG+'</span>',iconSize:[34,34],iconAnchor:[17,17]}); }
function isWreck(nm){ return (nm||'').replace(/\s/g,'').indexOf('번버리')>=0; }
const BOATHOUSE_SVG='<svg viewBox="0 0 32 28"><path d="M16 2L30 13H27V26H5V13H2Z" fill="#fff"/><path d="M11 26V18.5a5 5 0 0 1 10 0V26Z" fill="#c2185b"/></svg>';
function boathouseIcon(){ return L.divIcon({className:'spot-pin',html:'<span class="spot-pin-in">'+BOATHOUSE_SVG+'</span>',iconSize:[30,30],iconAnchor:[15,15]}); }
// 줌아웃: 작은 점 / 줌인(>=Z_ICON): 아이콘
const Z_ICON=12;
function dotIcon(kind){ const c=kind==='spot'?'dot-spot':kind==='wreck'?'dot-wreck':'dot-canoe'; return L.divIcon({className:'dotpin '+c,html:'',iconSize:[10,10],iconAnchor:[5,5]}); }
function fullIcon(kind){ return kind==='spot'?boathouseIcon():kind==='wreck'?wreckIcon():canoeIcon(); }
function makeMarker(ll,kind){ const dot=map.getZoom()<Z_ICON; const m=L.marker(ll,{icon:dot?dotIcon(kind):fullIcon(kind)}); m._kind=kind; m._isDot=dot; return m; }
const famousLayer = L.geoJSON(spotFeats, {
  pointToLayer:(f,ll)=>makeMarker(ll,'spot'),
  onEachFeature:(f,l)=>l.on('click',function(){ openPlaceModal(featPlace(f)); })
}).addTo(map);
const canoeLayer = L.geoJSON(landFeats, {
  pointToLayer:(f,ll)=>makeMarker(ll, isWreck((f.properties||{}).name)?'wreck':'canoe'),
  onEachFeature:(f,l)=>l.on('click',function(){ openPlaceModal(featPlace(f)); })
}).addTo(map);
function applyZoomIcons(){ const dot=map.getZoom()<Z_ICON; const f=function(m){ if(!m._kind||m._isDot===dot) return; m._isDot=dot; m.setIcon(dot?dotIcon(m._kind):fullIcon(m._kind)); };
  famousLayer.eachLayer(f); canoeLayer.eachLayer(f); }
map.on('zoomend', applyZoomIcons);

// ---- 레이어 토글 ----
const _ov = {};
_ov['상수원보호'] = protectLayer;
Object.keys(courseLayers).forEach(function(sc){ _ov['코스 · '+sc+'('+_courseGroups[sc].length+')']=courseLayers[sc]; });
_ov['명소('+spotFeats.features.length+')'] = famousLayer;
_ov['런칭/랜딩('+landFeats.features.length+')'] = canoeLayer;
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
function overpassOne(url,q,ms){
  return new Promise(function(resolve){
    const ctrl=new AbortController(); const tid=setTimeout(function(){ctrl.abort();}, ms);
    fetch(url,{method:'POST',signal:ctrl.signal,headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'data='+encodeURIComponent(q)})
      .then(function(r){ clearTimeout(tid); if(!r.ok) return null; return r.text(); })
      .then(function(t){ if(t==null){ resolve(null); return; } try{ resolve(JSON.parse(t)); }catch(e){ resolve(null); } })
      .catch(function(){ clearTimeout(tid); resolve(null); });
  });
}
const _opCache={};   // 세션 캐시(같은 영역 재측정 즉시)
async function overpassFetch(q){
  if(_opCache[q]) return _opCache[q];
  // 미러 동시 요청 → 가장 먼저 응답하는 것 채택(속도)
  const mirrors=['https://overpass.kumi.systems/api/interpreter','https://overpass-api.de/api/interpreter','https://overpass.private.coffee/api/interpreter','https://overpass.osm.ch/api/interpreter'];
  for(let round=0; round<3; round++){
    const got=await new Promise(function(resolve){
      let pending=mirrors.length, settled=false;
      mirrors.forEach(function(m){ overpassOne(m,q,11000).then(function(j){
        if(settled) return; if(j){ settled=true; resolve(j); } else if(--pending===0) resolve(null); }); });
    });
    if(got){ _opCache[q]=got; return got; }
    await new Promise(function(res){ setTimeout(res,400); });
  }
  return null;
}
async function waterRoute(p1,p2){
  const pad=Math.max(0.02, Math.abs(p1.lat-p2.lat)*0.3, Math.abs(p1.lng-p2.lng)*0.3);  // 작게(빠름) + 멀면 적응 확대
  const r3=function(x){return Math.round(x*1000)/1000;};   // bbox 100m 라운딩(캐시 적중↑)
  const s=r3(Math.min(p1.lat,p2.lat)-pad), w=r3(Math.min(p1.lng,p2.lng)-pad), n=r3(Math.max(p1.lat,p2.lat)+pad), e=r3(Math.max(p1.lng,p2.lng)+pad);
  const q='[out:json][timeout:25];(way["waterway"~"river|stream|canal"]('+s+','+w+','+n+','+e+'););out geom;';
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
  // (호수에서도 강/수로 중심선을 따라 라우팅. 경로가 정말 없을 때만 직선 폴백)
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
  onAdd:function(){ const d=L.DomUtil.create('div','locbtn'); d.id='locBtn'; d.title='내 위치';
    d.innerHTML='<svg viewBox="0 0 24 24" fill="#1976d2"><path d="M12 8a4 4 0 100 8 4 4 0 000-8zm8.94 3A8.994 8.994 0 0013 3.06V1h-2v2.06A8.994 8.994 0 003.06 11H1v2h2.06A8.994 8.994 0 0011 20.94V23h2v-2.06A8.994 8.994 0 0020.94 13H23v-2h-2.06zM12 19a7 7 0 110-14 7 7 0 010 14z"/></svg>';
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
  _locMarker=L.circleMarker(e.latlng,{radius:7,color:'#fff',weight:3,fillColor:'#1976d2',fillOpacity:1,className:'loc-dot'}).addTo(map);
  gaEvent('locate');
});
map.on('locationerror', function(){
  const b=document.getElementById('locBtn'); if(b) b.classList.remove('loading');
  L.popup().setLatLng(map.getCenter()).setContent('위치를 가져올 수 없습니다.<br><small>브라우저 위치 권한을 허용해 주세요</small>').openOn(map);
});

/* TRIPJS */
// ====== 카누잉 트립 기록 ======
function wapi(p){ return WORKER_URL.replace(/\/+$/,'')+p; }
function toastMsg(m){ const h=document.getElementById('hint'); if(!h) return; h.textContent=m; h.style.opacity='1'; clearTimeout(window._htid); window._htid=setTimeout(function(){h.style.opacity='0';},3800); }
function fmtDur(s){ s=Math.floor(s); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), ss=s%60; return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(ss).padStart(2,'0'); }
function trkMeters(t){ let d=0; for(let i=1;i<t.length;i++) d+=map.distance([t[i-1][0],t[i-1][1]],[t[i][0],t[i][1]]); return d; }
function shortPlace(a){ if(!a) return ''; return a.trim().split(/\s+/).slice(-2).join(' '); }
let _trk=null, _viewLine=null, _pendTrip=null;
function tripBackup(){ try{ if(_trk) localStorage.setItem('mc_trk',JSON.stringify({track:_trk.track,startMs:_trk.startMs})); }catch(e){} }
function tripBackupClear(){ try{ localStorage.removeItem('mc_trk'); }catch(e){} }
async function startTrip(resume){
  if(_trk) return; const u=getUser(); if(!u||!u.uid){ toastMsg('로그인 후 이용하세요'); return; }
  if(!navigator.geolocation){ toastMsg('이 기기는 위치를 지원하지 않습니다'); return; }
  const track=(resume&&resume.track)||[];
  _trk={track:track, startMs:(resume&&resume.startMs)||Date.now(), watchId:null, wakeLock:null, timer:null,
    line:L.polyline(track.map(function(p){return [p[0],p[1]];}),{color:'#ff3d00',weight:5,opacity:.9}).addTo(map)};
  try{ if('wakeLock' in navigator) _trk.wakeLock=await navigator.wakeLock.request('screen'); }catch(e){}
  _trk.watchId=navigator.geolocation.watchPosition(onTripPos,function(){},{enableHighAccuracy:true,maximumAge:1000,timeout:15000});
  _trk.timer=setInterval(updateTripUI,1000);
  document.getElementById('tripbar').classList.add('rec'); document.getElementById('tripLog').style.display='none';
  updateTripUI(); gaEvent('trip_start'); if(!resume) toastMsg('🛶 기록 시작 — 화면을 켜두세요(꺼지면 기록이 멈춰요)');
}
function onTripPos(pos){ if(!_trk) return; const c=pos.coords; if(c.accuracy>50) return;
  const np=[+c.latitude.toFixed(6),+c.longitude.toFixed(6),Date.now()]; const t=_trk.track;
  if(t.length){ const last=t[t.length-1]; const d=map.distance([last[0],last[1]],[np[0],np[1]]); const dt=(np[2]-last[2])/1000;
    if(d<5) return; if(dt>0 && d/dt>15) return; }
  t.push(np); _trk.line.addLatLng([np[0],np[1]]); tripBackup(); }
function updateTripUI(){ if(!_trk) return; const sec=(Date.now()-_trk.startMs)/1000; const km=trkMeters(_trk.track)/1000;
  const el=document.getElementById('tripStart'); if(el) el.textContent='■ 종료 · '+fmtDur(sec)+' · '+km.toFixed(2)+'km'; }
async function stopTrip(){ if(!_trk) return; const t=_trk; _trk=null;
  try{ navigator.geolocation.clearWatch(t.watchId); }catch(e){} clearInterval(t.timer);
  try{ if(t.wakeLock) t.wakeLock.release(); }catch(e){}
  document.getElementById('tripbar').classList.remove('rec'); document.getElementById('tripLog').style.display='';
  document.getElementById('tripStart').textContent='▶ 카누잉 시작';
  if(t.track.length<2){ map.removeLayer(t.line); tripBackupClear(); toastMsg('기록된 위치가 부족해 저장 안 함'); return; }
  await openTripSummary(t.track, t.startMs, t.line); }
function tripStartStop(){ if(_trk) stopTrip(); else startTrip(); }
async function openTripSummary(track, startMs, line){
  const a=track[0], b=track[track.length-1]; const km=trkMeters(track)/1000; const sec=(track[track.length-1][2]-startMs)/1000;
  try{ map.fitBounds(line.getBounds().pad(0.25)); }catch(e){}
  document.getElementById('tmBody').innerHTML='<h3>카누잉 요약</h3><div class="tm-empty">주소 확인 중…</div>'; openTModalRaw();
  let la=null,lo=null; try{ la=await vworldReverse(a[0],a[1]); }catch(e){} try{ lo=await vworldReverse(b[0],b[1]); }catch(e){}
  const launchAddr=(la&&(la.parcel||la.road))||''; const landAddr=(lo&&(lo.parcel||lo.road))||'';
  const title=(shortPlace(launchAddr)||'런칭')+' → '+(shortPlace(landAddr)||'랜딩');
  _pendTrip={track:track,startMs:startMs,endMs:track[track.length-1][2],durSec:Math.round(sec),km:km,
    launch:{lat:a[0],lng:a[1],addr:launchAddr},landing:{lat:b[0],lng:b[1],addr:landAddr},line:line};
  document.getElementById('tmBody').innerHTML='<h3>카누잉 요약</h3>'
    +'<div class="tm-stat"><div><b>'+km.toFixed(2)+'</b><span>km</span></div><div><b>'+fmtDur(sec)+'</b><span>시간</span></div></div>'
    +'<div style="font-size:13px;color:#445"><b>런칭</b> '+pmEsc(launchAddr||'-')+'<br><b>랜딩</b> '+pmEsc(landAddr||'-')+'</div>'
    +'<div class="tm-row"><input id="tmTitle" maxlength="40" value="'+title.replace(/["<>]/g,'')+'"></div>'
    +'<label class="tm-toggle"><input type="checkbox" id="tmShare"> 공유하기 (다른 사용자도 이 경로를 볼 수 있어요)</label>'
    +'<div class="tm-row"><button class="tm-save" id="tmSave">저장</button><button class="tm-btn" id="tmCancel">취소</button><span id="tmMsg" style="font-size:12px;color:#888;margin-left:6px"></span></div>';
  document.getElementById('tmSave').onclick=saveTrip;
  document.getElementById('tmCancel').onclick=function(){ if(_pendTrip&&_pendTrip.line) map.removeLayer(_pendTrip.line); tripBackupClear(); _pendTrip=null; closeTModal(); }; }
async function saveTrip(){ if(!_pendTrip) return; const u=getUser(); if(!u||!u.uid) return;
  const title=(document.getElementById('tmTitle').value||'카누잉').trim().slice(0,40); const shared=document.getElementById('tmShare').checked;
  document.getElementById('tmMsg').textContent='저장 중…';
  try{ const r=await fetch(wapi('/trip'),{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'save',id:u.uid,nick:u.nick||'',title:title,shared:shared,start:_pendTrip.startMs,end:_pendTrip.endMs,durSec:_pendTrip.durSec,track:_pendTrip.track,launch:_pendTrip.launch,landing:_pendTrip.landing})});
    if(r.ok){ gaEvent('trip_save',{km:Math.round(_pendTrip.km*10)/10,shared:shared}); tripBackupClear(); if(_pendTrip.line) map.removeLayer(_pendTrip.line); _pendTrip=null; openTModal('trips'); }
    else document.getElementById('tmMsg').textContent='저장 실패';
  }catch(e){ document.getElementById('tmMsg').textContent='오류'; } }
function openTModalRaw(){ document.getElementById('tmodal').classList.add('open'); }
function closeTModal(){ document.getElementById('tmodal').classList.remove('open'); }
function tabBar(active){ const tabs=[['trips','내 기록'],['feed','공유된 코스'],['board','랭킹'],['stats','내 통계']];
  return '<div class="tm-tabs">'+tabs.map(function(t){return '<button class="tm-tab'+(t[0]===active?' on':'')+'" onclick="openTModal(\''+t[0]+'\')">'+t[1]+'</button>';}).join('')+'</div>'; }
async function openTModal(tab){ tab=tab||'trips'; openTModalRaw(); const body=document.getElementById('tmBody'); body.innerHTML=tabBar(tab)+'<div class="tm-empty">불러오는 중…</div>';
  try{ if(tab==='trips') await renderTrips(); else if(tab==='feed') await renderFeed(); else if(tab==='board') await renderBoard(); else await renderStats(); }
  catch(e){ body.innerHTML=tabBar(tab)+'<div class="tm-empty">불러오지 못했어요</div>'; } }
function tripItem(x, mine){ const dt=x.start?new Date(x.start):null; const ds=dt?(dt.getMonth()+1)+'/'+dt.getDate():'';
  let h='<div class="tm-item"><div class="ti-main" onclick="viewTrip(\''+x.id+'\')"><div class="ti-t">'+pmEsc(x.title||'카누잉')+'</div><div class="ti-s">'+ds+' · '+(x.distKm||0).toFixed(2)+'km · '+fmtDur(x.durSec||0)+(x.nick?' · '+pmEsc(x.nick):'')+'</div></div>';
  if(mine){ h+='<button class="tm-btn tm-share'+(x.shared?' on':'')+'" onclick="toggleShare(\''+x.id+'\','+(x.shared?'true':'false')+')">'+(x.shared?'공유중':'공유')+'</button><button class="tm-btn del" onclick="deleteTrip(\''+x.id+'\')">삭제</button>'; }
  return h+'</div>'; }
async function renderTrips(){ const u=getUser(); const r=await fetch(wapi('/trips?uid='+encodeURIComponent(u.uid))); const list=await r.json();
  document.getElementById('tmBody').innerHTML=tabBar('trips')+(list.length?list.map(function(x){return tripItem(x,true);}).join(''):'<div class="tm-empty">아직 기록이 없어요. 하단 ▶ 카누잉 시작!</div>'); }
async function renderFeed(){ const r=await fetch(wapi('/feed')); const list=await r.json();
  document.getElementById('tmBody').innerHTML=tabBar('feed')+(list.length?list.map(function(x){return tripItem(x,false);}).join(''):'<div class="tm-empty">아직 공유된 코스가 없어요</div>'); }
async function renderBoard(){ const r=await fetch(wapi('/board')); const list=await r.json(); const u=getUser();
  document.getElementById('tmBody').innerHTML=tabBar('board')+(list.length?list.map(function(x,i){ return '<div class="tm-rank"><span class="rk">'+(i+1)+'</span><div style="flex:1"><b>'+pmEsc(x.nick||'익명')+'</b>'+(String(x.uid)===String(u.uid)?' (나)':'')+'</div><div>'+(x.totalKm||0).toFixed(1)+'km · '+(x.trips||0)+'회</div></div>'; }).join(''):'<div class="tm-empty">랭킹 데이터가 없어요</div>'); }
async function renderStats(){ const u=getUser(); const r=await fetch(wapi('/trips?uid='+encodeURIComponent(u.uid))); const list=await r.json();
  const n=list.length, km=list.reduce(function(s,x){return s+(x.distKm||0);},0), sec=list.reduce(function(s,x){return s+(x.durSec||0);},0);
  document.getElementById('tmBody').innerHTML=tabBar('stats')+'<div class="tm-stat"><div><b>'+n+'</b><span>회</span></div><div><b>'+km.toFixed(1)+'</b><span>총 km</span></div><div><b>'+(n?(km/n).toFixed(1):'0')+'</b><span>평균 km</span></div></div><div class="tm-empty">총 카누잉 시간 '+fmtDur(sec)+'</div>'; }
async function viewTrip(id){ const u=getUser(); closeTModal();
  try{ const r=await fetch(wapi('/trip?id='+encodeURIComponent(id)+'&viewer='+encodeURIComponent(u.uid))); if(!r.ok){ toastMsg('불러오지 못했어요'); return; }
    const trip=await r.json(); if(_viewLine) map.removeLayer(_viewLine);
    _viewLine=L.polyline(trip.track.map(function(p){return [p[0],p[1]];}),{color:'#ff3d00',weight:5,opacity:.9}).addTo(map);
    const a=trip.track[0], b=trip.track[trip.track.length-1];
    L.circleMarker([a[0],a[1]],{radius:7,color:'#fff',weight:2,fillColor:'#2e7d32',fillOpacity:1}).addTo(_viewLine).bindTooltip('런칭');
    L.circleMarker([b[0],b[1]],{radius:7,color:'#fff',weight:2,fillColor:'#c62828',fillOpacity:1}).addTo(_viewLine).bindTooltip('랜딩');
    map.fitBounds(_viewLine.getBounds().pad(0.2));
    L.popup().setLatLng([b[0],b[1]]).setContent('<b>'+pmEsc(trip.title||'카누잉')+'</b><br>'+(trip.distKm||0).toFixed(2)+'km · '+fmtDur(trip.durSec||0)).openOn(map);
    gaEvent('trip_view');
  }catch(e){ toastMsg('오류'); } }
async function toggleShare(id,cur){ const u=getUser();
  try{ const r=await fetch(wapi('/trip'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'share',id:u.uid,tripId:id,shared:!cur})}); if(r.ok){ gaEvent('trip_share'); renderTrips(); } }catch(e){} }
async function deleteTrip(id){ if(!confirm('이 기록을 삭제할까요?')) return; const u=getUser();
  try{ const r=await fetch(wapi('/trip'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',id:u.uid,adminKey:adminKey(),tripId:id})}); if(r.ok) renderTrips(); }catch(e){} }
(function(){ const s=document.getElementById('tripStart'); if(s) s.onclick=tripStartStop; const l=document.getElementById('tripLog'); if(l) l.onclick=function(){ openTModal('trips'); };
  const u=getUser(); if(!u||!u.uid) return; let bk=null; try{ bk=JSON.parse(localStorage.getItem('mc_trk')||'null'); }catch(e){}
  if(bk&&bk.track&&bk.track.length>1){ setTimeout(function(){
    if(confirm('이전에 종료하지 않은 카누잉 기록이 있어요. 이어서 기록할까요?\n(취소 = 그 기록을 요약/저장 화면으로)')) startTrip(bk);
    else openTripSummary(bk.track, bk.startMs, L.polyline(bk.track.map(function(p){return [p[0],p[1]];}),{color:'#ff3d00',weight:5,opacity:.9}).addTo(map));
  },1200); } })();
document.addEventListener('visibilitychange',function(){ if(_trk&&document.visibilityState==='visible'&&'wakeLock' in navigator){ navigator.wakeLock.request('screen').then(function(w){ _trk.wakeLock=w; }).catch(function(){}); } });
/* /TRIPJS */

// ---- 범례 ----
const legend = L.control({position:'bottomright'});
legend.onAdd=function(){ const d=L.DomUtil.create('div','legend legend-c');
  d.innerHTML='<b>범례</b>'+
    '<span class="sw" style="background:#ec407a"></span>명소<br>'+
    '<span class="sw" style="background:#2196f3"></span>런칭/랜딩<br>'+
    '<span class="sw" style="background:rgba(229,57,53,.4)"></span>상수원보호'+
    (COURSES.features.length?'<br><span class="sw" style="width:16px;height:4px;background:#7c4dff"></span>코스':'');
  return d; };
legend.addTo(map);
map.addControl(new CafeCtl());   // 카페 카드: 범례 위(우하단)에 표시
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
        .replace("__GA_ID__", GA_ID))

# 카누잉 기록(트립) 기능: 기본 빌드는 제외(운영), `python build_map.py test` 만 포함(테스트 페이지)
import re as _re, sys as _sys
_TEST = len(_sys.argv) > 1 and _sys.argv[1] == "test"

def _strip_trip(h):
    h = _re.sub(r"/\* TRIPCSS \*/.*?/\* /TRIPCSS \*/", "", h, flags=_re.S)
    h = _re.sub(r"<!-- TRIPHTML -->.*?<!-- /TRIPHTML -->", "", h, flags=_re.S)
    h = _re.sub(r"/\* TRIPJS \*/.*?/\* /TRIPJS \*/", "", h, flags=_re.S)
    return h

if _TEST:
    out = BASE / "test.html"               # 테스트 페이지: 트립 포함
    out.write_text(html, encoding="utf-8")
    print(f"생성: test.html ({out.stat().st_size/1024:.0f} KB) — 카누잉 기록 포함(테스트)")
else:
    prod = _strip_trip(html)               # 운영: 트립 제외
    (BASE / "map.html").write_text(prod, encoding="utf-8")
    (BASE / "index.html").write_text(prod, encoding="utf-8")
    print(f"생성: map.html + index.html ({len(prod)/1024:.0f} KB) — 카누잉 기록 제외(운영)")
