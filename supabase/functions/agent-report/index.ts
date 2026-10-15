// Sisyphus - an agent asked for today's ticket numbers (agent/index.html).
//
// Checks the agent's private token with the service key, then starts the
// "Weekly Agent Ticket Reports" action for just that agent. At most one
// request every 10 minutes per agent. Needs the GITHUB_TOKEN secret, like
// run-workflow.

const REPO = "sisyphusbrewing/dojour_tickets";
const WORKFLOW = "weekly_agent_reports.yml";
const COOLDOWN_MS = 10 * 60 * 1000;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
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

  const rows = await fetch(`${url}/rest/v1/show_agents?token=eq.${token}&select=show_title,last_requested_at`, { headers })
    .then((r) => r.json()).catch(() => []);
  const row = Array.isArray(rows) ? rows[0] : null;
  if (!row) return respond(404, { error: "No report with that link" });
  if (row.last_requested_at && Date.now() - Date.parse(row.last_requested_at) < COOLDOWN_MS) {
    return respond(429, { error: "One is already on its way. Give it ten minutes." });
  }

  const gh = Deno.env.get("GITHUB_TOKEN");
  if (!gh) return respond(500, { error: "GITHUB_TOKEN secret is not set in Supabase." });

  const dispatch = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${gh}`, "Content-Type": "application/json", "User-Agent": "sisyphus-agent-report" },
    body: JSON.stringify({ ref: "main", inputs: { token } }),
  });
  if (dispatch.status !== 204) {
    console.error(`GitHub dispatch failed (${dispatch.status}): ${await dispatch.text()}`);
    return respond(502, { error: `GitHub said ${dispatch.status}` });
  }

  await fetch(`${url}/rest/v1/show_agents?token=eq.${token}`, {
    method: "PATCH", headers: { ...headers, Prefer: "return=minimal" },
    body: JSON.stringify({ last_requested_at: new Date().toISOString() }),
  });
  return respond(200, { ok: true });
});
