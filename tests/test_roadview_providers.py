#!/usr/bin/env python3
"""로드뷰 제공처 링크가 현재 촬영물 확인을 우회하지 않는지 점검한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "tools" / "build_map.py").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    # 품질 검토에서 제외한 사용자 촬영 제공처는 UI와 URL 생성 코드에 남기지 않는다.
    for provider in ("mapillary", "kartaview"):
        assert f'data-rv-provider="{provider}"' not in html.lower()
        assert f"kind==='{provider}'" not in source.lower()

    # API 키 없이 현재 촬영물 존재를 검증할 수 없는 제공처는 선택 불가여야 한다.
    for provider in ("naver", "google"):
        marker = f'data-rv-provider="{provider}"'
        start = html.index(marker)
        button = html[html.rfind("<button", 0, start) : html.index("</button>", start)]
        assert " disabled" in button
        assert "확인 키 필요" in button

    # 함수 직접 호출로 disabled 상태를 우회해 외부 링크를 열 수 없어야 한다.
    assert "if(!b||b.disabled)return" in source

    # 공유 URL의 파노라마 ID만 믿지 않고 현재 좌표의 파노라마를 먼저 재조회한다.
    callback = source.index("_rvClient.getNearestPanoId(pos,120")
    restored_id = source.index("state&&isFinite(state.panoId)", callback)
    assert callback < restored_id
    print("roadview provider availability regression: ok")


if __name__ == "__main__":
    main()
