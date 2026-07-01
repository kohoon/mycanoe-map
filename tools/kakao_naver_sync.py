#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kakao_naver_sync.py

카카오맵 즐겨찾기(폴더) → 네이버맵 즐겨찾기(폴더) 자동 동기화.

동작 요약:
  1) Playwright로 브라우저 실행 (로그인 세션은 auth_state.json에 저장/재사용)
  2) 카카오맵 메인에서 favorite list API를 fetch + WCONGNAMUL→WGS84 좌표 변환
  3) synced_seqs.json 과 비교해 신규 항목만 필터
  4) 네이버맵 좌표 검색 → 저장 위젯 열기 → 별명 입력 → 대상 폴더 선택 → 저장
  5) 검증(aria-pressed=true) 성공 시 seq 를 synced_seqs.json 에 기록
  6) 봇 감지 회피용 랜덤 딜레이/휴식

사용 예:
  # 최초 1회 (현재 카카오 폴더 전체를 'synced'로 기록만, 저장 안 함)
  python kakao_naver_sync.py --folderid 20842531 --folder "마이카누" --mark-all-synced

  # 이후 매번 (신규만 네이버에 저장)
  python kakao_naver_sync.py --folderid 20842531 --folder "마이카누"
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# Windows 콘솔(cp949)에서도 한글/이모지 출력이 깨지거나 크래시하지 않도록 UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 경로/상수
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
AUTH_STATE = BASE_DIR / "auth_state.json"
SYNCED_FILE = DATA_DIR / "synced_seqs.json"

KAKAO_MAIN = "https://map.kakao.com/"
KAKAO_FAV_API = "https://map.kakao.com/favorite/mine/list?folderid={folderid}"
NAVER_SEARCH = "https://map.naver.com/p/search/{lat},{lng}"

# 봇 감지 회피용 딜레이(초)
ITEM_DELAY = (5, 8)        # 항목 간
REST_EVERY = 10            # N개마다
REST_DELAY = (25, 35)      # 휴식


# ---------------------------------------------------------------------------
# 로컬 상태 (synced_seqs.json)
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """
    상태를 {seq: {name, lat, lng, naver}} 형태의 dict로 반환.
    구버전(seq 문자열 리스트)도 자동 변환해 호환.
    """
    if not SYNCED_FILE.exists():
        return {}
    try:
        data = json.loads(SYNCED_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] synced_seqs.json 읽기 실패({e}) → 빈 상태로 시작")
        return {}
    # 구버전: ["seq1","seq2",...]
    if isinstance(data, list):
        return {str(s): {"name": None, "lat": None, "lng": None, "naver": "legacy"}
                for s in data}
    # 신버전: {"version":2, "items": {...}}
    if isinstance(data, dict) and "items" in data:
        return {str(k): v for k, v in data["items"].items()}
    # 혹시 {seq: info} 형태로 바로 저장된 경우
    if isinstance(data, dict):
        return {str(k): v for k, v in data.items()}
    return {}


