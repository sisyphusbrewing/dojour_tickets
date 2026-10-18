// Sisyphus - someone just sent a public form: a job application
// (jobs/index.html) or a Sam's Tank pitch (tank/index.html, kind "tank").
//
// The form calls this with the new row's id. We check it is a real, fresh,
// not-yet-emailed row with the service key, then start the GitHub Action that
// emails it to booking@ (job_notify.yml or tank_notify.yml).
//
// Needs the same GITHUB_TOKEN secret as run-workflow (Edge Functions > Secrets).

const REPO = "sisyphusbrewing/dojour_tickets";
const KINDS: Record<string, { table: string; workflow: string; input: string }> = {
  job: { table: "job_applications", workflow: "job_notify.yml", input: "application_id" },
  tank: { table: "tank_pitches", workflow: "tank_notify.yml", input: "pitch_id" },
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });

  let payload: { id?: string; kind?: string };
  try {
    payload = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }
  const id = (payload.id ?? "").trim();
  if (!/^[0-9a-f-]{36}$/.test(id)) return respond(400, { error: "Bad id" });
  const kind = KINDS[payload.kind ?? "job"];
  if (!kind) return respond(400, { error: "Bad kind" });

  const url = Deno.env.get("SUPABASE_URL") ?? "";
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const headers = { apikey: service, Authorization: `Bearer ${service}`, "Content-Type": "application/json" };

  const rows = await fetch(`${url}/rest/v1/${kind.table}?id=eq.${id}&select=id,created_at,notified_at`, { headers })
    .then((r) => r.json()).catch(() => []);
  const row = Array.isArray(rows) ? rows[0] : null;
  if (!row) return respond(404, { error: "No such row" });
  if (row.notified_at) return respond(200, { ok: true, skipped: "already notified" });
  if (Date.now() - Date.parse(row.created_at) > 60 * 60 * 1000) return respond(410, { error: "Too old" });

  const gh = Deno.env.get("GITHUB_TOKEN");
  if (!gh) return respond(500, { error: "GITHUB_TOKEN secret is not set in Supabase." });

  // Claim it first so a double call sends one email.
  await fetch(`${url}/rest/v1/${kind.table}?id=eq.${id}`, {
    method: "PATCH",
    headers: { ...headers, Prefer: "return=minimal" },
    body: JSON.stringify({ notified_at: new Date().toISOString() }),
  });

  const dispatch = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${kind.workflow}/dispatches`, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${gh}`,
      "Content-Type": "application/json",
      "User-Agent": "sisyphus-jobs",
    },
    body: JSON.stringify({ ref: "main", inputs: { [kind.input]: id } }),
  });
  if (dispatch.status !== 204) {
    const detail = await dispatch.text();
    console.error(`GitHub dispatch failed (${dispatch.status}): ${detail}`);
    await fetch(`${url}/rest/v1/${kind.table}?id=eq.${id}`, {
      method: "PATCH",
      headers: { ...headers, Prefer: "return=minimal" },
      body: JSON.stringify({ notified_at: null }),
    });
    return respond(502, { error: `GitHub said ${dispatch.status}` });
  }
  return respond(200, { ok: true });
});
