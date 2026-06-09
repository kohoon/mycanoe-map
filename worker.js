/**
 * Cloudflare Worker — V-World 역지오코딩 프록시
 * 카카오/네이버 없이 지번 주소를 주되, V-World 키를 클라이언트에 노출하지 않기 위한 중계.
 *
 * 배포:
 *  1) https://dash.cloudflare.com → Workers & Pages → Create Worker
 *  2) 이 코드를 붙여넣고 Deploy
 *  3) Settings → Variables → Secret 추가: 이름 VWORLD_KEY, 값 = 발급키
 *  4) 워커 URL(예: https://canoe-geo.<계정>.workers.dev)을 지도에 연결
 *
 * 사용: GET https://<worker>/?lat=37.083&lng=128.492  →  {"parcel":"충청북도 단양군 영춘면 상리 702","road":"..."}
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
      + "&crs=EPSG:4326&type=both&format=json&point=" + lng + "," + lat
      + "&key=" + env.VWORLD_KEY + "&domain=http://localhost";
    try {
      const r = await fetch(api, { cf: { cacheTtl: 86400 } });
      const d = await r.json();
      const res = (d.response && d.response.result) || [];
      const parcel = (res.find(x => x.type === "parcel") || {}).text || "";
      const road = (res.find(x => x.type === "road") || {}).text || "";
      return new Response(JSON.stringify({ parcel, road }), { headers: cors });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e) }), { status: 502, headers: cors });
    }
  },
};
