#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 자동: 카카오 즐겨찾기 수집 → (신규 시) 빌드+커밋+푸시 → 이메일 보고.

Windows 작업 스케줄러가 daily_collect.bat 을 호출 → 이 스크립트 실행.
카카오 세션(auth_state.json)이 살아있으면 헤드리스로 무인 수집,
만료되면 "재로그인 필요"로 보고(그때만 collect_kakao.py 수동 1회).

설정 파일(모두 gitignore, 로컬에만):
  - auth_state.json         : 카카오 로그인 세션(collect_kakao.py 가 생성/갱신)
  - gmail_app_password.txt  : Gmail 앱 비밀번호(16자) — 보고 메일 발신용. 없으면 메일 생략.
"""
import json, smtplib, ssl, subprocess, sys, time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable
FOLDERS = "20842531"                 # 카카오 폴더 ID(쉼표로 여러개). 마이카누=20842531
SENDER = "kohoon0140@gmail.com"      # 발신(Gmail)
TO = "crowd@kakao.com"               # 수신
LOG = BASE / "collect_log.txt"
PWFILE = BASE / "gmail_app_password.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run(cmd, timeout=600):
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def email_report(subject, body):
    if not PWFILE.exists():
        return "메일 생략(gmail_app_password.txt 없음)"
    pw = PWFILE.read_text(encoding="utf-8").strip()
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject; msg["From"] = SENDER; msg["To"] = TO
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(context=ctx); s.login(SENDER, pw)
            s.sendmail(SENDER, [TO], msg.as_string())
        return "메일 전송됨"
    except Exception as e:
        return f"메일 실패: {str(e)[:120]}"


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"[{now}] 마이카누 일일 수집"]

    # 1) 수집(헤드리스)
    rc, out = run([PY, "collect_kakao.py", "--folderid", FOLDERS, "--headless"])
    new = 0
    for ln in out.splitlines():
        if "신규" in ln and "추가" in ln:
            import re; m = re.search(r"신규\s*(\d+)", ln)
            if m: new = int(m.group(1))
    names = [ln.strip()[2:] for ln in out.splitlines() if ln.strip().startswith("+ ")]

    if rc == 2:   # 세션 만료
        lines.append("⚠️ 카카오 세션 만료 — 재로그인 필요")
        lines.append("  PC에서:  python collect_kakao.py --folderid " + FOLDERS)
        status = "재로그인 필요"
    elif rc != 0:
        lines.append("❌ 수집 오류"); lines.append(out[-600:]); status = "수집 오류"
    elif new == 0:
        lines.append("신규 장소 없음 (변동 없음)"); status = "변동 없음"
    else:
        lines.append(f"✅ 신규 {new}곳 수집")
        for nm in names[:30]: lines.append("  + " + nm)
        # 2) 빌드
        run([PY, "build_map.py"]); run([PY, "build_map.py", "test"])
        # 3) 변경 있으면 커밋+푸시
        _, st = run(["git", "status", "--porcelain"])
        if st.strip():
            run(["git", "add", "synced_seqs.json", "place_ids.json", "map.html", "index.html", "test.html"])
            run(["git", "commit", "-m", f"카카오 즐겨찾기 신규 {new}곳 자동 수집 ({now})"])
            prc, pout = run(["git", "push"])
            lines.append("📤 푸시 완료" if prc == 0 else "❌ 푸시 실패:\n" + pout[-400:])
            status = f"신규 {new}곳 반영"
        else:
            lines.append("(빌드 결과 변경 없음 — 푸시 생략)"); status = f"신규 {new}곳(푸시생략)"

    body = "\n".join(lines)
    mail = email_report(f"[마이카누] 일일 수집 — {status}", body)
    body += "\n" + mail
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(body + "\n" + ("-" * 40) + "\n")
    print(body)


if __name__ == "__main__":
    main()
