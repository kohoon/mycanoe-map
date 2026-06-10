#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카카오 로드뷰 존재 여부 사전계산 → roadview.json 생성(빌드 시 1회).

각 장소(synced_seqs.json) 좌표 근처(기본 60m)에 로드뷰 파노라마가 있는지
카카오 지도 JS SDK(RoadviewClient.getNearestPanoId)로 조회해 캐시한다.
결과는 런타임 키 없이 build_map.py가 임베드한다(완전 정적).

준비물:
  1) 카카오 JavaScript 키 — 개발자센터 → 내 앱 → 앱 키 → JavaScript 키
     (REST 키와 같은 앱. 환경변수 KAKAO_JS_KEY 또는 파일 kakao_js_key.txt)
  2) 카카오 콘솔 → 앱 → 플랫폼 → Web 에 빌드용 도메인 등록: http://localhost:8097
실행:
  python build_roadview.py            # 전체
  python build_roadview.py 80         # 반경 80m
출력: roadview.json  ->  {"<장소key>": {"rv": true/false, "pano": <id|null>}}
"""
import json, os, sys, threading, http.server, socketserver
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORT = 8097
RADIUS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def js_key():
    k = os.environ.get("KAKAO_JS_KEY", "").strip()
    if k:
        return k
    f = BASE / "kakao_js_key.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    sys.exit("[!] 카카오 JS 키가 없습니다. 환경변수 KAKAO_JS_KEY 또는 kakao_js_key.txt 준비 필요.")


def load_places():
    items = json.loads((BASE / "synced_seqs.json").read_text(encoding="utf-8")).get("items", {})
    out = []
    for key, v in items.items():
        if v.get("lat") is not None:
            out.append({"key": str(key), "name": v.get("name", ""), "lat": v["lat"], "lng": v["lng"]})
    return out


HTML = """<!doctype html><html><head><meta charset="utf-8">
<script src="//dapi.kakao.com/v2/maps/sdk.js?appkey=%KEY%&autoload=false"></script>
</head><body><div id="map" style="width:1px;height:1px"></div>
<script>
window.__ready=false;
kakao.maps.load(function(){ window.__rvc=new kakao.maps.RoadviewClient(); window.__ready=true; });
window.queryPanos=function(points, radius){
  return new Promise(function(resolve){
    var res={}, i=0;
    function next(){
      if(i>=points.length){ resolve(res); return; }
      var p=points[i++];
      var pos=new kakao.maps.LatLng(p.lat, p.lng);
      window.__rvc.getNearestPanoId(pos, radius, function(panoId){
        res[p.key]={rv: panoId!=null, pano: (panoId!=null?panoId:null)};
        setTimeout(next, 70);   // throttle
      });
    }
    next();
  });
};
</script></body></html>"""


def main():
    key = js_key()
    places = load_places()
    print(f"장소 {len(places)}곳 / 반경 {RADIUS}m / 포트 {PORT}", flush=True)
    (BASE / "_rv_probe.html").write_text(HTML.replace("%KEY%", key), encoding="utf-8")

    os.chdir(BASE)
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
            pg.goto(f"http://localhost:{PORT}/_rv_probe.html", wait_until="load", timeout=30000)
            pg.wait_for_function("() => window.__ready === true", timeout=20000)
            print("SDK 로드 완료, 조회 시작…", flush=True)
            res = pg.evaluate("(args) => window.queryPanos(args.pts, args.r)",
                              {"pts": places, "r": RADIUS})
            if errs:
                print("[!] 페이지 오류:", errs[:3])
            b.close()
    finally:
        httpd.shutdown()
        try:
            (BASE / "_rv_probe.html").unlink()
        except Exception:
            pass

    have = sum(1 for v in res.values() if v.get("rv"))
    (BASE / "roadview.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"[done] 로드뷰 있음 {have} / {len(res)} -> roadview.json", flush=True)


if __name__ == "__main__":
    main()
