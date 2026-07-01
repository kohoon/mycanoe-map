#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 자동: 카카오 즐겨찾기 수집 → (신규 시) 빌드+커밋+푸시 → 시트 보고.

GitHub Actions schedule(.github/workflows/daily-collect.yml)이 이 스크립트를 실행.
카카오 세션(auth_state.json)이 살아있으면 헤드리스로 무인 수집,
만료되면 "재로그인 필요"로 보고(그때만 collect_kakao.py 수동 1회).

설정 파일(모두 gitignore, 로컬에만):
  - auth_state.json         : 카카오 로그인 세션(collect_kakao.py 가 생성/갱신, CI에서는 GitHub Secret에서 복원)
  - admin_key.txt           : 시트 보고용 워커 ADMIN_KEY(로컬 gitignore, CI에서는 GitHub Secret에서 복원)
"""
import json, subprocess, sys, urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
TOOLS = Path(__file__).resolve().parent
PY = sys.executable
FOLDERS = "20842531"                 # 카카오 폴더 ID(쉼표로 여러개). 마이카누=20842531
WORKER = "https://mycanoe-map.kohoon0140.workers.dev"
LOG = BASE / "collect_log.txt"
ADMINFILE = BASE / "admin_key.txt"   # 시트 보고용(워커 /report 인증). gitignore.

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run(cmd, timeout=600):
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def sheet_report(status, added, detail):
    """수집 결과를 구글 시트(collect 탭)로 보고 → 워커 /report."""
    if not ADMINFILE.exists():
        return "시트보고 생략(admin_key.txt 없음)"
    key = ADMINFILE.read_text(encoding="utf-8").strip()
    body = json.dumps({"adminKey": key, "status": status, "added": added, "detail": detail}).encode("utf-8")
    try:
        req = urllib.request.Request(WORKER + "/report", data=body,
                                     headers={"Content-Type": "application/json", "Origin": "https://kohoon.github.io",
                                              "User-Agent": "Mozilla/5.0 (GitHub Actions) mycanoe-daily"})
        urllib.request.urlopen(req, timeout=20).read()
        return "시트 기록됨"
    except Exception as e:
        return f"시트 보고 실패: {str(e)[:120]}"


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"[{now}] 마이카누 일일 수집"]

    # 1) 수집(헤드리스)
    rc, out = run([PY, str(TOOLS / "collect_kakao.py"), "--folderid", FOLDERS, "--headless"])
    new = 0
    for ln in out.splitlines():
        if "신규" in ln and "추가" in ln:
            import re; m = re.search(r"신규\s*(\d+)", ln)
            if m: new = int(m.group(1))
    names = [ln.strip()[2:] for ln in out.splitlines() if ln.strip().startswith("+ ")]

    if rc == 2:   # 세션 만료
        lines.append("⚠️ 카카오 세션 만료 — 재로그인 필요")
        lines.append("  맥북에서:  python tools/collect_kakao.py --folderid " + FOLDERS)
        status = "재로그인 필요"
    elif rc != 0:
        lines.append("❌ 수집 오류"); lines.append(out[-600:]); status = "수집 오류"
    elif new == 0:
        lines.append("신규 장소 없음 (변동 없음)"); status = "변동 없음"
    else:
        lines.append(f"✅ 신규 {new}곳 수집")
        for nm in names[:30]: lines.append("  + " + nm)
        # 2) 빌드
        run([PY, str(TOOLS / "build_map.py")]); run([PY, str(TOOLS / "build_map.py"), "test"])
        # 3) 변경 있으면 커밋+푸시
        _, st = run(["git", "status", "--porcelain"])
        if st.strip():
            run(["git", "add", "data/synced_seqs.json", "data/place_ids.json", "map.html", "index.html", "test.html",
                 "wlz.geojson", "protect_polygons.geojson"])
            run(["git", "commit", "-m", f"카카오 즐겨찾기 신규 {new}곳 자동 수집 ({now})"])
            prc, pout = run(["git", "push"])
            lines.append("📤 푸시 완료" if prc == 0 else "❌ 푸시 실패:\n" + pout[-400:])
            status = f"신규 {new}곳 반영"
        else:
            lines.append("(빌드 결과 변경 없음 — 푸시 생략)"); status = f"신규 {new}곳(푸시생략)"

    body = "\n".join(lines)
    rep = sheet_report(status, new, body.replace("\n", " / "))
    body += "\n" + rep
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(body + "\n" + ("-" * 40) + "\n")
    print(body)


if __name__ == "__main__":
    main()
