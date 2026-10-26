// Sisyphus - a comic types their name into the Good-Enough-o-Matic
// (staff.sisyphusbrewing.com/goodenough/) and gets their own CSS reveal.
//
// POST { name } with the public anon key. If the comic is already on the CSS
// page (comic_scores), returns their share_token; otherwise adds them as a
// request and starts the "Comic scores" action, which looks them up in a few
// minutes. The page then polls css_reveal(token) until the score is in.
// Returns { token, status: "scored" | "requested" | "not_found" }.
// Needs the same GITHUB_TOKEN secret as run-workflow.

const REPO = "sisyphusbrewing/dojour_tickets";
// The public name box was a one-night thing (Oct 25 2026). While ASLEEP, every
// lookup gets 410 { status: "asleep" } and the page shows its asleep message;
// Sam's ?t= links don't use this function. Flip to false to open it again.
const ASLEEP = false;   // Sam woke it for 2 hours, Oct 26 ~6:30-8:30 PM CT
const MAX_NEW_PER_HOUR = 30;   // keeps a spammer from queueing hundreds of lookups

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}

const SB = Deno.env.get("SUPABASE_URL") ?? "";
const KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const H = { apikey: KEY, Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" };

// "  dayton   bissett " -> "Dayton Bissett"; keeps O'Flanagan, Cayton-Holland.
function cleanName(raw: string): string {
  const s = raw.normalize("NFC").replace(/\s+/g, " ").trim();
  if (s.length < 3 || s.length > 60 || !/^[\p{L}][\p{L}\p{M} .'’-]*$/u.test(s)) return "";
  return s.split(" ").map((w) => (w === w.toLowerCase() ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });
  if (ASLEEP) return respond(410, { status: "asleep" });

  let name = "";
  try { name = cleanName(String((await req.json()).name ?? "")); } catch { /* bad body */ }
  if (!name) return respond(400, { error: "Type your full name, the way you bill it." });

  const found = await fetch(
    `${SB}/rest/v1/comic_scores?select=comedian,status,share_token&comedian=ilike.${encodeURIComponent(name.replace(/[%_]/g, ""))}`,
    { headers: H },
  ).then((r) => r.json());
  if (Array.isArray(found) && found.length) {
    return respond(200, { token: found[0].share_token, status: found[0].status, comedian: found[0].comedian });
  }

  const since = new Date(Date.now() - 3600_000).toISOString();
  const recent = await fetch(
    `${SB}/rest/v1/comic_scores?select=comedian&requested_by=eq.public&created_at=gte.${since}`,
    { headers: H },
  ).then((r) => r.json());
  if (Array.isArray(recent) && recent.length >= MAX_NEW_PER_HOUR) {
    return respond(429, { error: "The machine is very busy. Try again in a little while." });
  }

  const ins = await fetch(`${SB}/rest/v1/comic_scores`, {
    method: "POST",
    headers: { ...H, Prefer: "return=representation" },
    body: JSON.stringify({ comedian: name, requested_by: "public" }),
  });
  const row = (await ins.json())?.[0];
  if (!ins.ok || !row) return respond(500, { error: "Could not add you. Try again." });

  const token = Deno.env.get("GITHUB_TOKEN");
  if (token) {
    const gh = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/css_score.yml/dispatches`, {
      method: "POST",
      headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "Content-Type": "application/json", "User-Agent": "sisyphus-css" },
      body: JSON.stringify({ ref: "main" }),
    });
    if (gh.status !== 204) console.error(`GitHub dispatch failed (${gh.status}): ${await gh.text()}`);
  }
  return respond(200, { token: row.share_token, status: "requested", comedian: row.comedian });
});
