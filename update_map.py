#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""원커맨드 지도 업데이트.
카카오 즐겨찾기(마스터) → synced_seqs.json 갱신(네이버 동기화 상태는 보존) → map.html 재생성 → git push.
카카오 앱에서 런칭/랜딩 지점을 추가/수정/삭제한 뒤 이 스크립트만 돌리면 공개 지도가 갱신됩니다.

사용: update.bat            (folderid 기본 20842531)
      update.bat 12345      (다른 폴더)
"""
import shutil, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kakao_naver_sync as kns  # noqa

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PY = sys.executable
FOLDERID = sys.argv[1] if len(sys.argv) > 1 else "20842531"


def fetch_kakao():
    state = kns.load_state()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        kw = {"locale": "ko-KR"}
        if kns.AUTH_STATE.exists():
            kw["storage_state"] = str(kns.AUTH_STATE)
        ctx = browser.new_context(**kw)
        page = ctx.new_page()
        page.set_default_timeout(20000)
        items = kns.fetch_kakao_favorites(page, FOLDERID)
        if not items:
            print("\n[!] 카카오 로그인이 필요합니다. 열린 창에서 로그인 후 Enter.")
            for _ in range(8):
                try:
                    input("    로그인 완료했으면 Enter: ")
                except EOFError:
                    break
                items = kns.fetch_kakao_favorites(page, FOLDERID)
                if items:
                    break
        ctx.storage_state(path=str(kns.AUTH_STATE))
        browser.close()
    return state, items


def main():
    state, items = fetch_kakao()
    if not items:
        print("[!] 즐겨찾기를 못 읽었습니다. 중단."); return

    # synced_seqs.json 갱신: 현재 카카오 기준, 기존 naver 상태는 보존
    cur = {it["seq"]: it for it in items}
    new_state = {}
    added, removed = 0, 0
    for seq, it in cur.items():
        old = state.get(seq)
        new_state[seq] = {"name": it["name"], "memo": it.get("memo", ""),
                          "lat": it["lat"], "lng": it["lng"],
                          "naver": (old or {}).get("naver", "new")}
        if not old:
            added += 1
    removed = sum(1 for seq in state if seq not in cur)
    kns.save_state(new_state)
    print(f"[state] synced_seqs.json 갱신: 총 {len(new_state)} (신규 {added} / 삭제 {removed})")

    # 지도 재생성
    print("[map] map.html 재생성…")
    subprocess.run([PY, str(BASE / "build_map.py")], check=True)
    shutil.copyfile(BASE / "map.html", BASE / "index.html")

    # git push
    print("[git] 커밋·푸시…")
    subprocess.run(["git", "add", "-A"], cwd=str(BASE))
    r = subprocess.run(["git", "commit", "-m", "update: 카카오 즐겨찾기 반영"], cwd=str(BASE))
    if r.returncode != 0:
        print("[git] 변경 없음(커밋 생략)")
    push = subprocess.run(["git", "push"], cwd=str(BASE))
    if push.returncode == 0:
        print("\n[done] 완료! 1~2분 후 https://kohoon.github.io/mycanoe-map/ 갱신됩니다.")
    else:
        print("\n[!] git push 실패 — 수동으로 'git push' 해보세요.")


if __name__ == "__main__":
    main()
