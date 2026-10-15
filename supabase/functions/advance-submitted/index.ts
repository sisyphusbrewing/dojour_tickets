// Sisyphus - a comedian just sent in their advance (advance/index.html).
//
// The public form calls this with the advance's token. We check the token
// against the database with the service key, then start the "Comedian advance"
// GitHub Action (advance_notify.yml), which emails the answers to booking@.
// The form never holds a GitHub token or the service key.
//
// Needs the same GITHUB_TOKEN secret as run-workflow (Edge Functions > Secrets).

const REPO = "sisyphusbrewing/dojour_tickets";
const WORKFLOW = "advance_notify.yml";

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

  let payload: { token?: string };
  try {
    payload = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }
  const token = (payload.token ?? "").trim();
  if (!/^[a-f0-9]{24}$/.test(token)) return respond(400, { error: "Bad token" });

  const url = Deno.env.get("SUPABASE_URL") ?? "";
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const headers = { apikey: service, Authorization: `Bearer ${service}`, "Content-Type": "application/json" };

  // Only a real, submitted advance gets an email, and only once per submission.
  const rows = await fetch(
    `${url}/rest/v1/advances?token=eq.${token}&status=eq.submitted&select=id,submitted_at,notified_at`,
    { headers },
  ).then((r) => r.json()).catch(() => []);
  const row = Array.isArray(rows) ? rows[0] : null;
  if (!row) return respond(404, { error: "No submitted advance for that token" });
  if (row.notified_at && row.submitted_at && row.notified_at >= row.submitted_at) {
    return respond(200, { ok: true, skipped: "already notified" });
  }

  const gh = Deno.env.get("GITHUB_TOKEN");
  if (!gh) return respond(500, { error: "GITHUB_TOKEN secret is not set in Supabase." });

  const dispatch = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${gh}`,
      "Content-Type": "application/json",
      "User-Agent": "sisyphus-advance",
    },
    body: JSON.stringify({ ref: "main", inputs: { advance_id: row.id } }),
  });
  if (dispatch.status !== 204) {
    const detail = await dispatch.text();
    console.error(`GitHub dispatch failed (${dispatch.status}): ${detail}`);
    return respond(502, { error: `GitHub said ${dispatch.status}` });
  }

  await fetch(`${url}/rest/v1/advances?id=eq.${row.id}`, {
    method: "PATCH",
    headers: { ...headers, Prefer: "return=minimal" },
    body: JSON.stringify({ notified_at: new Date().toISOString() }),
  });
  return respond(200, { ok: true });
});
