// Sisyphus - Reddit Ads API bridge.
//
// GET  ?start=<state>       Sends Sam to Reddit's Allow page (state must be
//                           one we issued in reddit_oauth_state).
// GET  ?code=...&state=...  Reddit sends Sam back here after "Allow". We swap
//                           the code for a refresh token and keep it in
//                           reddit_auth. Only states we issued are accepted.
// POST {method, path, body}  Calls https://ads-api.reddit.com/api/v3/<path>
//                           with a fresh access token. Needs header
//                           x-tool-key (sha256 stored in reddit_tool_keys).
//
// Setup, once:
//   Edge Function secrets: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
//   (from the developer app in Reddit Ads). Deploy with verify_jwt off.
//   Redirect URI in the Reddit app: <project>/functions/v1/reddit-ads

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const REDIRECT_URI = `${SUPABASE_URL}/functions/v1/reddit-ads`;
const API = "https://ads-api.reddit.com/api/v3/";
const UA = "web:sisyphus-ads:v1 (by /u/SisyphusComedy)";
const SCOPES = "adsread adsedit";

function db(path: string, init: RequestInit = {}) {
  return fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
}

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function page(title: string, text: string) {
  const html = `<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>${title}</title><body style="font-family:system-ui;background:#2b2d31;color:#fff;padding:32px;text-align:center">
<h1 style="background:#4a6a8a;display:inline-block;padding:8px 18px;transform:rotate(-2deg)">${title}</h1>
<p style="font-size:18px">${text}</p></body>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

function basicAuth() {
  const id = Deno.env.get("REDDIT_CLIENT_ID") ?? "";
  const secret = Deno.env.get("REDDIT_CLIENT_SECRET") ?? "";
  return "Basic " + btoa(`${id}:${secret}`);
}

async function tokenRequest(form: Record<string, string>) {
  const r = await fetch("https://www.reddit.com/api/v1/access_token", {
    method: "POST",
    headers: {
      Authorization: basicAuth(),
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": UA,
    },
    body: new URLSearchParams(form),
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok && !data.error, data };
}

async function sha256(text: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function start(state: string) {
  const s = await db(`reddit_oauth_state?state=eq.${encodeURIComponent(state)}&used_at=is.null&select=state`);
  if (!s.ok || !(await s.json()).length) return page("Link expired", "Ask Claude for a fresh Allow link.");
  const auth = new URL("https://www.reddit.com/api/v1/authorize");
  auth.search = new URLSearchParams({
    client_id: Deno.env.get("REDDIT_CLIENT_ID") ?? "",
    response_type: "code",
    state,
    redirect_uri: REDIRECT_URI,
    duration: "permanent",
    scope: SCOPES,
  }).toString();
  return Response.redirect(auth.toString(), 302);
}

async function callback(url: URL) {
  const begin = url.searchParams.get("start");
  if (begin) return start(begin);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state") ?? "";
  if (url.searchParams.get("error")) {
    return page("Not connected", `Reddit said: ${url.searchParams.get("error")}. Tell Claude.`);
  }
  if (!code) return page("Nothing to do", "This page is for Reddit's Allow button.");

  // Use up the state; refuse anything we didn't issue.
  const s = await db(
    `reddit_oauth_state?state=eq.${encodeURIComponent(state)}&used_at=is.null`,
    { method: "PATCH", headers: { Prefer: "return=representation" }, body: JSON.stringify({ used_at: new Date().toISOString() }) },
  );
  const rows = s.ok ? await s.json() : [];
  if (!rows.length) return page("Link expired", "Ask Claude for a fresh Allow link.");

  const { ok, data } = await tokenRequest({
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
  });
  if (!ok || !data.refresh_token) {
    return page("Not connected", `Reddit didn't hand over a token (${data.error ?? "unknown"}). Tell Claude.`);
  }
  await db("reddit_auth", {
    method: "POST",
    headers: { Prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({ id: 1, refresh_token: data.refresh_token, scope: data.scope ?? null, updated_at: new Date().toISOString() }),
  });
  return page("Reddit connected", "Done. Claude can run the Reddit ads now. You can close this.");
}

async function accessToken() {
  const r = await db("reddit_auth?id=eq.1&select=refresh_token");
  const rows = r.ok ? await r.json() : [];
  if (!rows.length) return null;
  const { ok, data } = await tokenRequest({ grant_type: "refresh_token", refresh_token: rows[0].refresh_token });
  if (!ok) return null;
  if (data.refresh_token && data.refresh_token !== rows[0].refresh_token) {
    await db("reddit_auth?id=eq.1", { method: "PATCH", body: JSON.stringify({ refresh_token: data.refresh_token, updated_at: new Date().toISOString() }) });
  }
  return data.access_token as string;
}

async function proxy(req: Request) {
  const key = req.headers.get("x-tool-key") ?? "";
  if (!key) return json(401, { error: "Missing x-tool-key" });
  const k = await db(`reddit_tool_keys?key_hash=eq.${await sha256(key)}&select=key_hash`);
  if (!k.ok || !(await k.json()).length) return json(401, { error: "Bad key" });

  let p: { method?: string; path?: string; body?: unknown };
  try {
    p = await req.json();
  } catch {
    return json(400, { error: "Bad request" });
  }
  const path = (p.path ?? "").replace(/^\/+/, "");
  if (!path || path.includes("..")) return json(400, { error: "Bad path" });
  const method = (p.method ?? "GET").toUpperCase();
  if (!["GET", "POST", "PATCH", "PUT", "DELETE"].includes(method)) return json(400, { error: "Bad method" });

  const token = await accessToken();
  if (!token) return json(409, { error: "Reddit isn't connected yet (or the token was revoked)." });

  const r = await fetch(API + path, {
    method,
    headers: { Authorization: `Bearer ${token}`, "User-Agent": UA, "Content-Type": "application/json" },
    body: method === "GET" || method === "DELETE" ? undefined : JSON.stringify(p.body ?? {}),
  });
  const text = await r.text();
  let body: unknown = text;
  try { body = JSON.parse(text); } catch { /* keep text */ }
  return json(200, { status: r.status, body });
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  if (req.method === "GET") return callback(url);
  if (req.method === "POST") return proxy(req);
  return json(405, { error: "GET or POST only" });
});
