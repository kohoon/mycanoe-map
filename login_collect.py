#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""헤드풀(영속 프로필) → 카카오 로그인 자동 감지(페이지 비간섭) → 수집 → synced_seqs.json 병합.
영속 프로필(_kakao_profile)에 로그인 저장 → 창이 닫혀도 유지, 다음에도 재로그인 불필요."""
import json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
FOLDERS = (sys.argv[1] if len(sys.argv) > 1 else "20842531").split(",")
PROFILE = BASE / "_kakao_profile"
AUTH = BASE / "auth_state.json"; SEQS = BASE / "synced_seqs.json"
JS = re.search(r'KAKAO_FETCH_JS = r"""(.*?)"""', (BASE/"kakao_naver_sync.py").read_text(encoding="utf-8"), re.S).group(1)

# 로그인 상태 체크용 경량 JS(페이지 이동 없이 fetch만)
CHECK_JS = r"""
async (fid) => {
  try {
    const res = await fetch('https://map.kakao.com/favorite/mine/list?folderid='+fid, {credentials:'include', headers:{'Accept':'application/json'}});
    const t = await res.text();
    return { loggedIn: t.indexOf('NOT_LOGIN') < 0 && t.length > 25 };
  } catch (e) { return { loggedIn: false, err: String(e) }; }
}
"""

def sdk_fetch(page, fid):
    page.goto("https://map.kakao.com/", wait_until="domcontentloaded")
    try: page.wait_for_function("typeof kakao!=='undefined' && !!kakao.maps", timeout=12000)
    except Exception: pass
    r = page.evaluate(JS, fid)
    if isinstance(r, dict) and r.get("error"): return []
    return r.get("items", [])

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, viewport={"width":1100,"height":820})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try: page.goto("https://map.kakao.com/", wait_until="domcontentloaded", timeout=30000)
    except Exception: pass
    print("[열림] 카카오맵 창 — 우측 상단 '로그인'으로 카카오 로그인 해주세요.", flush=True)
    print("       (로그인 후 창은 그대로 두세요 — 자동 감지·수집 후 알아서 닫힙니다)", flush=True)

    ok = False
    for i in range(150):   # 150 * 4s = 10분
        try:
            r = page.evaluate(CHECK_JS, FOLDERS[0])
            if r and r.get("loggedIn"): ok = True; break
        except Exception:
            # 로그인 중 다른 출처(accounts.kakao.com)면 evaluate 실패 → 컨텍스트 request로 폴백
            try:
                rr = ctx.request.get("https://map.kakao.com/favorite/mine/list?folderid="+FOLDERS[0],
                                     headers={"Referer":"https://map.kakao.com/","Accept":"application/json"}, timeout=8000)
                tt = rr.text()
                if "NOT_LOGIN" not in tt and len(tt) > 25: ok = True; break
            except Exception: pass
        if i % 8 == 0: print(f"  …감지 대기 {i*4}s", flush=True)
        time.sleep(4)

    if not ok:
        print("[!] 10분 내 로그인 미감지 — 종료(다시 실행 가능, 프로필은 유지됨)", flush=True); ctx.close(); sys.exit(2)
    print("[로그인 감지됨] 수집 시작…", flush=True)
    try: ctx.storage_state(path=str(AUTH))   # 일일 스크립트용 세션도 저장
    except Exception: pass
    allit = []
    for fid in FOLDERS:
        got = sdk_fetch(page, fid) or []
        print(f"[kakao] 폴더 {fid}: {len(got)}개", flush=True); allit += got
    ctx.close()

data = json.loads(SEQS.read_text(encoding="utf-8")); items = data.setdefault("items", {})
before = len(items); added = 0; names = []
for it in allit:
    seq = str(it.get("seq") or "")
    if not seq or it.get("lat") is None or seq in items: continue
    items[seq] = {"name": it.get("name",""), "memo": it.get("memo",""), "lat": it["lat"], "lng": it["lng"], "naver": "skipped"}
    added += 1; names.append(it.get("name","")); print("  + " + it.get("name",""), flush=True)
SEQS.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
print(f"[done] 신규 {added}곳 / 총 {before}->{len(items)}곳", flush=True)
