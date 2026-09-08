/** tour.crowdbase.kr -> GitHub Pages의 투어 전용 산출물 프록시. */
const SOURCE = "https://canoe.crowdbase.kr";

export default {
  async fetch(request) {
    const incoming = new URL(request.url);
    const path = incoming.pathname === "/" || incoming.pathname === "/index.html"
      ? "/tour/index.html"
      : incoming.pathname;
    const upstream = new URL(path + incoming.search, SOURCE);
    const response = await fetch(new Request(upstream, request));
    const headers = new Headers(response.headers);
    headers.set("Cache-Control", path === "/tour/index.html" ? "public, max-age=60" : "public, max-age=600");
    headers.set("X-Mycanoe-Site", "tour");
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  },
};
