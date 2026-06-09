/**
 * Cloudflare Worker — V-World 역지오코딩 프록시
 * V-World 키를 클라이언트에 노출하지 않고 지번 주소를 중계.
 *
 * 배포(대시보드): dash.cloudflare.com → Workers & Pages → 이 코드 붙여넣기 → Deploy
 * 시크릿: Settings → Variables and Secrets → Secret 추가 VWORLD_KEY = 발급키
 *
 * 사용: GET https://<worker>/?lat=37.083&lng=128.492 → {"parcel":"충청북도 단양군 영춘면 상리 702","road":"..."}
 */
export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Content-Type": "application/json; charset=utf-8",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    const url = new URL(request.url);
    const lat = url.searchParams.get("lat");
    const lng = url.searchParams.get("lng");
    if (!lat || !lng || isNaN(+lat) || isNaN(+lng)) {
      return new Response(JSON.stringify({ error: "lat,lng required" }), { status: 400, headers: cors });
    }
    if (!env.VWORLD_KEY) {
      return new Response(JSON.stringify({ error: "VWORLD_KEY not set" }), { status: 500, headers: cors });
    }

    const api = "https://api.vworld.kr/req/address?service=address&request=getAddress&version=2.0"
      + "&crs=EPSG:4326&type=both&format=json"
      + "&point=" + lng + "," + lat
      + "&key=" + env.VWORLD_KEY
      + "&domain=" + encodeURIComponent("http://localhost");

    let r, txt;
    try {
      r = await fetch(api, {
        headers: {
          "User-Agent": "Mozilla/5.0 (compatible; mycanoe-map/1.0)",
          "Accept": "application/json",
          "Referer": "http://localhost/",
        },
      });
      txt = await r.text();
    } catch (e) {
      return new Response(JSON.stringify({ error: "fetch failed: " + String(e) }), { status: 502, headers: cors });
    }

    let d;
    try {
      d = JSON.parse(txt);
    } catch (e) {
      // V-World가 JSON이 아닌 응답(차단/502 등)을 준 경우 진단 정보 노출
      return new Response(JSON.stringify({ error: "vworld non-json", upstreamStatus: r.status, body: txt.slice(0, 160) }),
        { status: 502, headers: cors });
    }

    const res = (d.response && d.response.result) || [];
    const parcel = (res.find(x => x.type === "parcel") || {}).text || "";
    const road = (res.find(x => x.type === "road") || {}).text || "";
    const status = (d.response && d.response.status) || "";
    return new Response(JSON.stringify({ parcel, road, status }), { headers: cors });
  },
};
