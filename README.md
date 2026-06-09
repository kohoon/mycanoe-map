# 마이카누 지도 (mycanoe-map)

카누 타고 내릴 수 있는 즐겨찾기 지점과 **상수원보호구역**(진입 금지)을 한 지도에서 보는 프로젝트.

## 🗺️ 지도 보기
- 공개 지도: **https://kohoon.github.io/mycanoe-map/** (GitHub Pages 활성화 후)
- 로컬: `map.html` 더블클릭 (자체포함, 서버·키 불필요)

지도 구성
- 🔵 **카누 진입/하선 지점** — 즐겨찾기 157곳 (이름·메모 팝업)
- 🔴 **상수원보호구역(면)** — 전국 2,159필지 (클릭 시 시·군·구)
- 베이스맵: OpenStreetMap

## 📂 구성

| 파일 | 설명 |
|---|---|
| `index.html` / `map.html` | 자체포함 지도 (폴리곤·점 임베드, 키 불필요) |
| `protect_polygons.geojson` | 상수원보호구역 면(단순화) |
| `synced_seqs.json` | 카누 즐겨찾기 점 데이터 |
| `build_polygons.py` | V-World API로 상수원보호구역 폴리곤 수집·단순화 |
| `build_map.py` | 데이터 → `map.html` 생성 |
| `protect_endpoints.py` / `protect_zones.py` | 구역 군집화·대표점 계산 |
| `kakao_naver_sync.py` | 카카오맵 즐겨찾기 → 네이버맵 동기화 |
| `kakao_add_favorites.py` | 카카오 폴더에 상수원보호구역 마커 일괄 추가 |

## 🔄 데이터 갱신
```bash
# V-World 키 준비 (둘 중 하나)
set VWORLD_KEY=발급키          # 또는 vworld_key.txt 에 키 저장
python build_polygons.py        # 폴리곤 재수집·단순화
python build_map.py             # map.html 재생성
```

## 🔐 참고
- `auth_state.json`(로그인 세션), `vworld_key.txt`(API 키)는 `.gitignore`로 제외 — 공개 금지.
- 데이터 출처: [V-World](https://www.vworld.kr) 상수원보호 `LT_C_UM710` (국토교통부).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
