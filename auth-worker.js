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
function _hav(a, b) {
  const R = 6371000, toR = Math.PI / 180;
  const dla = (b[0] - a[0]) * toR, dlo = (b[1] - a[1]) * toR, la1 = a[0] * toR, la2 = b[0] * toR;
  const h = Math.sin(dla / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dlo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function _trackKm(t) { let d = 0; for (let i = 1; i < t.length; i++) d += _hav(t[i - 1], t[i]); return d / 1000; }

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
          body: JSON.stringify({ id: b.id || "", nick: b.nick || "", type: b.type || "visit", dev: b.dev || "" }),
        }).catch(() => {}));
      }
      return new Response("ok", { headers: cors });
    }

    // 0-1b) 관리자 키 검증(백도어). 키는 Cloudflare Secret(env.ADMIN_KEY)에만 존재
    if (url.pathname.endsWith("/admincheck")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      let b = {}; try { b = await req.json(); } catch (e) {}
      const ok = !!env.ADMIN_KEY && String(b.key) === String(env.ADMIN_KEY);
      return new Response(JSON.stringify({ ok: ok }), { headers: { ...cors, "Content-Type": "application/json" } });
    }

    // 0-2) 등록 장소 저장/조회 (Cloudflare KV: env.PLACES, 어드민: env.ADMIN_KEY)
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
        if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY))
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

    // 0-3) 장소별 코멘트 (관리자 코멘트 + 사용자 코멘트). KV key = "cmt:<slug>"
    if (url.pathname.endsWith("/comments")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const EMPTY = '{"admin":"","list":[]}';
      if (req.method === "GET") {
        const slug = (url.searchParams.get("place") || "").slice(0, 40);
        const data = KV && slug ? await KV.get("cmt:" + slug) : null;
        return new Response(data || EMPTY, { headers: { ...cors, "Content-Type": "application/json" } });
      }
      if (req.method === "POST") {
        let b = {};
        try { b = await req.json(); } catch (e) {}
        if (b.action === "export") {   // 어드민: 기존 KV 코멘트 전체를 시트로 백필
          if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
          if (!KV || !env.LOG_WEBHOOK) return new Response("no-store", { status: 500, headers: cors });
          let cursor, n = 0;
          let sent = {}; try { sent = JSON.parse((await KV.get("cmt_exported")) || "{}"); } catch (e) {}   // 이미 보낸 것
          do {
            const lst = await KV.list({ prefix: "cmt:", cursor });
            for (const k of lst.keys) {
              let o = {}; try { o = JSON.parse((await KV.get(k.name)) || "{}"); } catch (e) {}
              const place = o.name || k.name.slice(4);
              if (o.admin) {   // 관리자 코멘트
                const sig = k.name + "#admin#" + o.admin;
                if (!sent[sig]) {
                  await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ type: "comment", place: String(place).slice(0, 60), nick: "📌관리자", text: o.admin }) }).catch(function () {});
                  sent[sig] = 1; n++;
                }
              }
              for (const c of (o.list || [])) {
                const sig = k.name + "#" + (c.t || "") + "#" + (c.text || "");
                if (!sent[sig]) {
                  await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ type: "comment", place: String(place).slice(0, 60), nick: c.nick || "", text: c.text || "" }) }).catch(function () {});
                  sent[sig] = 1; n++;
                }
              }
            }
            cursor = lst.list_complete ? null : lst.cursor;
          } while (cursor);
          await KV.put("cmt_exported", JSON.stringify(sent));
          return new Response(JSON.stringify({ ok: true, exported: n }), { headers: { ...cors, "Content-Type": "application/json" } });
        }
        const slug = String(b.place || "").slice(0, 40);
        if (!slug) return new Response("bad", { status: 400, headers: cors });
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        let obj = { admin: "", list: [] };
        try { obj = JSON.parse((await KV.get("cmt:" + slug)) || EMPTY); } catch (e) {}
        if (b.admin) {
          if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
          obj.admin = String(b.text || "").slice(0, 300);
          // 관리자 코멘트도 시트에 기록(중복 방지)
          if (env.LOG_WEBHOOK && obj.admin) {
            const sig = "cmt:" + slug + "#admin#" + obj.admin, pl = String(b.name || slug).slice(0, 60), txt = obj.admin;
            ctx.waitUntil((async () => { try {
              let sent = {}; try { sent = JSON.parse((await KV.get("cmt_exported")) || "{}"); } catch (e) {}
              if (sent[sig]) return;
              await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ type: "comment", place: pl, nick: "📌관리자", text: txt }) }).catch(function () {});
              sent[sig] = 1; await KV.put("cmt_exported", JSON.stringify(sent));
            } catch (e) {} })());
          }
        } else {
          if (!b.id) return new Response("forbidden", { status: 403, headers: cors });
          const text = String(b.text || "").trim().slice(0, 100);
          if (!text) return new Response("bad", { status: 400, headers: cors });
          const cnick = String(b.nick || "익명").slice(0, 20);
          if (b.name) obj.name = String(b.name).slice(0, 60);   // 장소명 저장(백필/표시용)
          let cseq = 0; try { cseq = parseInt((await KV.get("cmt_seq")) || "0", 10) || 0; } catch (e) {}
          cseq++; await KV.put("cmt_seq", String(cseq));   // 코멘트 전역 ID
          const ct = Date.now();
          obj.list.push({ id: cseq, nick: cnick, text: text, t: ct });
          if (obj.list.length > 500) obj.list = obj.list.slice(-500);
          // 새 코멘트 → 시트(중복 방지)
          if (env.LOG_WEBHOOK) {
            const sig = "cmt:" + slug + "#" + ct + "#" + text, pl = String(b.name || slug).slice(0, 60);
            ctx.waitUntil((async () => { try {
              let sent = {}; try { sent = JSON.parse((await KV.get("cmt_exported")) || "{}"); } catch (e) {}
              if (sent[sig]) return;
              await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ type: "comment", cid: cseq, place: pl, nick: cnick, text: text }) }).catch(function () {});
              sent[sig] = 1; await KV.put("cmt_exported", JSON.stringify(sent));
            } catch (e) {} })());
          }
        }
        await KV.put("cmt:" + slug, JSON.stringify(obj));
        return new Response("ok", { headers: cors });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3b) 일반 사용자 장소 제안 → Google Sheet(suggestions 탭)
    if (url.pathname.endsWith("/suggest")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      if (req.method === "POST") {
        let b = {};
        try { b = await req.json(); } catch (e) {}
        if (!b.id) return new Response("forbidden", { status: 403, headers: cors });
        if (env.LOG_WEBHOOK) ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "suggest", cat: String(b.cat || "기타").slice(0, 10),
            place: String(b.addr || "").slice(0, 80), nick: String(b.nick || "").slice(0, 20),
            text: String(b.text || "").slice(0, 200), lat: Number(b.lat) || "", lng: Number(b.lng) || "",
          }),
        }).catch(function () {}));
        return new Response("ok", { headers: cors });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3c) 공지사항 게시판 (관리자 글 + 사용자 답글). KV "notices"
    if (url.pathname.endsWith("/notices")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
      if (req.method === "GET") { const d = KV ? await KV.get("notices") : null; return J(d || "[]"); }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        let arr = []; try { arr = JSON.parse((await KV.get("notices")) || "[]"); } catch (e) {}
        const action = b.action || "";
        if (action === "post" || action === "delete" || action === "edit") {
          if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
          if (action === "post") {
            arr.unshift({ id: Date.now(), title: String(b.title || "").slice(0, 80), body: String(b.body || "").slice(0, 2000), t: Date.now(), replies: [] });
            if (arr.length > 200) arr = arr.slice(0, 200);
          } else if (action === "edit") {
            const nt = arr.find((x) => String(x.id) === String(b.noticeId));
            if (!nt) return new Response("bad", { status: 400, headers: cors });
            nt.title = String(b.title || "").slice(0, 80);
            nt.body = String(b.body || "").slice(0, 2000);
            nt.edited = Date.now();
          } else {
            arr = arr.filter((x) => String(x.id) !== String(b.noticeId));
          }
        } else if (action === "reply") {
          if (!b.id) return new Response("forbidden", { status: 403, headers: cors });
          const nt = arr.find((x) => String(x.id) === String(b.noticeId));
          if (!nt) return new Response("bad", { status: 400, headers: cors });
          const text = String(b.text || "").trim().slice(0, 300);
          if (!text) return new Response("bad", { status: 400, headers: cors });
          nt.replies = nt.replies || [];
          nt.replies.push({ nick: String(b.nick || "익명").slice(0, 20), text: text, t: Date.now() });
        } else return new Response("action", { status: 400, headers: cors });
        await KV.put("notices", JSON.stringify(arr));
        return J(JSON.stringify({ ok: true }));
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-4) 카누잉 트립 기록 (KV: trip:<id>, utrips:<uid>, feed, board)
    {
      const tp = url.pathname;
      if (tp.endsWith("/trips") || tp.endsWith("/trip") || tp.endsWith("/feed") || tp.endsWith("/board")) {
        const origin = req.headers.get("Origin") || "*";
        const cors = {
          "Access-Control-Allow-Origin": origin,
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        };
        if (req.method === "OPTIONS") return new Response(null, { headers: cors });
        const KV = env.PLACES;
        const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
        const TXT = (s, st) => new Response(s, { status: st || 200, headers: cors });

        if (tp.endsWith("/trips")) {            // 내 트립 목록
          const uid = url.searchParams.get("uid") || "";
          const data = KV && uid ? await KV.get("utrips:" + uid) : null;
          return J(data || "[]");
        }
        if (tp.endsWith("/feed")) {             // 공유 트립 목록
          const data = KV ? await KV.get("feed") : null;
          return J(data || "[]");
        }
        if (tp.endsWith("/board")) {            // 랭킹(총거리)
          let obj = {};
          try { obj = JSON.parse((KV ? await KV.get("board") : null) || "{}"); } catch (e) {}
          const arr = Object.keys(obj).map((k) => ({ uid: k, nick: obj[k].nick, totalKm: obj[k].totalKm, trips: obj[k].trips }))
            .sort((a, b) => b.totalKm - a.totalKm).slice(0, 50);
          return J(JSON.stringify(arr));
        }
        // /trip
        if (req.method === "GET") {             // 트립 1건(공유이거나 소유자/관리자)
          const id = url.searchParams.get("id") || "", viewer = url.searchParams.get("viewer") || "";
          const t = KV ? await KV.get("trip:" + id) : null;
          if (!t) return TXT("not found", 404);
          const trip = JSON.parse(t);
          if (!trip.shared && String(viewer) !== String(trip.uid))
            return TXT("forbidden", 403);
          return J(t);
        }
        if (req.method === "POST") {
          let b = {};
          try { b = await req.json(); } catch (e) {}
          const action = b.action || "save";
          if (!b.id) return TXT("forbidden", 403);
          if (!KV) return TXT("no-store", 500);

          if (action === "save") {
            let track = Array.isArray(b.track) ? b.track.slice(0, 5000) : [];
            if (track.length < 2) return TXT("bad", 400);
            const distKm = Math.round(_trackKm(track) * 100) / 100;
            const id = String(b.id) + "_" + Date.now();
            const trip = {
              id, uid: String(b.id), nick: String(b.nick || "").slice(0, 20),
              title: String(b.title || "카누잉").slice(0, 40),
              start: Number(b.start) || 0, end: Number(b.end) || 0, durSec: Number(b.durSec) || 0,
              distKm, track, launch: b.launch || null, landing: b.landing || null,
              shared: !!b.shared, ct: Date.now(),
            };
            await KV.put("trip:" + id, JSON.stringify(trip));
            const sum = { id, title: trip.title, start: trip.start, distKm, durSec: trip.durSec, shared: trip.shared };
            let ut = []; try { ut = JSON.parse((await KV.get("utrips:" + trip.uid)) || "[]"); } catch (e) {}
            ut.unshift(sum); if (ut.length > 500) ut = ut.slice(0, 500);
            await KV.put("utrips:" + trip.uid, JSON.stringify(ut));
            let bd = {}; try { bd = JSON.parse((await KV.get("board")) || "{}"); } catch (e) {}
            const en = bd[trip.uid] || { nick: trip.nick, totalKm: 0, trips: 0 };
            en.nick = trip.nick || en.nick; en.totalKm = Math.round((en.totalKm + distKm) * 100) / 100; en.trips++;
            bd[trip.uid] = en; await KV.put("board", JSON.stringify(bd));
            if (trip.shared) {
              let feed = []; try { feed = JSON.parse((await KV.get("feed")) || "[]"); } catch (e) {}
              feed.unshift({ id, uid: trip.uid, nick: trip.nick, title: trip.title, distKm, start: trip.start });
              if (feed.length > 500) feed = feed.slice(0, 500);
              await KV.put("feed", JSON.stringify(feed));
            }
            return J(JSON.stringify({ ok: true, id, distKm }));
          }
          if (action === "share") {
            const id = String(b.tripId || "");
            const t = await KV.get("trip:" + id); if (!t) return TXT("bad", 400);
            const trip = JSON.parse(t);
            if (String(trip.uid) !== String(b.id)) return TXT("forbidden", 403);
            trip.shared = !!b.shared; await KV.put("trip:" + id, JSON.stringify(trip));
            let ut = []; try { ut = JSON.parse((await KV.get("utrips:" + trip.uid)) || "[]"); } catch (e) {}
            ut = ut.map((x) => (x.id === id ? { ...x, shared: trip.shared } : x));
            await KV.put("utrips:" + trip.uid, JSON.stringify(ut));
            let feed = []; try { feed = JSON.parse((await KV.get("feed")) || "[]"); } catch (e) {}
            feed = feed.filter((x) => x.id !== id);
            if (trip.shared) feed.unshift({ id, uid: trip.uid, nick: trip.nick, title: trip.title, distKm: trip.distKm, start: trip.start });
            if (feed.length > 500) feed = feed.slice(0, 500);
            await KV.put("feed", JSON.stringify(feed));
            return J(JSON.stringify({ ok: true, shared: trip.shared }));
          }
          if (action === "delete") {
            const id = String(b.tripId || "");
            const t = await KV.get("trip:" + id); if (!t) return TXT("bad", 400);
            const trip = JSON.parse(t);
            const isOwner = String(trip.uid) === String(b.id), isAdmin = !!env.ADMIN_KEY && String(b.adminKey) === String(env.ADMIN_KEY);
            if (!isOwner && !isAdmin) return TXT("forbidden", 403);
            await KV.delete("trip:" + id);
            let ut = []; try { ut = JSON.parse((await KV.get("utrips:" + trip.uid)) || "[]"); } catch (e) {}
            await KV.put("utrips:" + trip.uid, JSON.stringify(ut.filter((x) => x.id !== id)));
            let feed = []; try { feed = JSON.parse((await KV.get("feed")) || "[]"); } catch (e) {}
            await KV.put("feed", JSON.stringify(feed.filter((x) => x.id !== id)));
            let bd = {}; try { bd = JSON.parse((await KV.get("board")) || "{}"); } catch (e) {}
            if (bd[trip.uid]) {
              bd[trip.uid].totalKm = Math.max(0, Math.round((bd[trip.uid].totalKm - trip.distKm) * 100) / 100);
              bd[trip.uid].trips = Math.max(0, bd[trip.uid].trips - 1);
              await KV.put("board", JSON.stringify(bd));
            }
            return J(JSON.stringify({ ok: true }));
          }
          return TXT("action", 400);
        }
        return TXT("method", 405);
      }
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
      const _ua = req.headers.get("User-Agent") || "";
      const _dev = /mobile|android|iphone|ipad|ipod/i.test(_ua) ? "모바일" : "PC";
      ctx.waitUntil(
        fetch(env.LOG_WEBHOOK, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: id, nick: nick, type: "login", dev: _dev }),
        }).catch(() => {})
      );
    }

    const site = env.SITE_URL || "https://kohoon.github.io/mycanoe-map/";
    const back = site + "#login=" + encodeURIComponent(id) + "&nick=" + encodeURIComponent(nick);
    return Response.redirect(back, 302);
  },
};
