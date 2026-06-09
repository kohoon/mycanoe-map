#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kakao_add_favorites.py

protect_zones.json 의 상수원보호구역 점들을 카카오맵 즐겨찾기 폴더에 추가.
- 카카오 비공개 엔드포인트 favorite/add 사용 (저장된 세션 auth_state.json 재사용)
- WGS84 -> WCONGNAMUL 좌표는 페이지의 kakao.maps.Coords 수치역산으로 변환
- 항목마다 진행상황 kakao_add_state.json 에 기록(중단 후 재개 가능)

먼저 카카오맵에서 폴더('상수원보호구역')를 만들고 folderid 를 확인하세요.
  - 폴더를 열면 주소창에 folderid=XXXX 가 보입니다. 또는: python kakao_add_favorites.py --list-folders

검증 실행(1건만):
  python kakao_add_favorites.py --folderid XXXX --limit 1
전체:
  python kakao_add_favorites.py --folderid XXXX
카누 근처만:
  python kakao_add_favorites.py --folderid XXXX --near-only
"""
import argparse, json, math, sys, time, random
from pathlib import Path
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
AUTH = BASE / "auth_state.json"
ZONES = BASE / "protect_zones.json"
STATE = BASE / "kakao_add_state.json"
SYNCED = BASE / "synced_seqs.json"

# 페이지에서 좌표변환 + favorite/add 를 수행하는 JS
ADD_JS = r"""
async ({folderid, name, lat, lng, color}) => {
  // SDK 대기
  for (let i=0;i<60 && !(window.kakao&&kakao.maps&&kakao.maps.Coords);i++){await new Promise(r=>setTimeout(r,500));}
  if(!(window.kakao&&kakao.maps&&kakao.maps.Coords)) return {ok:false, err:"no Coords"};
  // WGS84 -> WCONGNAMUL (kakao.maps.Coords.toLatLng 역산, 뉴턴법)
  const f=(xx,yy)=>{const ll=new kakao.maps.Coords(xx,yy).toLatLng();return [ll.getLng(),ll.getLat()];};
  let x=500000,y=1000000;
  for(let it=0; it<15; it++){
    const [lng0,lat0]=f(x,y); const d=1.0;
    const [lngx,latx]=f(x+d,y); const [lngy,laty]=f(x,y+d);
    const a=(lngx-lng0)/d,b=(lngy-lng0)/d,c=(latx-lat0)/d,e=(laty-lat0)/d;
    const det=a*e-b*c; if(Math.abs(det)<1e-20) break;
    const elng=lng-lng0, elat=lat-lat0;
    const dx=(e*elng-b*elat)/det, dy=(-c*elng+a*elat)/det;
    x+=dx; y+=dy; if(Math.abs(dx)<1e-4&&Math.abs(dy)<1e-4) break;
  }
  x=Math.round(x); y=Math.round(y);
  const item={folderid:parseInt(folderid), type:"POINT", display1:name, display2:"",
              memo:"", x:x, y:y, key:x+"|"+y, color:color||"03", home:false};
  const body={datas:[item]};   // 카카오 addFavorite 는 datas 배열 래퍼를 요구
  let status=0, text="";
  try{
    const r=await fetch("/favorite/add",{method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json","X-Requested-With":"XMLHttpRequest"},
      body:JSON.stringify(body)});
    status=r.status; text=(await r.text()).slice(0,400);
  }catch(err){ return {ok:false, err:String(err), wcong:[x,y]}; }
  return {ok:true, status, text, wcong:[x,y], sent:body};
}
"""

LIST_FOLDERS_JS = r"""
async () => {
  try{
    const r=await fetch("/folder/list",{credentials:"include",headers:{"X-Requested-With":"XMLHttpRequest"}});
    if(r.status!==200) return {err:"status "+r.status};
    const j=await r.json();
    const fs=(j.folders||j.result||[]).map(f=>({folderid:f.folderid,title:f.title,cnt:f.favorite_cnt}));
    return {folders:fs};
  }catch(e){ return {err:String(e)}; }
}
"""

CREATE_FOLDER_JS = r"""
async ({title}) => {
  const body={title:title, memo:"", out_link:"", icon:"06", status:"P"};
  try{
    const r=await fetch("/folder/add",{method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json","X-Requested-With":"XMLHttpRequest"},
      body:JSON.stringify(body)});
    const t=await r.text();
    let fid=null; try{ fid=(JSON.parse(t).req||{}).folderid; }catch(e){}
    return {status:r.status, folderid:fid, text:t.slice(0,300)};
  }catch(e){ return {err:String(e)}; }
}
"""


def flatten_points(zones, near_only, near_km):
    canoe = []
    if near_only and SYNCED.exists():
        items = json.loads(SYNCED.read_text(encoding="utf-8")).get("items", {})
        canoe = [(v["lng"], v["lat"]) for v in items.values() if v.get("lat")]

    def near(lat, lng):
        if not near_only:
            return True
        if not canoe:
            return True
        for cx, cy in canoe:
            if math.hypot((lng - cx) * math.cos(math.radians(lat)) * 111, (lat - cy) * 111) <= near_km:
                return True
        return False

    pts = []
    for z in zones:
        for p in z["points"]:
            nm = z["name"] + (f" ({p['label']})" if p.get("label") else "")
            if near(p["lat"], p["lng"]):
                pts.append({"id": f"{z['name']}|{p.get('label','')}",
                            "name": nm, "lat": p["lat"], "lng": p["lng"]})
    return pts


def load_done():
    if STATE.exists():
        return set(json.loads(STATE.read_text(encoding="utf-8")))
    return set()


def save_done(done):
    STATE.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folderid", help="대상 카카오 폴더 ID(숫자). 미지정시 --folder-name 사용")
    ap.add_argument("--folder-name", default="상수원보호구역", help="대상 폴더명(자동 인식)")
    ap.add_argument("--create-folder", action="store_true", help="폴더 없으면 생성")
    ap.add_argument("--near-only", action="store_true", help="카누 즐겨찾기 근처만")
    ap.add_argument("--near-km", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=0, help="이번에 추가할 최대 개수(0=전부)")
    ap.add_argument("--color", default="03")
    ap.add_argument("--list-folders", action="store_true", help="내 폴더 목록 조회")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    if not AUTH.exists():
        print("[!] auth_state.json 없음. 먼저 sync.bat 으로 카카오 로그인 세션을 만드세요.")
        return

    with sync_playwright() as p:
        b = p.chromium.launch(headless=args.headless)
        ctx = b.new_context(storage_state=str(AUTH), locale="ko-KR")
        pg = ctx.new_page()
        pg.goto("https://map.kakao.com/", wait_until="domcontentloaded")
        pg.wait_for_timeout(2000)

        if args.list_folders:
            res = pg.evaluate(LIST_FOLDERS_JS)
            for f in res.get("folders", []):
                print(f"  folderid={f['folderid']:>10}  ({f.get('cnt',0):>4})  {f['title']}")
            if "err" in res:
                print("  err:", res["err"])
            b.close(); return

        # folderid 결정: --folderid 우선, 없으면 --folder-name 으로 자동 인식/생성
        folderid = args.folderid
        if not folderid:
            res = pg.evaluate(LIST_FOLDERS_JS)
            folders = res.get("folders", [])
            match = [f for f in folders if f["title"] == args.folder_name]
            if match:
                folderid = str(match[0]["folderid"])
                print(f"[folder] '{args.folder_name}' 인식 → folderid={folderid}")
            elif args.create_folder:
                cr = pg.evaluate(CREATE_FOLDER_JS, {"title": args.folder_name})
                if cr.get("folderid"):
                    folderid = str(cr["folderid"])
                    print(f"[folder] 생성/확인됨 → folderid={folderid}")
                else:
                    print(f"[!] 폴더 생성 실패: {cr}"); b.close(); return
            else:
                print(f"[!] '{args.folder_name}' 폴더 없음. 카카오에서 만들거나 --create-folder 사용.")
                print("    현재 폴더 목록:")
                for f in folders:
                    print(f"      {f['folderid']}  {f['title']}")
                b.close(); return

        zones = json.loads(ZONES.read_text(encoding="utf-8"))
        pts = flatten_points(zones, args.near_only, args.near_km)
        done = load_done()
        todo = [p for p in pts if p["id"] not in done]
        if args.limit > 0:
            todo = todo[: args.limit]
        print(f"[add] 대상 {len(pts)} / 완료 {len(done)} / 이번 처리 {len(todo)}")

        ok = fail = 0
        for i, pt in enumerate(todo, 1):
            try:
                res = pg.evaluate(ADD_JS, {"folderid": folderid, "name": pt["name"],
                                           "lat": pt["lat"], "lng": pt["lng"], "color": args.color})
            except Exception as e:
                # 페이지가 죽었을 수 있음 → 재로드 후 1회 재시도
                print(f"[{i}/{len(todo)}] {pt['name']} → evaluate 예외, 페이지 재로드: {str(e)[:80]}")
                try:
                    pg.goto("https://map.kakao.com/", wait_until="domcontentloaded")
                    pg.wait_for_timeout(2500)
                    res = pg.evaluate(ADD_JS, {"folderid": folderid, "name": pt["name"],
                                               "lat": pt["lat"], "lng": pt["lng"], "color": args.color})
                except Exception as e2:
                    print(f"    재시도 실패: {str(e2)[:80]} — 다음 항목으로")
                    fail += 1
                    time.sleep(random.uniform(2, 4))
                    continue
            success = res.get("ok") and res.get("status") == 200 and \
                ("error" not in (res.get("text") or "").lower() or "ALREADY" in (res.get("text") or ""))
            if success:
                done.add(pt["id"]); save_done(done); ok += 1
                print(f"[{i}/{len(todo)}] {pt['name']} → OK (status {res.get('status')})")
            else:
                fail += 1
                print(f"[{i}/{len(todo)}] {pt['name']} → 실패: status={res.get('status')} "
                      f"err={res.get('err')} body={res.get('text')}")
                if i == 1:
                    print("  [!] 첫 항목 실패 → 본문 형식 확인 필요.")
                    print("  [debug] 보낸 body:", json.dumps(res.get('sent'), ensure_ascii=False))
                    break
            if i < len(todo):
                time.sleep(random.uniform(1.5, 3.0))
                if i % 20 == 0:
                    t = random.uniform(20, 30)
                    print(f"    …{i}개 처리, {t:.0f}s 휴식"); time.sleep(t)
                # 주기적 페이지 재로드(장시간 실행 안정화)
                if i % 80 == 0:
                    try:
                        pg.goto("https://map.kakao.com/", wait_until="domcontentloaded")
                        pg.wait_for_timeout(2000)
                    except Exception:
                        pass

        print(f"\n[done] 성공 {ok} / 실패 {fail} / 누적완료 {len(done)}")
        b.close()


if __name__ == "__main__":
    main()
