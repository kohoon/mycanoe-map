#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""카카오맵 즐겨찾기 → synced_seqs.json 수집(네이버 동기화 없음).

기존 kakao_naver_sync.py 의 검증된 수집 JS(KAKAO_FETCH_JS)를 재사용해
카카오 폴더의 즐겨찾기를 가져와 synced_seqs.json 에 신규만 추가한다.
※ 카카오 로그인이 필요하므로 **headful**(창 표시)로 실행 — 사용자 PC 터미널에서.

사용:
  # 폴더 1개
  python collect_kakao.py --folderid 20842531
  # 폴더 여러개(쉼표)
  python collect_kakao.py --folderid 20842531,12345678
  # 세션 만료 시 창에서 카카오 로그인 후 엔터 → 자동 수집

이후:
  python build_map.py && python build_map.py test
  git add synced_seqs.json place_ids.json map.html index.html test.html && git commit && git push
"""
import argparse, json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = Path(__file__).resolve().parent
try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

KAKAO_MAIN = "https://map.kakao.com/"
AUTH = BASE / "auth_state.json"
SEQS = BASE / "synced_seqs.json"

# 검증된 수집 JS 재사용
_src = (BASE / "kakao_naver_sync.py").read_text(encoding="utf-8")
KAKAO_FETCH_JS = re.search(r'KAKAO_FETCH_JS = r"""(.*?)"""', _src, re.S).group(1)


def fetch_folder(page, folderid):
    page.goto(KAKAO_MAIN, wait_until="domcontentloaded")
    try: page.wait_for_function("typeof kakao !== 'undefined' && !!kakao.maps", timeout=15000)
    except PWTimeout: pass
    res = page.evaluate(KAKAO_FETCH_JS, folderid)
    if isinstance(res, dict) and res.get("error"):
        if "NOT_LOGIN" in res["error"] or "로그인" in res["error"]:
            return None  # 로그인 필요 신호
        print("[error]", res["error"]); return []
    return res.get("items", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folderid", required=True, help="카카오 폴더 ID(쉼표로 여러개)")
    ap.add_argument("--headless", action="store_true", help="(세션 유효 시만) 창 없이")
    args = ap.parse_args()
    folders = [f.strip() for f in args.folderid.split(",") if f.strip()]

    data = json.loads(SEQS.read_text(encoding="utf-8")) if SEQS.exists() else {"version": 1, "items": {}}
    items = data.setdefault("items", {})
    before = len(items)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=args.headless)
        ctx = b.new_context(storage_state=str(AUTH)) if AUTH.exists() else b.new_context()
        page = ctx.new_page()

        # 첫 폴더로 로그인 상태 확인
        probe = fetch_folder(page, folders[0])
        if probe is None:
            if args.headless:
                print("[!] 세션 만료 — --headless 없이 다시 실행해 로그인하세요."); sys.exit(2)
            print("\n[로그인 필요] 열린 창에서 카카오 로그인을 완료한 뒤, 이 터미널에서 Enter…")
            try: input()
            except EOFError: pass
            ctx.storage_state(path=str(AUTH))   # 갱신된 세션 저장
            probe = fetch_folder(page, folders[0])
            if probe is None:
                print("[!] 여전히 로그인 안 됨 — 종료"); sys.exit(2)

        all_items = []
        for fid in folders:
            got = fetch_folder(page, fid) or []
            print(f"[kakao] 폴더 {fid}: {len(got)}개")
            all_items += got
        ctx.storage_state(path=str(AUTH))
        b.close()

    added, skipped = 0, 0
    for it in all_items:
        seq = str(it.get("seq") or "")
        if not seq or it.get("lat") is None:
            skipped += 1; continue
        if seq in items:
            continue
        items[seq] = {"name": it.get("name", ""), "memo": it.get("memo", ""),
                      "lat": it["lat"], "lng": it["lng"], "naver": "skipped"}
        added += 1
        print(f"  + {it.get('name','')}")

    SEQS.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"\n[done] 신규 {added}개 추가 (좌표없음 {skipped} 제외) / 총 {before}→{len(items)}곳")
    if added:
        print("다음: python build_map.py && python build_map.py test  →  git commit/push")


if __name__ == "__main__":
    main()
