# mycanoe-map — 프로젝트 행동규약

> 전역 규약(`~/.claude/CLAUDE.md`)을 따르되, 이 레포에만 해당하는 사항을 아래에 둔다.
> **정본은 `기획문서.md`** — 사소하지 않은 작업 전에 해당 장(의도·동작·히스토리)을 읽고, 변경 시 같은 커밋에서 갱신한다.

## 정체성
카누 런칭/랜딩·코스·상수원보호구역(진입금지)·장애물을 한 지도에 보여주는 한국형 카누 정적 웹앱.
정적 HTML(Leaflet, 데이터 빌드시 임베드) + Cloudflare Worker(`workers/auth-worker.js`, KV·Kakao OAuth·Google Sheets).
공개: https://kohoon.github.io/mycanoe-map/

## 구조 — 5단 아님
이 레포는 전역 규약의 `ingest/parse/store/analyze/serve` 5단을 **따르지 않는다**.
의도된 단순 스크립트 구조다(빌드시 임베드 → CDN 정적 서빙, 요청당 서버작업 0).
루트 공개 산출물 + `tools/` 스크립트 + `data/` 원천/레지스트리 정도의 얕은 구조만 유지한다. 핵심 파일은 `기획문서.md` 부록 A 참조.

## 빌드 & 배포 (반드시 이 순서)
```
python tools/build_map.py        # index.html / map.html (운영)
python tools/build_map.py test   # test.html (카누잉 기록 포함)
# → Playwright headless 검증: JS 에러 0 + 핵심 함수/엔드포인트
git add … && git commit && git push   # GitHub Pages 자동 반영, Worker 1~2분 자동 재배포
```
- 빌드 후 **항상** headless 검증. 검증 없이 커밋 금지.
- 커밋 메시지 끝: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` (기존 히스토리 관례).

## 데이터 갱신 명령 (원천 갱신 시에만)
- 상수원보호: `tools/rebuild_protect.py`(오프라인, 키 불요) / `tools/build_polygons.py`(deprecated 온라인 크롤러)
- 코스: `tools/trace_course.py`(OSM 물길추적) → `data/courses.geojson`
- 수위관측소: `tools/build_hrfco.py`(HRFCO 키) · 보: 빌드시 자동(원천만 `tools/build_weirs.py`)
- 내수면 금지구역: `tools/build_wlz_inland.py` · 로드뷰: `tools/build_roadview.py`(카카오 JS 키)
- 카카오 즐겨찾기: GitHub Actions `.github/workflows/daily-collect.yml`(매일 09:00 KST) 자동

## 보안 (절대 준수)
- `ADMIN_KEY`·`LOG_WEBHOOK`(Apps Script URL)·Kakao Client Secret → **Cloudflare Secret만**. 코드/레포 금지.
- `vworld_key.txt`·`auth_state.json`·`hrfco_key.txt`·`gmail_app_password.txt` 등 → `.gitignore`.
- `KAKAO_REST_KEY`는 OAuth client_id로 어차피 노출(Redirect URI 화이트리스트 보호) → `wrangler.toml` vars 허용.
- 쓰기 API는 HMAC 서명 토큰(`mc1|uid`, ADMIN_KEY) 검증 — 자기신고 uid 신뢰 금지(2026-06-11 점검).

## 운영 원칙
- **큰 변경(코스/데이터)은 "보여주고 컨펌 후 반영"**.
- 확장은 KV→D1→외부DB 단계 이전(기획문서 8c) — 워커 엔드포인트 계약(URL/JSON)은 고정, 클라이언트 미변경.
