// Sisyphus Brewing - starts a GitHub Action for signed-in staff.
//
// The door app used to ask every device for a GitHub token. Now the app sends
// the staff member's normal Supabase sign-in, and this function (running on
// Supabase) holds the one GitHub token and starts the workflow.
//
// Setup, once:
//   Supabase dashboard > Edge Functions > Secrets: add GITHUB_TOKEN
//   (a fine-grained token for sisyphusbrewing/dojour_tickets with
//   "Actions: Read and write"). Then deploy this function as "run-workflow".

const REPO = "sisyphusbrewing/dojour_tickets";

// Only these workflows can be started from the app.
const ALLOWED_WORKFLOWS = new Set([
  "create_shopify_show.yml",
  "daily_sync.yml",
  "advance_welcome.yml",
  "supply_notify.yml",
]);
const DOOR_WORKFLOWS = new Set(["daily_sync.yml"]);

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

  // Confirm the caller is a signed-in staff member.
  const auth = req.headers.get("Authorization") ?? "";
  const userResp = await fetch(`${Deno.env.get("SUPABASE_URL")}/auth/v1/user`, {
    headers: { Authorization: auth, apikey: Deno.env.get("SUPABASE_ANON_KEY") ?? "" },
  });
  if (!userResp.ok) return respond(401, { error: "Please sign in again." });

  let payload: { workflow?: string; inputs?: Record<string, string> };
  try {
    payload = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }

  const workflow = payload.workflow ?? "";
  if (!ALLOWED_WORKFLOWS.has(workflow)) {
    return respond(400, { error: `Workflow not allowed: ${workflow}` });
  }

  // Door staff can refresh the guest list; everything else is for managers.
  if (!DOOR_WORKFLOWS.has(workflow)) {
    const mgr = await fetch(`${Deno.env.get("SUPABASE_URL")}/rest/v1/rpc/is_manager`, {
      method: "POST",
      headers: { Authorization: auth, apikey: Deno.env.get("SUPABASE_ANON_KEY") ?? "", "Content-Type": "application/json" },
      body: "{}",
    });
    if (!mgr.ok || (await mgr.json()) !== true) return respond(403, { error: "Managers only." });
  }

  const token = Deno.env.get("GITHUB_TOKEN");
  if (!token) return respond(500, { error: "GITHUB_TOKEN secret is not set in Supabase." });

  const gh = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "sisyphus-door-app",
      },
      body: JSON.stringify({ ref: "main", inputs: payload.inputs ?? {} }),
    },
  );

  if (gh.status !== 204) {
    const detail = await gh.text();
    console.error(`GitHub dispatch failed (${gh.status}): ${detail}`);
    return respond(502, { error: `GitHub said ${gh.status}`, detail });
  }
  return respond(200, { ok: true });
});
