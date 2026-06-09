#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""코스 원커맨드 업데이트: courses_def.json 편집 후 실행하면
OSM 하천 추적 → courses.geojson → map.html 재생성 → git push.
(카카오 로그인 불필요)
"""
import shutil, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PY = sys.executable

print("[1/3] 하천 따라 코스 추적 (trace_course.py)…")
subprocess.run([PY, str(BASE / "trace_course.py")], check=True)

print("[2/3] 지도 재생성 (build_map.py)…")
subprocess.run([PY, str(BASE / "build_map.py")], check=True)
shutil.copyfile(BASE / "map.html", BASE / "index.html")

print("[3/3] git 커밋·푸시…")
subprocess.run(["git", "add", "-A"], cwd=str(BASE))
r = subprocess.run(["git", "commit", "-m", "update: 엑스페디션 코스"], cwd=str(BASE))
if r.returncode != 0:
    print("  변경 없음(커밋 생략)")
push = subprocess.run(["git", "push"], cwd=str(BASE))
if push.returncode == 0:
    print("\n[done] 완료! 1~2분 후 https://kohoon.github.io/mycanoe-map/ 반영.")
else:
    print("\n[!] git push 실패 — 수동으로 'git push' 해보세요.")