def save_state(state: dict) -> None:
    SYNCED_FILE.write_text(
        json.dumps({"version": 2, "items": state}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 카카오: 즐겨찾기 fetch + 좌표 변환 (페이지 컨텍스트에서 실행)
# ---------------------------------------------------------------------------
# 카카오 favorite API는 WCONGNAMUL 좌표를 돌려준다. 페이지에 로드된 kakao 맵 SDK로
# WGS84(위경도)로 변환한다. SDK 버전/로드 상태에 따라 변환 경로가 달라서 여러 방법을 순차 시도.
KAKAO_FETCH_JS = r"""
async (folderid) => {
  // kakao SDK 로드 대기 (최대 ~15초)
  for (let i = 0; i < 30 && (typeof kakao === 'undefined' || !kakao.maps); i++) {
    await new Promise(r => setTimeout(r, 500));
  }
  if (typeof kakao === 'undefined' || !kakao.maps) {
    return {error: 'kakao.maps not loaded'};
  }

  const url = `https://map.kakao.com/favorite/mine/list?folderid=${folderid}`;
  let json;
  try {
    const res = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}});
    json = await res.json();
  } catch (e) {
    return {error: 'fetch failed: ' + e.message};
  }

  // 로그인 안 됨 등 status 래퍼 처리
  if (json && json.status && json.status.code &&
      json.status.code !== 'OK' && json.status.code !== 0 && json.status.code !== '0') {
    return {error: 'kakao status: ' + json.status.code + ' / ' + (json.status.message || ''), raw: json};
  }

  // 응답에서 항목 배열 찾아내기.
  // 키 이름을 모르므로: (1) 알려진 키 우선, (2) 없으면 응답 전체를 훑어
  // "객체들의 배열이면서 좌표/이름 비슷한 필드를 가진" 첫 배열을 자동 선택.
  const looksLikeItem = (o) =>
    o && typeof o === 'object' &&
    (o.x != null || o.posX != null || o.cx != null || (o.coord && o.coord.x != null) ||
     o.name != null || o.title != null || o.placeName != null);
  const findArray = (node, depth) => {
    if (depth > 4 || node == null || typeof node !== 'object') return null;
    if (Array.isArray(node)) {
      return node.length && looksLikeItem(node[0]) ? node : null;
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (Array.isArray(v) && v.length && looksLikeItem(v[0])) return v;
    }
    for (const k of Object.keys(node)) {
      const found = findArray(node[k], depth + 1);
      if (found) return found;
    }
    return null;
  };
  let items =
    json.favoriteList || json.favorites || json.list ||
    (json.data && (json.data.favoriteList || json.data.list)) || null;
  if (!items || !Array.isArray(items)) items = findArray(json, 0);
  if (!items) {
    return {error: 'unexpected schema', raw: json, topKeys: Object.keys(json || {})};
  }

  // WCONGNAMUL -> WGS84 변환기
  const congToWgs = (x, y) => {
    // 1) kakao.maps.Coords (구 daum) 경로
    try {
      if (kakao.maps.Coords) {
        const ll = new kakao.maps.Coords(Number(x), Number(y)).toLatLng();
        return {lat: ll.getLat(), lng: ll.getLng()};
      }
    } catch (e) {}
    return null;
  };

  // 2) services.Geocoder.transCoord (비동기) 경로 — Coords가 없을 때 사용
  const transCoordAsync = (x, y) => new Promise((resolve) => {
    try {
      const geocoder = new kakao.maps.services.Geocoder();
      geocoder.transCoord(Number(x), Number(y), (result, status) => {
        if (status === kakao.maps.services.Status.OK && result[0]) {
          resolve({lat: Number(result[0].y), lng: Number(result[0].x)});
        } else {
          resolve(null);
        }
      }, {
        input_coord: kakao.maps.services.Coords.CONGNAMUL,
        output_coord: kakao.maps.services.Coords.WGS84
      });
    } catch (e) { resolve(null); }
  });

  const out = [];
  for (const it of items) {
    // 카카오 favorite 스키마: display1=제목, display2=주소, memo=메모
    const seq = it.seq ?? it.id ?? it.favoriteId ?? it.itemId ?? null;
    const name = it.display1 ?? it.name ?? it.title ?? it.placeName ?? it.display2 ?? '';
    const addr = it.display2 ?? '';
    const memo = it.memo ?? '';
    const x = it.x ?? it.posX ?? it.cx ?? (it.coord && it.coord.x);
    const y = it.y ?? it.posY ?? it.cy ?? (it.coord && it.coord.y);

    let coord = null;
    if (x != null && y != null) {
      coord = congToWgs(x, y);
      if (!coord && kakao.maps.services) {
        coord = await transCoordAsync(x, y);
      }
    }
    out.push({seq: String(seq), name, addr, memo, x, y,
              lat: coord ? coord.lat : null, lng: coord ? coord.lng : null});
  }
  return {items: out};
}
"""


def fetch_kakao_favorites(page, folderid: str, quiet: bool = False) -> list:
    """카카오 폴더의 즐겨찾기 항목 리스트를 반환. [{seq,name,lat,lng}, ...]"""
    if not quiet:
        print(f"[kakao] 메인 페이지 로딩…")
    page.goto(KAKAO_MAIN, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        if not quiet:
            print("[kakao] networkidle 대기 타임아웃 — 계속 진행")
    # SDK 로드 대기
    try:
        page.wait_for_function("typeof kakao !== 'undefined' && !!kakao.maps", timeout=15000)
    except PWTimeout:
        if not quiet:
            print("[kakao] kakao.maps 로드 대기 실패 — fetch 시 에러날 수 있음")

    result = page.evaluate(KAKAO_FETCH_JS, folderid)
    if isinstance(result, dict) and result.get("error"):
        err = result["error"]
        # 로그인 필요는 복구 가능 → 빈 리스트로 돌려보내 로그인 대기 루프가 돌게 한다
        if "NOT_LOGIN_USER" in err or "로그인" in err:
            if not quiet:
                print("[kakao] 로그인이 필요합니다.")
            return []
        if quiet:
            return []
        print(f"[kakao][error] {err}")
        if "topKeys" in result:
            print("[kakao] 응답 최상위 키:", result["topKeys"])
        if "raw" in result:
            print("[kakao] 원본 응답(앞부분):",
                  json.dumps(result["raw"], ensure_ascii=False)[:1000])
        sys.exit(1)

    items = result.get("items", [])
    if quiet:
        return items
    print(f"[kakao] 즐겨찾기 {len(items)}개 수신")
    if items:
        # 필드 매핑 확인용: 첫 항목 샘플 출력
        s = items[0]
        print(f"[kakao] 샘플: seq={s['seq']} name={s['name']!r} "
              f"x={s['x']} y={s['y']} -> lat={s['lat']} lng={s['lng']}")
    # 좌표 변환 실패한 항목 경고
    bad = [it for it in items if it.get("lat") is None]
    if bad:
        print(f"[kakao][warn] 좌표 변환 실패 {len(bad)}개 (예: {bad[0]['name']})")
    return items


# ---------------------------------------------------------------------------
# 네이버: 좌표 검색 → 저장 위젯 → 폴더 선택 → 저장
# ---------------------------------------------------------------------------
WIDGET_SEL = "#swt-save-widget-wrap"


def _naver_logged_in(context) -> bool:
    """네이버 로그인 여부를 쿠키(NID_AUT)로 판단."""
    try:
        for c in context.cookies():
            if c.get("name") == "NID_AUT" and "naver" in (c.get("domain") or ""):
                return True
    except Exception:
        pass
    return False


# 카카오 계정 로그인 시 .kakao.com 에 설정되는 인증 토큰 쿠키들
_KAKAO_AUTH_COOKIES = {"_kawlt", "_kawltea", "_karmt", "_kahai"}


def _kakao_logged_in(context) -> bool:
    """카카오 로그인 여부를 인증 쿠키로 판단(페이지 이동 없이)."""
    try:
        for c in context.cookies():
            if c.get("name") in _KAKAO_AUTH_COOKIES and "kakao" in (c.get("domain") or ""):
                return True
    except Exception:
        pass
    return False


def _open_place(page, lat, lng):
    """좌표로 장소 패널을 열고 (fav_btn, pressed) 반환. 실패 시 (None, 에러코드)."""
    url = NAVER_SEARCH.format(lat=lat, lng=lng)
    page.goto(url, wait_until="domcontentloaded")
    # 좌표 검색은 /p/entry/coordinates/ 로 리다이렉트됨
    try:
        page.wait_for_url("**/p/entry/**", timeout=20000)
    except PWTimeout:
        pass
    try:
        page.wait_for_selector("button.btn_favorite", timeout=15000)
    except PWTimeout:
        return None, "no_panel"
    fav_btn = page.locator("button.btn_favorite").first
    pressed = (fav_btn.get_attribute("aria-pressed") or "").lower() == "true"
    return fav_btn, pressed


def _open_widget(page):
    """저장 위젯을 열어 locator 반환. 실패 시 None."""
    try:
        page.wait_for_selector(WIDGET_SEL, state="visible", timeout=12000)
    except PWTimeout:
        return None
    return page.locator(WIDGET_SEL)


def _expand_alias(widget, page):
    """'+ 메모, 별명, URL 추가' 토글을 눌러 별명 입력란을 노출."""
    try:
        toggle = widget.locator(
            "xpath=.//*[contains(text(),'별명') or contains(text(),'메모')]"
        ).first
        if toggle.count() > 0:
            toggle.click()
            page.wait_for_timeout(400)
    except Exception:
        pass


def _set_alias(widget, name, page):
    if not name:
        return
    try:
        alias = widget.locator(
            "input[placeholder*='별명'], textarea[placeholder*='별명']"
        ).first
        if alias.count() > 0:
            alias.fill(name)
    except Exception:
        print(f"  [warn] 별명 입력란 못 찾음: {name}")


def _set_memo(widget, memo):
    """카카오 메모를 네이버 메모란에 입력(있을 때만, 베스트에포트)."""
    if not memo:
        return
    try:
        m = widget.locator(
            "textarea[placeholder*='메모'], input[placeholder*='메모']"
        ).first
        if m.count() > 0:
            m.fill(memo)
    except Exception:
        pass


def _find_folder_idx(widget, folder):
    """위젯 내 대상 폴더 li 인덱스 반환. 못 찾으면 -1."""
    groups = widget.locator("li.swt-save-group-item")
    n = groups.count()
    partial = -1
    for i in range(n):
        gname = (groups.nth(i).locator(".swt-save-group-name").inner_text() or "").strip()
        if gname == folder:
            return i
        if folder in gname or gname in folder:
            partial = i
    return partial


def _click_save(widget):
    save_btn = widget.locator(
        "xpath=.//button[contains(.,'저장') or contains(.,'완료') or contains(.,'추가')]"
    ).first
    if save_btn.count() == 0:
        return False
    save_btn.click()
    return True


def save_to_naver(page, item: dict, folder: str) -> str:
    """
    한 항목을 네이버맵 대상 폴더에 저장.
    반환: 'ok' | 'skip_already' | 에러코드(문자열)
    """
    lat, lng = item["lat"], item["lng"]
    name = item["name"]
    if lat is None or lng is None:
        return "no_coord"

    fav_btn, pressed = _open_place(page, lat, lng)
    if fav_btn is None:
        return pressed  # 에러코드
    if pressed:
        return "skip_already"  # 이미 어딘가에 저장됨

    fav_btn.click()
    widget = _open_widget(page)
    if widget is None:
        return "no_widget"

    _expand_alias(widget, page)
    _set_alias(widget, name, page)
    _set_memo(widget, item.get("memo"))

    idx = _find_folder_idx(widget, folder)
    if idx < 0:
        return "no_folder"
    widget.locator("li.swt-save-group-item").nth(idx).click()
    page.wait_for_timeout(300)

    if not _click_save(widget):
        return "no_save_btn"

    # 검증: aria-pressed=true 로 바뀌었는지
    try:
        page.wait_for_function(
            """() => {
                const b = document.querySelector('button.btn_favorite');
                return b && b.getAttribute('aria-pressed') === 'true';
            }""",
            timeout=10000,
        )
    except PWTimeout:
        return "verify_failed"
    return "ok"


def remove_from_naver(page, info: dict, folder: str) -> str:
    """
    카카오에서 삭제된 항목을 네이버 대상 폴더에서 제거.
    저장 위젯을 열어 대상 폴더 체크를 해제하고 저장.
    반환: 'ok' | 'already_absent' | 에러코드
    """
    lat, lng = info.get("lat"), info.get("lng")
    if lat is None or lng is None:
        return "no_coord"

    fav_btn, pressed = _open_place(page, lat, lng)
    if fav_btn is None:
        return pressed
    if not pressed:
        return "already_absent"  # 저장 안 돼 있음

    fav_btn.click()
    widget = _open_widget(page)
    if widget is None:
        return "no_widget"

    idx = _find_folder_idx(widget, folder)
    if idx < 0:
        # 대상 폴더에 들어있지 않음 → 우리가 건드릴 것 없음
        return "already_absent"
    # 폴더 li 클릭 = 토글. 현재 체크돼 있다고 보고 해제.
    widget.locator("li.swt-save-group-item").nth(idx).click()
    page.wait_for_timeout(300)
    if not _click_save(widget):
        return "no_save_btn"
    page.wait_for_timeout(800)
    return "ok"


def update_alias_naver(page, item: dict, folder: str) -> str:
    """
    이름(별명)이 바뀐 항목의 네이버 별명을 갱신.
    저장된 장소면 위젯을 열어 별명만 새로 입력 후 저장.
    반환: 'ok' | 'not_saved' | 에러코드
    """
    lat, lng = item["lat"], item["lng"]
    if lat is None or lng is None:
        return "no_coord"

    fav_btn, pressed = _open_place(page, lat, lng)
    if fav_btn is None:
        return pressed
    if not pressed:
        # 저장돼 있지 않으면 그냥 신규 저장으로 처리
        return "not_saved"

    fav_btn.click()
    widget = _open_widget(page)
    if widget is None:
        return "no_widget"

    _expand_alias(widget, page)
    _set_alias(widget, item["name"], page)
    # 대상 폴더가 선택 해제되지 않도록 idx 확인만(이미 체크된 상태 가정, 클릭하지 않음)
    if not _click_save(widget):
        return "no_save_btn"
    page.wait_for_timeout(600)
    return "ok"


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def sleep_rand(rng):
    t = random.uniform(*rng)
    time.sleep(t)
    return t


def ensure_naver_login(page, context, headless) -> bool:
    """네이버 로그인 보장. 이미 로그인이면 True, 아니면 안내 후 Enter 대기."""
    if _naver_logged_in(context):
        return True
    if headless:
        print("[!] 네이버 로그인 세션이 없습니다(헤드리스). 먼저 헤드풀로 로그인하세요.")
        return False
    page.goto("https://map.naver.com/", wait_until="domcontentloaded")
    page.bring_to_front()
    print("\n" + "=" * 64)
    print("  열린 브라우저 창에서 [네이버 로그인]을 해주세요.")
    print("  (2단계 인증이 있으면 그것까지 모두 끝내세요.)")
    print("  로그인을 전부 마친 뒤, 이 터미널로 돌아와 Enter를 누르세요.")
    print("=" * 64)
    for _ in range(8):
        try:
            input("    >> 네이버 로그인을 마쳤으면 Enter (종료하려면 Ctrl+C): ")
        except EOFError:
            break
        if _naver_logged_in(context):
            print("[naver] 로그인 확인됨")
            return True
        print("    아직 네이버 로그인이 확인되지 않았습니다. 다시 Enter를 눌러주세요.")
    return False


def main():
    ap = argparse.ArgumentParser(description="카카오맵→네이버맵 즐겨찾기 동기화")
    ap.add_argument("--folderid", required=True, help="카카오 폴더 ID (folderid=XXX)")
    ap.add_argument("--folder", required=True, help="네이버 대상 폴더명 (정확히 일치)")
    ap.add_argument("--mark-all-synced", action="store_true",
                    help="현재 카카오 폴더 전체를 synced로 기록만 (저장 안 함)")
    ap.add_argument("--headless", action="store_true", help="헤드리스 모드")
    ap.add_argument("--max-items", type=int, default=0, help="이번 실행 최대 처리 개수(0=무제한)")
    ap.add_argument("--no-delete", action="store_true",
                    help="카카오에서 삭제된 항목을 네이버에서 제거하지 않음")
    ap.add_argument("--no-rename", action="store_true",
                    help="이름(별명)이 바뀐 항목을 네이버에서 갱신하지 않음")
    ap.add_argument("--test-save", metavar="LAT,LNG",
                    help="진단용: 지정 좌표에 저장 위젯 플로우만 시험 (카카오 fetch 안 함)")
    ap.add_argument("--dump-widget", metavar="LAT,LNG",
                    help="진단용: 저장된 좌표의 위젯/폴더 마크업을 덤프 (폴더 체크상태 파악)")
    args = ap.parse_args()

    state = load_state()  # {seq: {name, lat, lng, naver}}
    print(f"[state] 기존 기록 {len(state)}개")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx_kwargs = {"locale": "ko-KR"}
        if AUTH_STATE.exists():
            ctx_kwargs["storage_state"] = str(AUTH_STATE)
            print(f"[auth] 저장된 세션 재사용: {AUTH_STATE.name}")
        else:
            print("[auth] 저장된 세션 없음 — 브라우저에서 카카오/네이버 로그인 필요")
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.set_default_timeout(20000)

        # --- 진단: --dump-widget 위젯/폴더 마크업 덤프 ---
        if args.dump_widget:
            try:
                lat, lng = [float(v) for v in args.dump_widget.split(",")]
            except Exception:
                print("[!] --dump-widget 형식은 LAT,LNG")
                browser.close(); return
            if not ensure_naver_login(page, context, args.headless):
                browser.close(); return
            fav_btn, pressed = _open_place(page, lat, lng)
            if fav_btn is None:
                print(f"[dump] 패널 열기 실패: {pressed}"); browser.close(); return
            print(f"[dump] aria-pressed(저장됨?) = {pressed}")
            fav_btn.click()
            widget = _open_widget(page)
            if widget is None:
                print("[dump] 위젯 안 열림"); browser.close(); return
            info = page.evaluate(r"""() => {
                const w = document.querySelector('#swt-save-widget-wrap');
                const lis = [...w.querySelectorAll('li.swt-save-group-item')];
                return lis.map(li => {
                    const nameEl = li.querySelector('.swt-save-group-name');
                    const cb = li.querySelector('input[type=checkbox]');
                    const btn = li.querySelector('button');
                    return {
                        name: nameEl ? nameEl.textContent.trim() : '(no-name)',
                        liClass: li.className,
                        liAriaSelected: li.getAttribute('aria-selected'),
                        liAriaChecked: li.getAttribute('aria-checked'),
                        checkboxChecked: cb ? cb.checked : null,
                        checkboxAriaChecked: cb ? cb.getAttribute('aria-checked') : null,
                        btnAriaPressed: btn ? btn.getAttribute('aria-pressed') : null,
                        btnAriaChecked: btn ? btn.getAttribute('aria-checked') : null,
                        outerHTML: li.outerHTML.slice(0, 400)
                    };
                });
            }""")
            print(f"[dump] 폴더 {len(info)}개:")
            for i, f in enumerate(info):
                print(f"\n  [{i}] name='{f['name']}'")
                print(f"      liClass={f['liClass']!r}")
                print(f"      li.aria-selected={f['liAriaSelected']} li.aria-checked={f['liAriaChecked']}")
                print(f"      checkbox.checked={f['checkboxChecked']} checkbox.aria-checked={f['checkboxAriaChecked']}")
                print(f"      btn.aria-pressed={f['btnAriaPressed']} btn.aria-checked={f['btnAriaChecked']}")
                print(f"      outerHTML={f['outerHTML']}")
            browser.close(); return

        # --- 진단: --test-save 좌표에 저장 위젯 플로우만 시험 ---
        if args.test_save:
            try:
                lat, lng = [float(v) for v in args.test_save.split(",")]
            except Exception:
                print("[!] --test-save 형식은 LAT,LNG (예: 37.5665,126.9780)")
                browser.close()
                return
            if not ensure_naver_login(page, context, args.headless):
                print("[!] 네이버 로그인 필요. 종료.")
                context.storage_state(path=str(AUTH_STATE))
                browser.close()
                return
            item = {"name": "[테스트] 저장확인", "memo": "test-save 진단",
                    "lat": lat, "lng": lng}
            print(f"[test-save] ({lat},{lng}) 저장 시도 → 폴더 '{args.folder}'")
            res = save_to_naver(page, item, args.folder)
            print(f"[test-save] 결과: {res}")
            context.storage_state(path=str(AUTH_STATE))
            browser.close()
            return

        # --- 카카오 fetch ---
        items = fetch_kakao_favorites(page, args.folderid)

        # 로그인 안 된 경우 0개 → 브라우저에서 직접 로그인(2단계 인증 포함) 후 Enter
        if not items and not args.headless:
            print("\n" + "=" * 64)
            print("  열린 브라우저 창에서 [카카오 로그인]을 해주세요.")
            print("  (2단계 인증이 있으면 그것까지 모두 끝내세요.)")
            print("  로그인을 전부 마친 뒤, 이 터미널로 돌아와 Enter를 누르세요.")
            print("=" * 64)
            page.bring_to_front()
            for _ in range(8):
                try:
                    input("    >> 카카오 로그인을 마쳤으면 Enter (종료하려면 Ctrl+C): ")
                except EOFError:
                    break
                items = fetch_kakao_favorites(page, args.folderid)
                if items:
                    break
                print("    아직 즐겨찾기를 읽지 못했습니다. 로그인 상태를 확인하고 다시 Enter를 눌러주세요.")
            if not items:
                print("[!] 로그인 확인에 실패했습니다. 종료합니다.")

        current = {it["seq"]: it for it in items}  # seq -> kakao item

        # --- mark-all-synced: 저장 없이 전체 스냅샷 기록만 ---
        if args.mark_all_synced:
            state = {
                seq: {"name": it["name"], "memo": it.get("memo", ""),
                      "lat": it["lat"], "lng": it["lng"], "naver": "baseline"}
                for seq, it in current.items()
            }
            save_state(state)
            context.storage_state(path=str(AUTH_STATE))
            print(f"\n[done] {len(state)}개를 모두 기록(스냅샷). 저장은 하지 않았습니다.")
            print(f"[auth] 세션 저장: {AUTH_STATE.name}")
            browser.close()
            return

        # --- diff 계산: 추가 / 삭제 / 이름변경 ---
        added = [it for seq, it in current.items() if seq not in state]
        removed = [(seq, info) for seq, info in state.items() if seq not in current]
        renamed = [
            it for seq, it in current.items()
            if seq in state and state[seq].get("name") not in (None, it["name"])
        ]
        print(f"[diff] 추가 {len(added)} / 삭제 {len(removed)} / 이름변경 {len(renamed)} "
              f"(카카오 {len(current)} / 기록 {len(state)})")
        if args.max_items > 0:
            added = added[: args.max_items]
            print(f"[diff] --max-items 적용 → 추가분 {len(added)}개만 처리")

        if not added and not removed and not renamed:
            print("[done] 변경 사항 없음.")
            context.storage_state(path=str(AUTH_STATE))
            browser.close()
            return

        # 네이버 로그인 (이미 로그인돼 있으면 건너뜀)
        if not args.headless:
            if not ensure_naver_login(page, context, args.headless):
                print("[!] 네이버 로그인 확인 실패. 종료합니다.")
                context.storage_state(path=str(AUTH_STATE))
                browser.close()
                return

        stats = {"add": 0, "skip": 0, "del": 0, "rename": 0, "fail": 0}

        def pace(i, total):
            if i < total:
                if i % REST_EVERY == 0:
                    t = sleep_rand(REST_DELAY)
                    print(f"    …{i}개 처리, {t:.0f}s 휴식")
                else:
                    sleep_rand(ITEM_DELAY)

        # --- 1) 삭제 처리 ---
        if removed and not args.no_delete:
            for i, (seq, info) in enumerate(removed, 1):
                label = f"[삭제 {i}/{len(removed)}] {info.get('name')}"
                try:
                    res = remove_from_naver(page, info, args.folder)
                except Exception as e:
                    res = f"exception: {e}"
                if res in ("ok", "already_absent"):
                    state.pop(seq, None)
                    save_state(state)
                    stats["del"] += 1
                    print(f"{label} → 네이버에서 제거 {'완료' if res=='ok' else '(이미 없음)'} 🗑️")
                else:
                    stats["fail"] += 1
                    print(f"{label} → 제거 실패: {res} ❌")
                pace(i, len(removed))
        elif removed:
            print(f"[del] --no-delete 지정 → 삭제 {len(removed)}건 건너뜀")

        # --- 2) 이름변경 처리 ---
        if renamed and not args.no_rename:
            for i, it in enumerate(renamed, 1):
                label = f"[변경 {i}/{len(renamed)}] {it['name']}"
                try:
                    res = update_alias_naver(page, it, args.folder)
                except Exception as e:
                    res = f"exception: {e}"
                if res == "ok":
                    state[it["seq"]] = {"name": it["name"], "memo": it.get("memo", ""),
                                        "lat": it["lat"], "lng": it["lng"], "naver": "saved"}
                    save_state(state)
                    stats["rename"] += 1
                    print(f"{label} → 별명 갱신 ✏️")
                elif res == "not_saved":
                    # 네이버에 없던 항목 → 신규 저장 대상으로 합류
                    added.append(it)
                    print(f"{label} → 네이버에 없음, 신규 저장으로 처리")
                else:
                    stats["fail"] += 1
                    print(f"{label} → 갱신 실패: {res} ❌")
                pace(i, len(renamed))
        elif renamed:
            print(f"[rename] --no-rename 지정 → 변경 {len(renamed)}건 건너뜀")

        # --- 3) 추가 처리 ---
        for i, it in enumerate(added, 1):
            label = f"[추가 {i}/{len(added)}] {it['name']}"
            try:
                res = save_to_naver(page, it, args.folder)
            except Exception as e:
                res = f"exception: {e}"
            if res == "ok":
                state[it["seq"]] = {"name": it["name"], "memo": it.get("memo", ""),
                                    "lat": it["lat"], "lng": it["lng"], "naver": "saved"}
                save_state(state)
                stats["add"] += 1
                print(f"{label} → 저장 완료 ✅")
            elif res == "skip_already":
                state[it["seq"]] = {"name": it["name"], "memo": it.get("memo", ""),
                                    "lat": it["lat"], "lng": it["lng"], "naver": "skipped"}
                save_state(state)
                stats["skip"] += 1
                print(f"{label} → 이미 저장됨(스킵) ⏭️")
            else:
                stats["fail"] += 1
                print(f"{label} → 실패: {res} ❌")
            pace(i, len(added))

        context.storage_state(path=str(AUTH_STATE))
        print(f"\n[done] 완료 ✅ 추가 {stats['add']} / 스킵 {stats['skip']} / "
              f"삭제 {stats['del']} / 변경 {stats['rename']} / 실패 {stats['fail']}")
        print(f"[auth] 세션 저장: {AUTH_STATE.name}")
        browser.close()


if __name__ == "__main__":
    main()
