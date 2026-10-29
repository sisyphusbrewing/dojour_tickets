// Sisyphus - the taproom LED sign draws its own pictures.
//
// POST { prompt, name? }      a customer's suggestion (public page /sign/).
//                             Claude draws it as 32x32 pixel art and it waits
//                             as "pending" for a manager on /sign/review.html.
//                             Returns { status, art } so the page can show it.
// POST { beers: true }        managers: draws every beer on tap (GoTab feed)
//                             that has no art yet, approved straight away.
// POST { redraw: id }         managers: draws that picture again.
//
// Art is 32 rows of 32 characters: "." is off, 1-9 and A-F pick palette[1..15].
// Needs the ANTHROPIC_API_KEY secret.

import Anthropic from "npm:@anthropic-ai/sdk@1.3.0";

const MODEL = "claude-opus-5-5";
const MENU = "https://sisyphusmenu.stharriman.workers.dev/";
const MAX_SUGGESTIONS_PER_HOUR = 30; // keeps one table from running up the bill
const MAX_BEERS_PER_RUN = 8;
const SIZE = 32;
const CODES = ".123456789ABCDEF";

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

const SYSTEM = `You draw pixel art for the LED sign in the taproom at Sisyphus, a comedy club and brewery in Minneapolis.

The sign is a 64x32 RGB LED panel in a dark bar. Your picture fills a 32x32 square on it and the caption shows beside it. Draw it as 32 rows of exactly 32 characters each. "." is an unlit pixel (black). The characters 1-9 and A-F pick colors from your palette: "1" is palette[0], "2" is palette[1], and so on up to "F" for palette[14]. Use 15 colors or fewer, as 6-digit hex strings without "#".

What reads well on an LED panel:
- One bold subject, big, filling most of the square, on a black background.
- Thick shapes and strong outlines. Single stray pixels and fine detail turn to mush.
- Bright, saturated colors. Dark colors (below about 30% brightness) barely light up, and pure white is glaring, so prefer a warm light gray like B4B4B4 for whites.
- Dark outlines in a deep version of the fill color, not black, so the edges stay visible.

The caption is shown in a small font beside the picture: at most 24 characters, uppercase, punchy, no emoji. Up to three words of five letters or fewer sit still beside the picture; anything longer scrolls past, which is fine for a joke but slower to read. It can be the subject's name or a short funny line in the voice of a comedy club.

Sisyphus pushes a boulder up a mountain forever and has made peace with it; a boulder, a mountain or a hill are fair game when they fit, but don't force them in.

Set ok to false (and still return a blank picture) only when a suggestion asks for something a bar could not show: sexual content, slurs or hate, gore, insults aimed at a real private person, or another business's advertising. Edgy comedy-club humor is fine. Give the reason in one short sentence.`;

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["ok", "reason", "caption", "palette", "rows"],
  properties: {
    ok: { type: "boolean" },
    reason: { type: "string" },
    caption: { type: "string" },
    palette: { type: "array", items: { type: "string" } },
    rows: { type: "array", items: { type: "string" } },
  },
};

type Art = { ok: boolean; reason: string; caption: string; palette: string[]; rows: string[] };

