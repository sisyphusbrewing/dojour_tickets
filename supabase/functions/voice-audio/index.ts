// Sisyphus - voice notes: uploads and deletes the audio for /voice/.
//
// Storage only lets managers upload or delete files directly, and Lindsey's
// login is door level (Nov 5 2026). Instead of loosening that rule for
// everyone, the page asks this function, which checks that the signed-in
// person can use voice notes and owns the note, then:
//   { action: "sign", path: "<note id>/part-0003.m4a" } -> a one-time upload token
//   { action: "delete", note_id }                      -> removes that note's audio

const SB = Deno.env.get("SUPABASE_URL") ?? "";
const ANON = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const BUCKET = "voice-notes";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}

// Asks the database as the caller, so their own rules apply.
async function rpc(auth: string, fn: string, args: Record<string, unknown>) {
  const r = await fetch(`${SB}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: { apikey: ANON, Authorization: auth, "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  return r.ok && (await r.json()) === true;
}

const admin = { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, "Content-Type": "application/json" };

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });
  const auth = req.headers.get("Authorization") ?? "";

  let p: { action?: string; path?: string; note_id?: string };
  try {
    p = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }

  if (!(await rpc(auth, "can_voice", {}))) return respond(403, { error: "This login isn't set up for voice notes." });

  if (p.action === "sign") {
    const path = String(p.path ?? "");
    if (!/^[0-9a-f-]{36}\/part-\d{4}\.[a-z0-9]{1,5}$/.test(path)) return respond(400, { error: "Bad path" });
    if (!(await rpc(auth, "owns_voice_note", { p_name: path }))) return respond(403, { error: "Not your note" });
    const r = await fetch(`${SB}/storage/v1/object/upload/sign/${BUCKET}/${path}`, {
      method: "POST", headers: { ...admin, "x-upsert": "true" }, body: "{}",
    });
    if (!r.ok) return respond(502, { error: `Storage said ${r.status}` });
    const { url } = await r.json();
    const token = new URL(url, SB).searchParams.get("token");
    return respond(200, { path, token });
  }

  if (p.action === "delete") {
    const id = String(p.note_id ?? "");
    if (!/^[0-9a-f-]{36}$/.test(id)) return respond(400, { error: "Bad note" });
    if (!(await rpc(auth, "owns_voice_note", { p_name: `${id}/x` }))) return respond(403, { error: "Not your note" });
    const list = await fetch(`${SB}/storage/v1/object/list/${BUCKET}`, {
      method: "POST", headers: admin, body: JSON.stringify({ prefix: `${id}/`, limit: 1000 }),
    });
    const names = list.ok ? ((await list.json()) as { name: string }[]).map((o) => `${id}/${o.name}`) : [];
    if (names.length) {
      await fetch(`${SB}/storage/v1/object/${BUCKET}`, { method: "DELETE", headers: admin, body: JSON.stringify({ prefixes: names }) });
    }
    return respond(200, { ok: true, deleted: names.length });
  }

  return respond(400, { error: "Unknown action" });
});
