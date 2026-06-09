/**
 * Cloudflare Worker — 카카오 로그인 OAuth 콜백.
 * 정적 사이트는 토큰 교환을 직접 못 하므로 이 Worker가 대신 처리한다.
 *
 * 동작:
 *   1) 사용자가 Worker URL 로 들어오면 → 카카오 인증 페이지로 리다이렉트
 *   2) 카카오가 ?code= 로 다시 Worker 로 보내면 → 토큰 교환 → 사용자 정보 조회
 *   3) 지도(SITE_URL)로 #login=카카오ID&nick=닉네임 붙여 리다이렉트
 *
 * 배포(대시보드): Workers & Pages → Create → 이 코드 붙여넣기 → Deploy
 * Settings → Variables and Secrets 에 추가:
 *   - Secret  KAKAO_REST_KEY      (카카오 앱 REST API 키)
 *   - Secret  KAKAO_CLIENT_SECRET (카카오 로그인 보안 client_secret; 안 쓰면 생략)
 *   - Variable SITE_URL           (예: https://kohoon.github.io/mycanoe-map/)
 * 카카오 개발자센터 Redirect URI 에 "이 Worker 의 URL" 을 등록.
 */
export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const REDIRECT = url.origin + url.pathname;   // = 카카오에 등록할 Redirect URI
    const code = url.searchParams.get("code");

    // 0) 활동 로그(자동로그인 재접속 등) → 브라우저가 호출, Worker가 Sheet 로 전달
    if (url.pathname.endsWith("/log")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      if (req.method === "POST" && env.LOG_WEBHOOK) {
        let b = {};
        try { b = await req.json(); } catch (e) {}
        ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: b.id || "", nick: b.nick || "", type: b.type || "visit" }),
        }).catch(() => {}));
      }
      return new Response("ok", { headers: cors });
    }

    // 0-2) 등록 장소 저장/조회 (Cloudflare KV: env.PLACES, 어드민: env.ADMIN_ID)
    if (url.pathname.endsWith("/places")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      if (req.method === "GET") {
        const data = KV ? await KV.get("places") : null;
        return new Response(data || "[]", { headers: { ...cors, "Content-Type": "application/json" } });
      }
      if (req.method === "POST") {
        let b = {};
        try { b = await req.json(); } catch (e) {}
        if (!env.ADMIN_ID || String(b.id) !== String(env.ADMIN_ID))
          return new Response("forbidden", { status: 403, headers: cors });
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        const lat = Number(b.lat), lng = Number(b.lng);
        const name = String(b.name || "").slice(0, 60);
        const cat = b.cat === "명소" ? "명소" : "런칭랜딩";
        if (!name || !isFinite(lat) || !isFinite(lng))
          return new Response("bad", { status: 400, headers: cors });
        let arr = [];
        try { arr = JSON.parse((await KV.get("places")) || "[]"); } catch (e) {}
        arr.push({ name, cat, lat, lng, by: String(b.nick || ""), t: Date.now() });
        await KV.put("places", JSON.stringify(arr));
        return new Response("ok", { headers: cors });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 1) 로그인 시작
    if (!code) {
      const auth = "https://kauth.kakao.com/oauth/authorize?response_type=code"
        + "&client_id=" + env.KAKAO_REST_KEY
        + "&redirect_uri=" + encodeURIComponent(REDIRECT);
      return Response.redirect(auth, 302);
    }

    // 2) code → access_token
    const form = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: env.KAKAO_REST_KEY,
      redirect_uri: REDIRECT,
      code,
    });
    if (env.KAKAO_CLIENT_SECRET) form.set("client_secret", env.KAKAO_CLIENT_SECRET);
    const tokRes = await fetch("https://kauth.kakao.com/oauth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=utf-8" },
      body: form,
    });
    const tok = await tokRes.json();
    if (!tok.access_token) {
      return new Response("login failed: " + JSON.stringify(tok), { status: 400 });
    }

    // 3) 사용자 정보
    const meRes = await fetch("https://kapi.kakao.com/v2/user/me", {
      headers: { Authorization: "Bearer " + tok.access_token },
    });
    const me = await meRes.json();
    const id = String(me.id || "");
    const nick =
      (me.kakao_account && me.kakao_account.profile && me.kakao_account.profile.nickname) ||
      (me.properties && me.properties.nickname) || "";

    // 로그인 기록 → Google Sheet(Apps Script 웹앱). LOG_WEBHOOK 은 대시보드 Secret 으로 설정.
    if (env.LOG_WEBHOOK) {
      ctx.waitUntil(
        fetch(env.LOG_WEBHOOK, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: id, nick: nick, type: "login" }),
        }).catch(() => {})
      );
    }

    const site = env.SITE_URL || "https://kohoon.github.io/mycanoe-map/";
    const back = site + "#login=" + encodeURIComponent(id) + "&nick=" + encodeURIComponent(nick);
    return Response.redirect(back, 302);
  },
};
