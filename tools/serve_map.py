#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map.html 을 localhost 로 서빙하고 브라우저로 연다.
(V-World WMS 는 등록 도메인 http://localhost 에서 호출돼야 해서 file:// 가 아닌 서버 필요)"""
import functools, http.server, socketserver, sys, webbrowser
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
PORT = 8000
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(BASE))
try:
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
except OSError:
    PORT = 8001
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)

url = f"http://localhost:{PORT}/map.html"
print(f"[serve] {url}")
print("[serve] 브라우저를 엽니다. 종료하려면 이 창에서 Ctrl+C.")
webbrowser.open(url)
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print("\n[serve] 종료")
