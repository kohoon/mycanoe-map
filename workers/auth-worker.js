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

// ---- 신원 서명 토큰(HMAC) — 클라이언트 자기신고 uid 스푸핑 방지 ----
// 로그인 콜백에서 발급(#login=...&tok=...) → 쓰기 API가 검증. 비밀키는 ADMIN_KEY 재사용(서버 전용).
async function _hmacHex(msg, secret) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(String(secret)),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(String(msg)));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function _tokFor(env, uid) {
  if (!env.ADMIN_KEY) return "";
  return (await _hmacHex("mc1|" + uid, env.ADMIN_KEY)).slice(0, 32);
}
async function _tokOk(env, uid, tok) {
  if (!env.ADMIN_KEY) return true;     // 키 미설정(개발) 시 통과
  if (!uid || !tok) return false;
  return (await _tokFor(env, uid)) === String(tok);
}
async function _uidHash(env, uid) {    // 공개 응답용 가명(원 uid 비노출)
  return (await _hmacHex("uh|" + uid, env.ADMIN_KEY || "x")).slice(0, 10);
}
// 허용 Origin(우리 사이트)만 — 비브라우저 클라이언트는 Origin 위조 가능하나 캐주얼 남용 차단
function _allowedOrigin(req, env) {
  const o = req.headers.get("Origin") || "";
  if (!o) return true;   // 동일 출처/비-CORS(이미지 src 등) 허용
  const site = (env.SITE_URL || "https://kohoon.github.io/").replace(/\/$/, "");
  try { const oh = new URL(o).host; return oh === new URL(site).host || oh === "localhost" || oh.startsWith("localhost:") || oh === "127.0.0.1"; }
  catch (e) { return false; }
}
// 단순 속도 제한(KV 카운터, 분 단위) — true면 차단
async function _rateLimited(env, bucket, ip, max) {
  const KV = env.PLACES; if (!KV) return false;
  const minute = Math.floor(Date.now() / 60000);
  const k = "rl_" + bucket + "_" + ip + "_" + minute;
  let n = 0; try { n = parseInt((await KV.get(k)) || "0", 10) || 0; } catch (e) {}
  if (n >= max) return true;
  await KV.put(k, String(n + 1), { expirationTtl: 120 });
  return false;
}
async function _cacheJson(ctx, key, build, ttl = 60) {
  const cache = caches.default;
  const ck = new Request(key, { method: "GET" });
  const hit = await cache.match(ck);
  if (hit) return hit;
  const resp = await build();
  if (resp && resp.status === 200) ctx.waitUntil(cache.put(ck, resp.clone()));
  return resp;
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const REDIRECT = url.origin + url.pathname;   // = 카카오에 등록할 Redirect URI
    const code = url.searchParams.get("code");
    const back = (() => {
      const raw = url.searchParams.get("back") || url.searchParams.get("state") || "";
      if (!raw) return "";
      try {
        const u = new URL(raw, env.SITE_URL || "https://kohoon.github.io/mycanoe-map/");
        const site = new URL(env.SITE_URL || "https://kohoon.github.io/mycanoe-map/");
        const isLocal = (u.protocol === "http:" || u.protocol === "https:") && (u.hostname === "localhost" || u.hostname === "127.0.0.1");
        if (isLocal) return u.origin + u.pathname + u.search;
        if (u.origin !== site.origin) return "";
        return u.origin + u.pathname + u.search;
      } catch (e) {
        return "";
      }
    })();

    // B: 쓰기성 POST는 우리 사이트 Origin에서만(타 사이트 브라우저 JS 차단). Origin 없으면 통과(이미지/툴).
    if (req.method === "POST" && !_allowedOrigin(req, env)) {
      return new Response("forbidden-origin", { status: 403, headers: { "Access-Control-Allow-Origin": req.headers.get("Origin") || "*" } });
    }

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
        // A: 진짜 카카오 id(숫자) + 유효 서명토큰만 기록 — 봇/가짜 id 차단
        const idOk = /^[0-9]+$/.test(String(b.id || ""));
        if (idOk && (await _tokOk(env, String(b.id), b.tok)) && _allowedOrigin(req, env)) {
          ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: b.id || "", nick: b.nick || "", type: b.type || "visit", dev: b.dev || "" }),
          }).catch(() => {}));
        }
      }
      return new Response("ok", { headers: cors });   // 항상 ok(공격자에게 정보 비노출)
    }

    // 0-1b) 관리자 키 검증(백도어). 키는 Cloudflare Secret(env.ADMIN_KEY)에만 존재
    if (url.pathname.endsWith("/admincheck")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      // C: 무차별 대입 방어 — IP당 분 10회 제한 + 실패 지연
      const ip = req.headers.get("CF-Connecting-IP") || "0";
      if (await _rateLimited(env, "adm", ip, 10)) return new Response(JSON.stringify({ ok: false, rl: true }), { status: 429, headers: { ...cors, "Content-Type": "application/json" } });
      let b = {}; try { b = await req.json(); } catch (e) {}
      const ok = !!env.ADMIN_KEY && String(b.key) === String(env.ADMIN_KEY);
      if (!ok) await new Promise((r) => setTimeout(r, 600));   // 타이밍/속도 둔화
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
        return _cacheJson(ctx, url.toString(), async () => {
          const data = KV ? await KV.get("places") : null;
          return new Response(data || "[]", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
        }, 60);
      }
      if (req.method === "POST") {
        let b = {};
        try { b = await req.json(); } catch (e) {}
        if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY))
          return new Response("forbidden", { status: 403, headers: cors });
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        const lat = Number(b.lat), lng = Number(b.lng);
        const name = String(b.name || "").slice(0, 60);
        const cat = (b.cat === "명소" || b.cat === "spot") ? "명소" : (b.cat === "candidate" ? "candidate" : "런칭랜딩");
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
        return _cacheJson(ctx, url.toString(), async () => {
          const data = KV && slug ? await KV.get("cmt:" + slug) : null;
          return new Response(data || EMPTY, { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
        }, 60);
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
                  const imgU = c.img ? (url.origin + "/img?k=" + c.img) : "";
                  await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ type: "comment", cid: c.id || "", place: String(place).slice(0, 60), nick: c.nick || "", text: c.text || "", stars: c.stars || "", img: imgU }) }).catch(function () {});
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
        if (b.action === "cmtdel" || b.action === "cmtedit") {   // 어드민: 코멘트 삭제/수정
          if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
          const cid = Number(b.cid);
          if (b.action === "cmtdel") {
            const victim = (obj.list || []).find((c) => c.id === cid);
            if (victim && victim.img) ctx.waitUntil(KV.delete("img:" + victim.img));   // 첨부 사진도 삭제
            obj.list = (obj.list || []).filter((c) => c.id !== cid);
          } else {
            const it = (obj.list || []).find((c) => c.id === cid);
            if (it) it.text = String(b.text || "").slice(0, 100);
          }
          await KV.put("cmt:" + slug, JSON.stringify(obj));
          return new Response(JSON.stringify({ ok: true }), { headers: { ...cors, "Content-Type": "application/json" } });
        }
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
          if (!(await _tokOk(env, String(b.id), b.tok))) return new Response("relogin", { status: 401, headers: cors });
          const text = String(b.text || "").trim().slice(0, 100);
          const imgKey = String(b.img || "").replace(/[^a-zA-Z0-9_]/g, "").slice(0, 40);
          if (!text && !imgKey) return new Response("bad", { status: 400, headers: cors });
          const cnick = String(b.nick || "익명").slice(0, 20);
          if (b.name) obj.name = String(b.name).slice(0, 60);   // 장소명 저장(백필/표시용)
          let cseq = 0; try { cseq = parseInt((await KV.get("cmt_seq")) || "0", 10) || 0; } catch (e) {}
          cseq++; await KV.put("cmt_seq", String(cseq));   // 코멘트 전역 ID
          const ct = Date.now();
          const stars = Math.round(Number(b.stars));
          const item = { id: cseq, nick: cnick, text: text, t: ct };
          if (stars >= 1 && stars <= 5) item.stars = stars;
          if (imgKey) item.img = imgKey;
          obj.list.push(item);
          if (obj.list.length > 500) obj.list = obj.list.slice(-500);
          if (stars >= 1 && stars <= 5) {   // 별점도 함께 반영(평균용 rate_<slug>)
            const rk = "rate_" + slug;
            let rm = {}; try { rm = JSON.parse((await KV.get(rk)) || "{}"); } catch (e) {}
            rm[String(b.id)] = stars; await KV.put(rk, JSON.stringify(rm));
          }
          // 새 코멘트 → 시트(중복 방지)
          if (env.LOG_WEBHOOK) {
            const sig = "cmt:" + slug + "#" + ct + "#" + text, pl = String(b.name || slug).slice(0, 60);
            ctx.waitUntil((async () => { try {
              let sent = {}; try { sent = JSON.parse((await KV.get("cmt_exported")) || "{}"); } catch (e) {}
              if (sent[sig]) return;
              const imgU = imgKey ? (url.origin + "/img?k=" + imgKey) : "";
              await fetch(env.LOG_WEBHOOK, { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ type: "comment", cid: cseq, place: pl, nick: cnick, text: text, stars: (stars >= 1 && stars <= 5) ? stars : "", img: imgU }) }).catch(function () {});
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
    // 0-2e) 장소 카테고리 오버라이드(관리자) — KV "placecat" = {placeId: 'spot'|'canoe'|'candidate'}
    if (url.pathname.endsWith("/placecat")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
      if (req.method === "GET") { return _cacheJson(ctx, url.toString(), async () => {
        const d = KV ? await KV.get("placecat") : null;
        return new Response(d || "{}", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
      }, 60); }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        let m = {}; try { m = JSON.parse((await KV.get("placecat")) || "{}"); } catch (e) {}
        const id = String(b.id || "").slice(0, 20);
        if (!id) return new Response("bad", { status: 400, headers: cors });
        const cat = (b.cat === "spot" || b.cat === "canoe" || b.cat === "candidate") ? b.cat : null;
        if (cat) m[id] = cat; else delete m[id];   // null = 기본 분류 복원
        await KV.put("placecat", JSON.stringify(m));
        return J(JSON.stringify({ ok: true }));
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-2f) 통합 장소 오버라이드(관리자) — KV "placeover" = {id: {name?,memo?,cat?,del?,new?,lat?,lng?}}
    // 임베드 점 수정/삭제/분류 + 앱 신규 등록을 id 하나로 통합 관리(D1 호환: id=행). 원본 비파괴.
    if (url.pathname.endsWith("/placeover")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
      if (req.method === "GET") { return _cacheJson(ctx, url.toString(), async () => {
        const d = KV ? await KV.get("placeover") : null;
        return new Response(d || "{}", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
      }, 60); }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        let m = {}; try { m = JSON.parse((await KV.get("placeover")) || "{}"); } catch (e) {}
        const id = String(b.id || "").slice(0, 40);
        if (!id) return new Response("bad", { status: 400, headers: cors });
        if (b.clear) { delete m[id]; }   // 오버라이드 완전 해제(원복)
        else {
          const cur = m[id] || {};
          if (b.name != null) cur.name = String(b.name).slice(0, 60);
          if (b.memo != null) cur.memo = String(b.memo).slice(0, 500);
          if (b.cat != null) { const c = (b.cat === "spot" || b.cat === "canoe" || b.cat === "candidate") ? b.cat : null; if (c) cur.cat = c; }
          if (b.del != null) cur.del = b.del ? 1 : 0;
          if (b.new) cur.new = 1;
          if (b.lat != null && isFinite(Number(b.lat))) cur.lat = Number(b.lat);
          if (b.lng != null && isFinite(Number(b.lng))) cur.lng = Number(b.lng);
          m[id] = cur;
        }
        await KV.put("placeover", JSON.stringify(m));
        // 위치 이동 시 좌표 slug 기반 데이터 이관: 코멘트·평점·즐겨찾기(전 사용자)
        const mvFrom = String(b.mvFrom || "").slice(0, 40), mvTo = String(b.mvTo || "").slice(0, 40);
        if (mvFrom && mvTo && mvFrom !== mvTo) {
          // 코멘트 cmt:<slug> (대상 있으면 병합)
          const cFrom = await KV.get("cmt:" + mvFrom);
          if (cFrom) {
            const cTo = await KV.get("cmt:" + mvTo);
            if (!cTo) { await KV.put("cmt:" + mvTo, cFrom); }
            else { let a = {}, bb = {}; try { a = JSON.parse(cTo); } catch (e) {} try { bb = JSON.parse(cFrom); } catch (e) {}
              a.list = (a.list || []).concat(bb.list || []); if (!a.admin && bb.admin) a.admin = bb.admin;
              await KV.put("cmt:" + mvTo, JSON.stringify(a)); }
            await KV.delete("cmt:" + mvFrom);
          }
          // 평점 rate_<slug> (uid→stars 병합)
          const rFrom = await KV.get("rate_" + mvFrom);
          if (rFrom) { let rm = {}, rt = {}; try { rm = JSON.parse(rFrom); } catch (e) {}
            const rTo = await KV.get("rate_" + mvTo); try { rt = rTo ? JSON.parse(rTo) : {}; } catch (e) {}
            Object.assign(rt, rm); await KV.put("rate_" + mvTo, JSON.stringify(rt)); await KV.delete("rate_" + mvFrom); }
          // 즐겨찾기 favs_<uid> 전체 스캔 — 항목 t===mvFrom 을 mvTo+새좌표로 갱신
          const nlat = (b.lat != null) ? Number(b.lat) : null, nlng = (b.lng != null) ? Number(b.lng) : null;
          let cursor;
          do {
            const lst = await KV.list({ prefix: "favs_", cursor });
            for (const ky of lst.keys) {
              let arr = []; try { arr = JSON.parse((await KV.get(ky.name)) || "[]"); } catch (e) {}
              let ch = false;
              arr = arr.map((x) => { if (x && x.t === mvFrom) { ch = true; return { ...x, t: mvTo, lat: nlat != null ? nlat : x.lat, lng: nlng != null ? nlng : x.lng }; } return x; });
              if (ch) await KV.put(ky.name, JSON.stringify(arr));
            }
            cursor = lst.list_complete ? null : lst.cursor;
          } while (cursor);
        }
        return J(JSON.stringify({ ok: true }));
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-1d) 수집 결과 보고 → 시트(LOG_WEBHOOK, type:collect). ADMIN_KEY 필수.
    if (url.pathname.endsWith("/report")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      let b = {}; try { b = await req.json(); } catch (e) {}
      if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
      if (env.LOG_WEBHOOK) ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "collect", status: String(b.status || "").slice(0, 40), added: Number(b.added) || 0, detail: String(b.detail || "").slice(0, 500) }),
      }).catch(() => {}));
      return new Response(JSON.stringify({ ok: true }), { headers: { ...cors, "Content-Type": "application/json" } });
    }

    // 0-1c) 관리자 정리 — 테스트/잔재 데이터 조회·삭제. ADMIN_KEY 필수.
    if (url.pathname.endsWith("/cleanup")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      let b = {}; try { b = await req.json(); } catch (e) {}
      if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
      const KV = env.PLACES; if (!KV) return new Response("no-store", { status: 500, headers: cors });
      const J = (o) => new Response(JSON.stringify(o), { headers: { ...cors, "Content-Type": "application/json" } });
      const isNumeric = (s) => /^[0-9]+$/.test(String(s));   // 진짜 카카오 id = 숫자
      const report = { board: [], favs: [], rate: [], utrips: [], trips: [] };
      // board: 비숫자 uid 항목
      let bd = {}; try { bd = JSON.parse((await KV.get("board")) || "{}"); } catch (e) {}
      for (const k of Object.keys(bd)) if (!isNumeric(k)) report.board.push(k);
      // favs_/utrips_/trip: 키 스캔
      let cursor;
      do {
        const lst = await KV.list({ cursor });
        for (const it of lst.keys) {
          const n = it.name;
          if (n.startsWith("favs_") && !isNumeric(n.slice(5))) report.favs.push(n);
          else if (n.startsWith("utrips:") && !isNumeric(n.slice(7))) report.utrips.push(n);
          else if (n.startsWith("trip:") && !isNumeric(n.slice(5).split("_")[0])) report.trips.push(n);
          else if (n.startsWith("rate_")) {   // rate: 비숫자 uid 표 제거 또는 빈 표
            try { const rm = JSON.parse((await KV.get(n)) || "{}");
              const bad = Object.keys(rm).filter((u) => !isNumeric(u));
              if (bad.length) report.rate.push({ k: n, bad });
            } catch (e) {}
          }
        }
        cursor = lst.list_complete ? null : lst.cursor;
      } while (cursor);

      if (b.dry) return J({ dry: true, report });   // 미리보기

      // 실제 삭제
      let removed = 0;
      for (const k of report.board) { delete bd[k]; removed++; }
      if (report.board.length) await KV.put("board", JSON.stringify(bd));
      for (const n of report.favs) { await KV.delete(n); removed++; }
      for (const n of report.utrips) { await KV.delete(n); removed++; }
      for (const n of report.trips) { await KV.delete(n); removed++; }
      for (const r of report.rate) {
        try { const rm = JSON.parse((await KV.get(r.k)) || "{}");
          for (const u of r.bad) delete rm[u];
          if (Object.keys(rm).length) await KV.put(r.k, JSON.stringify(rm)); else await KV.delete(r.k);
          removed++;
        } catch (e) {}
      }
      return J({ ok: true, removed, report });
    }

    // 0-2c) 이미지 업로드(로그인 사용자) — KV에 base64 저장(클라가 압축). 추후 R2 이전(8c).
    if (url.pathname.endsWith("/upload")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      if (req.method !== "POST") return new Response("method", { status: 405, headers: cors });
      let b = {}; try { b = await req.json(); } catch (e) {}
      if (!b.id || !(await _tokOk(env, String(b.id), b.tok))) return new Response("relogin", { status: 401, headers: cors });
      const KV = env.PLACES; if (!KV) return new Response("no-store", { status: 500, headers: cors });
      const m = String(b.img || "").match(/^data:image\/(?:jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=]+)$/);
      if (!m) return new Response("bad-image", { status: 400, headers: cors });
      const b64 = m[1];
      if (b64.length > 950000) return new Response("too-large", { status: 413, headers: cors });   // ~700KB
      const key = String(b.id).replace(/[^a-zA-Z0-9]/g, "").slice(0, 24) + "_" + Date.now().toString(36);
      await KV.put("img:" + key, b64);
      return new Response(JSON.stringify({ ok: true, key: key }), { headers: { ...cors, "Content-Type": "application/json" } });
    }
    // 0-2d) 이미지 서빙 — /img?k=<key> (엣지 캐시 + 장기 캐시헤더)
    if (url.pathname.endsWith("/img")) {
      const key = (url.searchParams.get("k") || "").replace(/[^a-zA-Z0-9_]/g, "").slice(0, 40);
      const KV = env.PLACES;
      if (!key || !KV) return new Response("not found", { status: 404 });
      const cache = caches.default; const ck = new Request(url.toString());
      let hit = await cache.match(ck); if (hit) return hit;
      const b64 = await KV.get("img:" + key);
      if (!b64) return new Response("not found", { status: 404 });
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const resp = new Response(bytes, { headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*" } });
      ctx.waitUntil(cache.put(ck, resp.clone()));
      return resp;
    }

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
        if (!(await _tokOk(env, String(b.id), b.tok))) return new Response("relogin", { status: 401, headers: cors });
        if (env.LOG_WEBHOOK) ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "suggest", cat: String(b.cat || "기타").slice(0, 10),
            place: String(b.addr || "").slice(0, 80), nick: String(b.nick || "").slice(0, 20),
            text: String(b.text || "").slice(0, 200), lat: Number(b.lat) || "", lng: Number(b.lng) || "",
            img: String(b.img || "").slice(0, 200),
          }),
        }).catch(function () {}));
        return new Response("ok", { headers: cors });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3d) 코스 등록(관리자) — 거리측정 경로를 코스로. KV "courses"
    if (url.pathname.endsWith("/courses") || url.pathname.endsWith("/course")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
      if (req.method === "GET") {
        return _cacheJson(ctx, url.toString(), async () => {
          if (url.searchParams.get("mine")) {
            const uid = (url.searchParams.get("uid") || "").slice(0, 40);
            if (!uid || !(await _tokOk(env, uid, url.searchParams.get("tok")))) return J("[]");
            const d = KV ? await KV.get("courses") : null;
            let arr = []; try { arr = JSON.parse(d || "[]"); } catch (e) {}
            arr = arr.filter((x) => String(x.owner || "") === String(uid));
            return new Response(JSON.stringify(arr), { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
          }
          if (url.searchParams.get("hidden")) { const h = KV ? await KV.get("course_hidden") : null; return new Response(h || "[]", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } }); }   // 정적 코스 숨김 cid 목록
          if (url.searchParams.get("over")) { const o = KV ? await KV.get("course_over") : null; return new Response(o || "{}", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } }); }   // 정적 코스 이름/분류/거리 오버라이드
          const d = KV ? await KV.get("courses") : null; return new Response(d || "[]", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
        }, 60);
      }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        const uid = String(b.id || "").slice(0, 40);
        const tokOk = uid && (await _tokOk(env, uid, b.tok));
        const adminOk = !!env.ADMIN_KEY && String(b.adminKey) === String(env.ADMIN_KEY);
        const ownerEditOk = async (courseId) => {
          const arr0 = JSON.parse((await KV.get("courses")) || "[]");
          const it = arr0.find((x) => String(x.id) === String(courseId));
          return !!(it && uid && String(it.owner || "") === uid && tokOk);
        };
        if (b.action === "hidestatic" || b.action === "unhidestatic") {   // 정적(임베드) 코스 숨김/복원 — KV "course_hidden"
          if (!adminOk) return new Response("forbidden", { status: 403, headers: cors });
          const cid = String(b.cid || "").slice(0, 20); if (!cid) return new Response("bad", { status: 400, headers: cors });
          let hid = []; try { hid = JSON.parse((await KV.get("course_hidden")) || "[]"); } catch (e) {}
          hid = hid.filter((x) => String(x) !== cid);
          if (b.action === "hidestatic") hid.push(cid);
          await KV.put("course_hidden", JSON.stringify(hid));
          return J(JSON.stringify({ ok: true }));
        }
        if (b.action === "editstatic") {   // 정적 코스는 원본 GeoJSON 비파괴, 표시 메타만 KV 오버라이드
          if (!adminOk) return new Response("forbidden", { status: 403, headers: cors });
          const cid = String(b.cid || "").slice(0, 20); if (!cid) return new Response("bad", { status: 400, headers: cors });
          let over = {}; try { over = JSON.parse((await KV.get("course_over")) || "{}"); } catch (e) {}
          const name = String(b.name || "").slice(0, 80);
          const km = Number(b.km);
          if (!name && !Number.isFinite(km)) delete over[cid];
          else {
            over[cid] = over[cid] || {};
            if (name) over[cid].name = name;
            if (Number.isFinite(km)) over[cid].km = km;
          }
          await KV.put("course_over", JSON.stringify(over));
          return J(JSON.stringify({ ok: true }));
        }
        let arr = []; try { arr = JSON.parse((await KV.get("courses")) || "[]"); } catch (e) {}
        if (b.action === "delete" || b.action === "deleteuser") {
          if (!adminOk && !(await ownerEditOk(b.courseId))) return new Response("forbidden", { status: 403, headers: cors });
          arr = arr.filter((x) => String(x.id) !== String(b.courseId));
        } else if (b.action === "edit" || b.action === "edituser") {
          const it = arr.find((x) => String(x.id) === String(b.courseId));
          if (!it) return new Response("notfound", { status: 404, headers: cors });
          if (!adminOk && !(uid && String(it.owner || "") === uid && tokOk)) return new Response("forbidden", { status: 403, headers: cors });
          it.name = String(b.name || it.name || "코스").slice(0, 80);
          if (b.km != null) it.km = Number(b.km) || 0;
        } else if (b.action === "add" || b.action === "adduser" || !b.action) {
          const coords = Array.isArray(b.coords) ? b.coords.slice(0, 5000) : [];
          if (coords.length < 2) return new Response("bad", { status: 400, headers: cors });
          if (!adminOk && !(uid && tokOk)) return new Response("relogin", { status: 401, headers: cors });
          const segments = Array.isArray(b.segments) ? b.segments.slice(0, 40).map((s) => ({
            name: String((s && s.name) || "구간").slice(0, 30),
            km: Number(s && s.km) || 0,
            mode: String((s && s.mode) || "").slice(0, 12),
          })) : [];
          arr.unshift({ id: Date.now(), name: String(b.name || "코스").slice(0, 80), coords: coords, km: Number(b.km) || 0, segments: segments, t: Date.now(), owner: adminOk ? "admin" : uid, nick: String(b.nick || "").slice(0, 20) });
          if (arr.length > 200) arr = arr.slice(0, 200);
        } else {
          return new Response("bad", { status: 400, headers: cors });
        }
        await KV.put("courses", JSON.stringify(arr));
        return J(JSON.stringify({ ok: true }));
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3g) 별점(장소/코스) — KV "rate_<target>" = {uid:별점}
    if (url.pathname.endsWith("/rate")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (o) => new Response(JSON.stringify(o), { headers: { ...cors, "Content-Type": "application/json" } });
      if (!KV) return new Response("no-store", { status: 500, headers: cors });
      if (req.method === "GET") {
        let uid = (url.searchParams.get("uid") || "").slice(0, 40);
        if (uid && !(await _tokOk(env, uid, url.searchParams.get("tok")))) uid = "";   // 무효 토큰이면 내 별점만 비표시
        const targets = (url.searchParams.get("targets") || "").split(",").filter(Boolean).slice(0, 30);
        const out = {};
        for (const t of targets) {
          const key = "rate_" + t.slice(0, 60);
          let m = {}; try { m = JSON.parse((await KV.get(key)) || "{}"); } catch (e) {}
          const vals = Object.values(m).map(Number).filter((v) => v >= 1 && v <= 5);
          out[t] = { n: vals.length, avg: vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length * 10) / 10 : 0, my: (uid && m[uid]) || 0 };
        }
        return J(out);
      }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        const uid = String(b.id || "").slice(0, 40); const t = String(b.target || "").slice(0, 60);
        const stars = Math.round(Number(b.stars));
        if (!uid || !t || !(stars >= 1 && stars <= 5)) return new Response("bad", { status: 400, headers: cors });
        if (!(await _tokOk(env, uid, b.tok))) return new Response("relogin", { status: 401, headers: cors });
        const key = "rate_" + t;
        let m = {}; try { m = JSON.parse((await KV.get(key)) || "{}"); } catch (e) {}
        m[uid] = stars;
        await KV.put(key, JSON.stringify(m));
        const vals = Object.values(m).map(Number).filter((v) => v >= 1 && v <= 5);
        return J({ ok: true, n: vals.length, avg: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length * 10) / 10, my: stars });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3h) 즐겨찾기 — KV "favs_<uid>" = [{t,n,k}] (target, 이름, 종류 p/c)
    if (url.pathname.endsWith("/fav")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (o) => new Response(JSON.stringify(o), { headers: { ...cors, "Content-Type": "application/json" } });
      if (!KV) return new Response("no-store", { status: 500, headers: cors });
      if (req.method === "GET") {
        const uid = (url.searchParams.get("uid") || "").slice(0, 40);
        if (!uid || !(await _tokOk(env, uid, url.searchParams.get("tok")))) return J([]);   // 본인만 열람
        let a = []; try { a = JSON.parse((await KV.get("favs_" + uid)) || "[]"); } catch (e) {}
        return J(a);
      }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        const uid = String(b.id || "").slice(0, 40); const t = String(b.target || "").slice(0, 60);
        if (!uid || !t) return new Response("bad", { status: 400, headers: cors });
        if (!(await _tokOk(env, uid, b.tok))) return new Response("relogin", { status: 401, headers: cors });
        let a = []; try { a = JSON.parse((await KV.get("favs_" + uid)) || "[]"); } catch (e) {}
        a = a.filter((x) => x && x.t !== t);
        if (b.on) a.unshift({ t: t, n: String(b.name || "").slice(0, 60), k: String(b.kind || "p").slice(0, 1), lat: Number(b.lat) || null, lng: Number(b.lng) || null });
        if (a.length > 200) a = a.slice(0, 200);
        await KV.put("favs_" + uid, JSON.stringify(a));
        return J({ ok: true, n: a.length });
      }
      return new Response("method", { status: 405, headers: cors });
    }

    // 0-3f) 수위 조회 — HRFCO 프록시(키는 Secret HRFCO_KEY), KV 캐시 10분
    if (url.pathname.endsWith("/waterlevel")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      if (!env.HRFCO_KEY) return new Response(JSON.stringify({ err: "nokey" }), { status: 503, headers: { ...cors, "Content-Type": "application/json" } });
      const obs = (url.searchParams.get("obs") || "").replace(/[^0-9,]/g, "").slice(0, 200);
      if (!obs) return new Response("bad", { status: 400, headers: cors });
      const KV = env.PLACES;
      const out = {};
      for (const cd of obs.split(",").filter(Boolean).slice(0, 12)) {
        const ck = "wl_" + cd;
        let v = KV ? await KV.get(ck) : null;
        if (!v) {
          try {
            const r = await fetch(`https://api.hrfco.go.kr/${env.HRFCO_KEY}/waterlevel/list/10M/${cd}.json`);
            const j = await r.json();
            const rec = (j.content || [])[0];
            if (rec) v = JSON.stringify({ wl: rec.wl, t: rec.ymdhm });
          } catch (e) {}
          if (v && KV) await KV.put(ck, v, { expirationTtl: 600 });
        }
        if (v) { try { out[cd] = JSON.parse(v); } catch (e) {} }
      }
      return new Response(JSON.stringify(out), { headers: { ...cors, "Content-Type": "application/json" } });
    }

    // 0-3e) 지형지물(보/징검다리/낮은바닥/여울/유명지) — 관리자. KV "obstacles". 여울·유명지는 name 보유
    if (url.pathname.endsWith("/obstacles") || url.pathname.endsWith("/obstacle")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      const KV = env.PLACES;
      const J = (s) => new Response(s, { headers: { ...cors, "Content-Type": "application/json" } });
      if (req.method === "GET") { return _cacheJson(ctx, url.toString(), async () => {
        const d = KV ? await KV.get("obstacles") : null;
        return new Response(d || "[]", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
      }, 60); }
      if (req.method === "POST") {
        let b = {}; try { b = await req.json(); } catch (e) {}
        if (!KV) return new Response("no-store", { status: 500, headers: cors });
        const TYPES = ["보", "징검다리", "낮은바닥", "여울", "유명지"];
        let arr = []; try { arr = JSON.parse((await KV.get("obstacles")) || "[]"); } catch (e) {}
        let created = null;
        const seedAdd = b.action === "add" && String(b.obsId || "").startsWith("weir:");
        if (!seedAdd && (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY))) return new Response("forbidden", { status: 403, headers: cors });
        if (b.action === "delete") {
          const it = arr.find((x) => String(x.id) === String(b.obsId));
          if (it && String(b.obsId || "").startsWith("weir:")) {
            it.del = true;
            it.t = Date.now();
          } else {
            arr = arr.filter((x) => String(x.id) !== String(b.obsId));
          }
        } else if (b.action === "edit") {
          let it = arr.find((x) => String(x.id) === String(b.obsId));
          if (!it && String(b.obsId || "").trim()) {
            it = { id: String(b.obsId), lat: null, lng: null, type: "보", note: "", name: "", t: Date.now() };
            arr.unshift(it);
          }
          if (!it) return new Response("notfound", { status: 404, headers: cors });
          if (it.del) delete it.del;
          if (b.type && TYPES.indexOf(b.type) >= 0) it.type = b.type;
          if (b.note != null) it.note = String(b.note).slice(0, 200);
          if (b.name != null) it.name = String(b.name).slice(0, 40);
          if (b.lat != null && b.lng != null) { it.lat = Number(b.lat); it.lng = Number(b.lng); }
        } else if (b.action === "add" && String(b.obsId || "").trim()) {
          const lat = Number(b.lat), lng = Number(b.lng);
          if (!isFinite(lat) || !isFinite(lng)) return new Response("bad", { status: 400, headers: cors });
          const id = String(b.obsId).trim();
          let it = arr.find((x) => String(x.id) === id);
          if (it) {
            if (it.del) delete it.del;
            if (b.type && TYPES.indexOf(b.type) >= 0) it.type = b.type;
            it.note = String(b.note || "").slice(0, 200);
            it.name = String(b.name || "").slice(0, 40);
            it.lat = lat; it.lng = lng;
            created = it;
          } else {
            created = { id: id, lat: lat, lng: lng, type: TYPES.indexOf(b.type) >= 0 ? b.type : "보", note: String(b.note || "").slice(0, 200), name: String(b.name || "").slice(0, 40), t: Date.now() };
            arr.unshift(created);
          }
        } else {
          const lat = Number(b.lat), lng = Number(b.lng);
          if (!isFinite(lat) || !isFinite(lng)) return new Response("bad", { status: 400, headers: cors });
          const type = TYPES.indexOf(b.type) >= 0 ? b.type : "보";
          created = { id: String(b.obsId || Date.now()), lat: lat, lng: lng, type: type, note: String(b.note || "").slice(0, 200), name: String(b.name || "").slice(0, 40), t: Date.now() };
          arr.unshift(created);
          if (arr.length > 500) arr = arr.slice(0, 500);
        }
        await KV.put("obstacles", JSON.stringify(arr));
        return J(JSON.stringify({ ok: true, obstacle: created }));
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
      if (req.method === "GET") { return _cacheJson(ctx, url.toString(), async () => {
        const d = KV ? await KV.get("notices") : null;
        return new Response(d || "[]", { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=60" } });
      }, 60); }
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
        } else if (action === "replyDelete") {
          if (!env.ADMIN_KEY || String(b.adminKey) !== String(env.ADMIN_KEY)) return new Response("forbidden", { status: 403, headers: cors });
          const nt = arr.find((x) => String(x.id) === String(b.noticeId));
          if (!nt || !Array.isArray(nt.replies)) return new Response("bad", { status: 400, headers: cors });
          const ri = nt.replies.findIndex((r) => String(r.t) === String(b.replyT));
          if (ri >= 0) nt.replies.splice(ri, 1);
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

        if (tp.endsWith("/trips")) {            // 내 트립 목록(본인만 — 토큰 필수)
          const uid = url.searchParams.get("uid") || "";
          if (!uid || !(await _tokOk(env, uid, url.searchParams.get("tok")))) return J("[]");
          const data = KV ? await KV.get("utrips:" + uid) : null;
          return J(data || "[]");
        }
        if (tp.endsWith("/feed")) {             // 공유 트립 목록(uid 비노출)
          let feed = []; try { feed = JSON.parse((KV ? await KV.get("feed") : null) || "[]"); } catch (e) {}
          return J(JSON.stringify(feed.map((x) => ({ id: x.id, nick: x.nick, title: x.title, distKm: x.distKm, start: x.start }))));
        }
        if (tp.endsWith("/board")) {            // 랭킹(uid → 가명 해시, 본인 행은 me 표시)
          let obj = {};
          try { obj = JSON.parse((KV ? await KV.get("board") : null) || "{}"); } catch (e) {}
          let me = url.searchParams.get("uid") || "";
          if (me && !(await _tokOk(env, me, url.searchParams.get("tok")))) me = "";
          const arr = [];
          for (const k of Object.keys(obj)) {
            arr.push({ h: await _uidHash(env, k), nick: obj[k].nick, totalKm: obj[k].totalKm, trips: obj[k].trips, me: String(k) === String(me) });
          }
          arr.sort((a, b) => b.totalKm - a.totalKm);
          return J(JSON.stringify(arr.slice(0, 50)));
        }
        // /trip
        if (req.method === "GET") {             // 트립 1건(공유 = 공개 / 비공유 = 소유자 토큰 필수)
          const id = url.searchParams.get("id") || "", viewer = url.searchParams.get("viewer") || "";
          const t = KV ? await KV.get("trip:" + id) : null;
          if (!t) return TXT("not found", 404);
          const trip = JSON.parse(t);
          if (!trip.shared) {
            const ok = String(viewer) === String(trip.uid) && (await _tokOk(env, viewer, url.searchParams.get("tok")));
            if (!ok) return TXT("forbidden", 403);
          }
          return J(t);
        }
        if (req.method === "POST") {
          let b = {};
          try { b = await req.json(); } catch (e) {}
          const action = b.action || "save";
          if (!b.id) return TXT("forbidden", 403);
          const isAdminReq = !!env.ADMIN_KEY && String(b.adminKey) === String(env.ADMIN_KEY);
          if (!isAdminReq && !(await _tokOk(env, String(b.id), b.tok))) return TXT("relogin", 401);
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

    // 0-10) 소양호 카누잉 종주 참가 확인 — 로그인 사용자만 제출, KV "soyang_traverse_signups"
    if (url.pathname.endsWith("/soyang-travers")) {
      const origin = req.headers.get("Origin") || "*";
      const cors = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      };
      if (req.method === "OPTIONS") return new Response(null, { headers: cors });
      if (req.method !== "POST") return new Response("method", { status: 405, headers: cors });
      const KV = env.PLACES;
      if (!KV) return new Response("no-store", { status: 500, headers: cors });
      let b = {}; try { b = await req.json(); } catch (e) {}
      const uid = String(b.id || "").slice(0, 40);
      if (!uid || !(await _tokOk(env, uid, b.tok))) return new Response("relogin", { status: 401, headers: cors });
      const name = String(b.name || "").trim().slice(0, 40);
      const cafeNick = String(b.cafeNick || "").trim().slice(0, 40);
      const phone = String(b.phone || "").trim().slice(0, 30);
      const agreed = !!b.agreed;
      if (!agreed || !name || !cafeNick || !phone) return new Response("bad", { status: 400, headers: cors });
      let arr = []; try { arr = JSON.parse((await KV.get("soyang_traverse_signups")) || "[]"); } catch (e) {}
      const rec = {
        uid,
        kakaoNick: String(b.nick || "").slice(0, 40),
        name,
        cafeNick,
        phone,
        agreed,
        ua: String(req.headers.get("User-Agent") || "").slice(0, 160),
        t: Date.now(),
      };
      arr = arr.filter((x) => String(x.uid || "") !== uid);
      arr.unshift(rec);
      if (arr.length > 500) arr = arr.slice(0, 500);
      await KV.put("soyang_traverse_signups", JSON.stringify(arr));
      if (env.LOG_WEBHOOK) ctx.waitUntil(fetch(env.LOG_WEBHOOK, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "suggest",
          cat: "소양호종주",
          place: "soyang-travers",
          nick: rec.kakaoNick,
          text: "카카오ID: " + uid + " / 실명: " + name + " / 카페닉네임: " + cafeNick + " / 휴대전화: " + phone + " / 동의: Y",
          lat: "",
          lng: "",
          img: "",
        }),
      }).catch(() => {}));
      return new Response(JSON.stringify({ ok: true }), { headers: { ...cors, "Content-Type": "application/json" } });
    }

    // 1) 로그인 시작
    if (!code) {
      const auth = "https://kauth.kakao.com/oauth/authorize?response_type=code"
        + "&client_id=" + env.KAKAO_REST_KEY
        + "&redirect_uri=" + encodeURIComponent(REDIRECT)
        + (back ? "&state=" + encodeURIComponent(back) : "");
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
    const dest = back ? (/^https?:\/\//.test(back) ? back : site.replace(/\/$/, "") + back) : site;
    const idTok = await _tokFor(env, String(id));
    const backUrl = dest + "#login=" + encodeURIComponent(id) + "&nick=" + encodeURIComponent(nick) + "&tok=" + encodeURIComponent(idTok);
    return Response.redirect(backUrl, 302);
  },
};