// Whatever comes back, the sign gets exactly 32 rows of 32 valid characters.
function tidy(a: Art): Art {
  const palette = (a.palette ?? []).slice(0, 15).map((c) => {
    const hex = String(c).replace(/^#|^0x/i, "").toUpperCase();
    return /^[0-9A-F]{6}$/.test(hex) ? hex : "000000";
  });
  const allowed = CODES.slice(0, palette.length + 1);
  const rows: string[] = [];
  for (let y = 0; y < SIZE; y++) {
    const raw = String((a.rows ?? [])[y] ?? "").toUpperCase();
    let row = "";
    for (let x = 0; x < SIZE; x++) {
      const ch = raw[x] ?? ".";
      row += allowed.includes(ch) ? ch : ".";
    }
    rows.push(row);
  }
  const caption = String(a.caption ?? "").replace(/[^\x20-\x7E]/g, "").replace(/\s+/g, " ").trim().toUpperCase().slice(0, 24);
  return { ok: !!a.ok, reason: String(a.reason ?? ""), caption, palette, rows };
}

const anthropic = new Anthropic(); // ANTHROPIC_API_KEY

async function draw(ask: string): Promise<Art> {
  const response = await anthropic.beta.messages.create({
    model: MODEL,
    max_tokens: 16000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: { effort: "medium", format: { type: "json_schema", schema: SCHEMA } },
    system: SYSTEM,
    messages: [{ role: "user", content: ask }],
  });
  if (response.stop_reason === "refusal") {
    return { ok: false, reason: "Claude wouldn't draw that one.", caption: "", palette: [], rows: [] };
  }
  const text = response.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("");
  return tidy(JSON.parse(text) as Art);
}

async function isManager(req: Request): Promise<boolean> {
  const auth = req.headers.get("authorization") ?? "";
  if (auth === `Bearer ${KEY}`) return true; // scheduled runs
  const r = await fetch(`${SB}/rest/v1/rpc/is_manager`, {
    method: "POST",
    headers: { apikey: req.headers.get("apikey") ?? KEY, Authorization: auth, "Content-Type": "application/json" },
    body: "{}",
  });
  return r.ok && (await r.json()) === true;
}

async function insert(row: Record<string, unknown>) {
  const r = await fetch(`${SB}/rest/v1/sign_art`, {
    method: "POST",
    headers: { ...H, Prefer: "return=representation" },
    body: JSON.stringify(row),
  });
  if (!r.ok) throw new Error(`insert ${r.status} ${await r.text()}`);
  return (await r.json())[0];
}

async function suggestion(prompt: string, name: string) {
  const since = new Date(Date.now() - 3600_000).toISOString();
  const recent = await fetch(`${SB}/rest/v1/sign_art?select=id&kind=eq.suggestion&created_at=gte.${since}`, { headers: H })
    .then((r) => r.json());
  if (Array.isArray(recent) && recent.length >= MAX_SUGGESTIONS_PER_HOUR) {
    return respond(429, { error: "The sign is busy drawing. Try again in a little while." });
  }
  const art = await draw(`A customer at the bar suggested: "${prompt}"`);
  const saved = await insert({
    kind: "suggestion", prompt, from_name: name || null,
    caption: art.caption, palette: art.palette, rows: art.rows,
    status: art.ok ? "pending" : "rejected", note: art.ok ? null : art.reason,
    decided_at: art.ok ? null : new Date().toISOString(),
  });
  return respond(200, { status: saved.status, note: saved.note, art: { caption: art.caption, palette: art.palette, rows: art.rows } });
}

function beerKey(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

async function beers() {
  const menu = await fetch(MENU).then((r) => r.json());
  const onTap = (menu.sections ?? [])
    .filter((s: { category: string }) => /beer|tap|draft/i.test(s.category) && !/n\/?a|non/i.test(s.category))
    .flatMap((s: { items: { name: string; description?: string }[] }) => s.items ?? []);
  const have = await fetch(`${SB}/rest/v1/sign_art?select=beer_key&kind=eq.beer`, { headers: H }).then((r) => r.json());
  const done = new Set((have as { beer_key: string }[]).map((b) => b.beer_key));
  const missing = onTap.filter((b: { name: string }) => b.name && !done.has(beerKey(b.name)));
  const todo = missing.slice(0, MAX_BEERS_PER_RUN);
  const results = await Promise.allSettled(todo.map(async (b: { name: string; description?: string }) => {
    const art = await draw(
      `Draw the beer on tap called "${b.name}". The menu says: ${(b.description ?? "").replace(/\s+/g, " ").slice(0, 400)}\n` +
      `Make the picture about the beer's name (a pun or the thing it names is great), not just a glass of beer. ` +
      `The caption is the beer's name, shortened only if it is over 24 characters.`,
    );
    if (!art.ok) throw new Error(art.reason);
    await insert({
      kind: "beer", prompt: b.name, beer_key: beerKey(b.name),
      caption: art.caption, palette: art.palette, rows: art.rows,
      status: "approved", decided_at: new Date().toISOString(),
    });
    return b.name;
  }));
  const drawn = results.filter((r) => r.status === "fulfilled").map((r) => (r as PromiseFulfilledResult<string>).value);
  const failed = results.filter((r) => r.status === "rejected").map((r) => String((r as PromiseRejectedResult).reason));
  return respond(200, { drawn, failed, left: missing.length - todo.length });
}

async function redraw(id: number) {
  const rows = await fetch(`${SB}/rest/v1/sign_art?select=*&id=eq.${id}`, { headers: H }).then((r) => r.json());
  const row = rows?.[0];
  if (!row) return respond(404, { error: "No such picture." });
  const ask = row.kind === "beer"
    ? `Draw the beer on tap called "${row.prompt}". Make the picture about the beer's name. The caption is the beer's name.`
    : `A customer at the bar suggested: "${row.prompt}"`;
  const art = await draw(ask + "\nThis is a second try, so take a fresh approach.");
  const r = await fetch(`${SB}/rest/v1/sign_art?id=eq.${id}`, {
    method: "PATCH",
    headers: { ...H, Prefer: "return=representation" },
    body: JSON.stringify({ caption: art.caption, palette: art.palette, rows: art.rows }),
  });
  return respond(200, { art: (await r.json())[0] });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });
  if (!Deno.env.get("ANTHROPIC_API_KEY")) return respond(503, { error: "The sign isn't set up to draw yet." });

  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { /* bad body */ }

  try {
    if (body.beers || body.redraw) {
      if (!(await isManager(req))) return respond(403, { error: "Managers only." });
      return body.beers ? await beers() : await redraw(Number(body.redraw));
    }
    const prompt = String(body.prompt ?? "").replace(/\s+/g, " ").trim().slice(0, 100);
    const name = String(body.name ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
    if (prompt.length < 2) return respond(400, { error: "Tell the sign what to draw." });
    return await suggestion(prompt, name);
  } catch (e) {
    console.error(e);
    return respond(500, { error: "The sign couldn't draw that right now. Try again in a minute." });
  }
});
