/**
 * 마이카누 지도 — Google Apps Script (LOG_WEBHOOK 수신).
 * Cloudflare Worker 가 보내는 모든 type 을 각 시트 탭에 한 줄씩 기록한다.
 *
 * 적용:
 *   1) https://script.google.com → 이 프로젝트 열기 → 코드 전체를 이 내용으로 교체
 *   2) 배포 → 새 배포 또는 기존 배포 관리 → 버전 새로 만들기 → 배포
 *      (URL 이 바뀌면 Cloudflare Worker 의 Secret LOG_WEBHOOK 도 새 URL 로 갱신)
 *   3) 액세스: "나"(소유자) 실행 / "모든 사용자"(익명 포함) 접근 허용
 *
 * 받는 type:
 *   visit   {id, nick, type, dev}                        → logins
 *   comment {cid, place, nick, text, stars, img}         → comments
 *   suggest {cat, place, nick, text, lat, lng, img}      → suggestions
 *   collect {status, added, detail}                      → collect
 *   soyang_travers {id, nick, name, cafeNick, phone}     → soyang_travers
 */

function doPost(e) {
  var out = "ok";
  try {
    var d = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var now = new Date();

    if (d.type === "comment") {
      appendRow_(ss, "comments",
        ["시각", "ID", "장소", "닉네임", "별점", "코멘트", "사진"],
        [now, d.cid || "", d.place || "", d.nick || "", d.stars || "", d.text || "", d.img || ""]);

    } else if (d.type === "suggest") {
      appendRow_(ss, "suggestions",
        ["시각", "유형", "장소/주소", "닉네임", "설명", "위도", "경도", "사진"],
        [now, d.cat || "", d.place || "", d.nick || "", d.text || "", d.lat || "", d.lng || "", d.img || ""]);

    } else if (d.type === "collect") {
      appendRow_(ss, "collect",
        ["시각", "상태", "신규", "상세"],
        [now, d.status || "", d.added || 0, d.detail || ""]);

    } else if (d.type === "soyang_travers") {
      appendRow_(ss, "soyang_travers",
        ["시각", "카카오ID", "카카오닉네임", "실명", "카페닉네임", "휴대전화", "동의"],
        [now, d.id || "", d.nick || "", d.name || "", d.cafeNick || "", d.phone || "", "Y"]);

    } else { // visit (기본)
      appendRow_(ss, "logins",
        ["시각", "카카오ID", "닉네임", "구분", "기기"],
        [now, d.id || "", d.nick || "", d.type || "visit", d.dev || ""]);
    }
  } catch (err) {
    out = "err: " + err;
  }
  return ContentService.createTextOutput(out);
}

// 시트가 없으면 헤더와 함께 생성하고, 한 줄 추가
function appendRow_(ss, name, header, row) {
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); }
  if (sh.getLastRow() === 0) { sh.appendRow(header); }
  sh.appendRow(row);
}

// (선택) GET 테스트용 — 브라우저로 열면 동작 확인
function doGet() {
  return ContentService.createTextOutput("mycanoe webhook ok");
}
