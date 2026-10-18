// Sisyphus - staff logins, for managers.
//
// The manager page lists logins, adds new ones, resets passwords and switches
// a login between "door" (tonight's check-in only) and "manager". Logins are
// Supabase users; a plain username like "rjoseph" is stored as
// rjoseph@sisyphusbrewing.com, which is what the sign-in box adds when no @
// is typed. Only a signed-in manager can call this.

const DOMAIN = "sisyphusbrewing.com";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

const BASE = Deno.env.get("SUPABASE_URL") ?? "";
const ANON = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const admin = { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, "Content-Type": "application/json" };

function toEmail(login: string) {
  const v = login.trim().toLowerCase();
  return v.includes("@") ? v : `${v}@${DOMAIN}`;
}

async function setRole(userId: string, role: string) {
  const r = await fetch(`${BASE}/rest/v1/staff_roles?on_conflict=user_id`, {
    method: "POST",
    headers: { ...admin, Prefer: "resolution=merge-duplicates" },
    body: JSON.stringify({ user_id: userId, role, updated_at: new Date().toISOString() }),
  });
  if (!r.ok) throw new Error(`role save failed (${r.status})`);
}

async function authError(r: Response) {
  try {
    const b = await r.json();
    return b.msg || b.message || b.error_description || b.error || `error ${r.status}`;
  } catch {
    return `error ${r.status}`;
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });

  // Caller must be a signed-in manager.
  const auth = req.headers.get("Authorization") ?? "";
  const me = await fetch(`${BASE}/auth/v1/user`, { headers: { Authorization: auth, apikey: ANON } });
  if (!me.ok) return respond(401, { error: "Please sign in again." });
  const meId = (await me.json()).id as string;
  const mgr = await fetch(`${BASE}/rest/v1/rpc/is_manager`, {
    method: "POST",
    headers: { Authorization: auth, apikey: ANON, "Content-Type": "application/json" },
    body: "{}",
  });
  if (!mgr.ok || (await mgr.json()) !== true) return respond(403, { error: "Managers only." });

  let p: { action?: string; login?: string; password?: string; role?: string; user_id?: string };
  try {
    p = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }

  try {
    if (p.action === "list") {
      const [u, r] = await Promise.all([
        fetch(`${BASE}/auth/v1/admin/users?per_page=200`, { headers: admin }),
        fetch(`${BASE}/rest/v1/staff_roles?select=user_id,role`, { headers: admin }),
      ]);
      if (!u.ok) return respond(502, { error: await authError(u) });
      const roles = new Map((await r.json() as { user_id: string; role: string }[]).map((x) => [x.user_id, x.role]));
      const users = ((await u.json()).users ?? []).map((x: { id: string; email: string; last_sign_in_at: string | null }) => ({
        user_id: x.id,
        login: x.email?.endsWith(`@${DOMAIN}`) ? x.email.slice(0, -DOMAIN.length - 1) : x.email,
        role: roles.get(x.id) ?? "door",
        last_sign_in_at: x.last_sign_in_at,
        me: x.id === meId,
      }));
      return respond(200, { users });
    }

    if (p.action === "create") {
      const login = (p.login ?? "").trim();
      const role = p.role === "manager" ? "manager" : "door";
      if (!/^[a-z0-9._+-]+(@[a-z0-9.-]+\.[a-z]+)?$/i.test(login)) {
        return respond(400, { error: "Use letters and numbers for the username." });
      }
      if ((p.password ?? "").length < 8) return respond(400, { error: "Password needs at least 8 characters." });
      const c = await fetch(`${BASE}/auth/v1/admin/users`, {
        method: "POST",
        headers: admin,
        body: JSON.stringify({ email: toEmail(login), password: p.password, email_confirm: true }),
      });
      if (!c.ok) return respond(400, { error: await authError(c) });
      const user = await c.json();
      await setRole(user.id, role);
      return respond(200, { ok: true });
    }

    if (!/^[0-9a-f-]{36}$/i.test(p.user_id ?? "")) return respond(400, { error: "Which login?" });

    if (p.action === "set_role") {
      if (p.user_id === meId) return respond(400, { error: "You can't change your own access." });
      await setRole(p.user_id, p.role === "manager" ? "manager" : "door");
      return respond(200, { ok: true });
    }

    if (p.action === "set_password") {
      if ((p.password ?? "").length < 8) return respond(400, { error: "Password needs at least 8 characters." });
      const s = await fetch(`${BASE}/auth/v1/admin/users/${p.user_id}`, {
        method: "PUT",
        headers: admin,
        body: JSON.stringify({ password: p.password }),
      });
      if (!s.ok) return respond(400, { error: await authError(s) });
      return respond(200, { ok: true });
    }

    if (p.action === "remove") {
      if (p.user_id === meId) return respond(400, { error: "You can't remove your own login." });
      const d = await fetch(`${BASE}/auth/v1/admin/users/${p.user_id}`, { method: "DELETE", headers: admin });
      if (!d.ok) return respond(400, { error: await authError(d) });
      return respond(200, { ok: true });
    }

    return respond(400, { error: `Unknown action: ${p.action}` });
  } catch (err) {
    console.error(err);
    return respond(500, { error: String((err as Error).message ?? err) });
  }
});
