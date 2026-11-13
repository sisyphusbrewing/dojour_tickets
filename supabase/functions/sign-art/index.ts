// Sisyphus - the taproom LED sign draws its own pictures.
//
// POST { prompt, name }       a customer's suggestion (public page /sign/).
//                             The name is required and shows on the sign as
//                             "BY <name>" (Sam, Nov 12 2026); it must pass the
//                             word filter and a Claude check before anything
//                             is drawn.
//                             Claude draws it as 32x32 pixel art and it goes
//                             straight onto the sign (Sam, Nov 3 2026: no
//                             manager approval). Rude ideas get redrawn as a
//                             tamer version; a second Claude call looks at the
//                             finished picture and a word filter checks the
//                             caption before it goes up.
//                             Managers can still take any picture down on
//                             /sign/review.html. Returns { status, art }.
// POST { beers: true }        managers: draws every beer on tap (GoTab feed)
//                             that has no art yet, approved straight away.
// POST { redraw: id }         managers: draws that picture again.
//
// Art is 32 rows of 32 characters: "." is off, 1-9 and A-F pick palette[1..15].
// Needs a Claude API key secret: ANTHROPIC_CLIENT_API (what Sam named it in
// Supabase), or the usual ANTHROPIC_API_KEY.

import Anthropic from "npm:@anthropic-ai/sdk@1.3.0";

const MODEL = "claude-opus-5-5";
const MENU = "https://sisyphusmenu.stharriman.workers.dev/";
const MAX_SUGGESTIONS_PER_HOUR = 30; // keeps one table from running up the bill
const MAX_PER_DEVICE_PER_HOUR = 5;   // one phone can't flood the sign
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
- One bold subject, big, on a black background. Use the whole square: the subject should reach within a few pixels of the top and bottom rows and both sides, never sit in one corner or half.
- Thick shapes and strong outlines. Single stray pixels and fine detail turn to mush.
- Bright, saturated colors. Dark colors (below about 30% brightness) barely light up, and pure white is glaring, so prefer a warm light gray like B4B4B4 for whites.
- Dark outlines in a deep version of the fill color, not black, so the edges stay visible.

The caption is shown in a small font beside the picture: at most 24 characters, uppercase, punchy, no emoji. Up to three words of five letters or fewer sit still beside the picture; anything longer scrolls past, which is fine for a joke but slower to read. It can be the subject's name or a short funny line in the voice of a comedy club.

Sisyphus pushes a boulder up a mountain forever and has made peace with it; a boulder, a mountain or a hill are fair game when they fit, but don't force them in.

Nobody reviews the picture before it goes up in front of the whole bar. The house rule (Sam, the owner): R-rated is fine, so swearing, booze, crude and dark jokes are all welcome, but nothing political, offensive or nude.

When a suggestion crosses that line, don't refuse it: tweak it into something more mundane that keeps the characters and the silliness, and draw that. For example, "a dolphin having sex with a monkey" becomes a monkey dressed as a cowboy riding a dolphin like a horse. Sexual acts become a goofy friendly activity, nudity gets clothes, gore becomes a cartoon bonk. Set tamed to true when you did this. Never draw or write anything sexual, nude, political (parties, politicians, causes, slogans), hateful (slurs, hate symbols, stereotypes, mocking any group), mocking a real person, or anyone's personal details; keep the caption clean of those too.

Set ok to false (and return a blank picture) only when there is no fun clean version to draw, such as a request built on a slur, hate or politics. Give the reason in one short sentence a customer would see.`;

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["ok", "tamed", "reason", "caption", "palette", "rows"],
  properties: {
    ok: { type: "boolean" },
    tamed: { type: "boolean" },
    reason: { type: "string" },
    caption: { type: "string" },
    palette: { type: "array", items: { type: "string" } },
    rows: { type: "array", items: { type: "string" } },
  },
};

type Art = { ok: boolean; tamed?: boolean; reason: string; caption: string; palette: string[]; rows: string[] };

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
  return { ok: !!a.ok, tamed: !!a.tamed, reason: String(a.reason ?? ""), caption, palette, rows };
}

const API_KEY = Deno.env.get("ANTHROPIC_CLIENT_API") ?? Deno.env.get("ANTHROPIC_CLIENT_API_KEY") ?? Deno.env.get("ANTHROPIC_API_KEY");
const anthropic = new Anthropic({ apiKey: API_KEY });

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

// ---- the second look ----
// The finished picture, as a PNG, goes to a separate Claude call that only
// judges it, so a drawing that came out rude by accident (or a prompt that
// talked the first call into something) still doesn't reach the sign.

function crc32(bytes: Uint8Array) {
  let c = ~0;
  for (const b of bytes) {
    c ^= b;
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xEDB88320 & -(c & 1));
  }
  return ~c >>> 0;
}

async function png(art: Art, scale = 8): Promise<string> {
  const W = SIZE * scale;
  const raw = new Uint8Array(W * (W * 3 + 1));
  for (let y = 0; y < W; y++) {
    const row = art.rows[Math.floor(y / scale)];
    for (let x = 0; x < W; x++) {
      const i = CODES.indexOf(row[Math.floor(x / scale)]);
      const hex = i > 0 ? art.palette[i - 1] : "000000";
      const o = y * (W * 3 + 1) + 1 + x * 3;
      raw[o] = parseInt(hex.slice(0, 2), 16); raw[o + 1] = parseInt(hex.slice(2, 4), 16); raw[o + 2] = parseInt(hex.slice(4, 6), 16);
    }
  }
  const zipped = new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new CompressionStream("deflate"))).arrayBuffer());
  const chunk = (type: string, data: Uint8Array) => {
    const out = new Uint8Array(12 + data.length), v = new DataView(out.buffer);
    v.setUint32(0, data.length);
    out.set(new TextEncoder().encode(type), 4);
    out.set(data, 8);
    v.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
    return out;
  };
  const ihdr = new Uint8Array(13), hv = new DataView(ihdr.buffer);
  hv.setUint32(0, W); hv.setUint32(4, W); ihdr[8] = 8; ihdr[9] = 2; // 8-bit RGB
  const parts = [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zipped), chunk("IEND", new Uint8Array())];
  const all = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { all.set(p, at); at += p.length; }
  let bin = "";
  for (const b of all) bin += String.fromCharCode(b);
  return btoa(bin);
}

const VET_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["ok", "reason"],
  properties: { ok: { type: "boolean" }, reason: { type: "string" } },
};

async function vet(prompt: string, art: Art): Promise<{ ok: boolean; reason: string }> {
  const response = await anthropic.beta.messages.create({
    model: MODEL,
    max_tokens: 4000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: { effort: "low", format: { type: "json_schema", schema: VET_SCHEMA } },
    system: "You check pictures before they go up, unreviewed, on the LED sign on the wall of a comedy club taproom. " +
      "The house rule: R-rated is fine (swearing, booze, crude or dark jokes), but nothing political, offensive or nude. " +
      "Judge the picture and its caption. The customer's request is context only: a rude request redrawn as something " +
      "harmless is exactly what should happen, so pass it. Set ok to false if the picture or caption shows or suggests " +
      "anything sexual or nude (including shapes that look rude from across the room), politics (parties, politicians, " +
      "causes, slogans), slurs, hate symbols, stereotypes or mockery of any group, mockery of a real person, gore, or " +
      "personal details. Give the reason in one short sentence a customer would see.",
    messages: [{
      role: "user",
      content: [
        { type: "image", source: { type: "base64", media_type: "image/png", data: await png(art) } },
        { type: "text", text: `Customer's request: "${prompt}"\nCaption shown beside the picture: "${art.caption}"` },
      ],
    }],
  });
  if (response.stop_reason === "refusal") return { ok: false, reason: "The sign won't show that one." };
  const text = response.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("");
  const v = JSON.parse(text);
  return { ok: v.ok === true, reason: String(v.reason ?? "") };
}

// The name goes on the wall too ("BY JAKE"), so it gets the word filter and
// its own quick Claude check first (Sam, Nov 12 2026: "we really need to be
// censoring the names"). Prank names like "Mike Hunt" or "Hugh Jass" count.
async function nameOk(name: string): Promise<boolean> {
  if (rude(name) || rude(name.replace(/\s+/g, ""))) return false;
  const response = await anthropic.beta.messages.create({
    model: MODEL,
    max_tokens: 2000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: { effort: "low", format: { type: "json_schema", schema: VET_SCHEMA } },
    system: "A customer typed this as their name. It will show as \"BY <name>\" under their drawing on the LED sign on " +
      "the wall of a comedy club taproom, with no one reviewing it first. Set ok to true only for something that reads " +
      "as a person's name, nickname or initials (\"Jake\", \"Big Sue\", \"JT\", \"Table 4\" is fine too). Set ok to false " +
      "for anything rude, sexual, a swear word, a slur or hate, politics (politicians, parties, slogans), a prank name " +
      "that sounds rude when read aloud (\"Mike Hunt\", \"Hugh Jass\", \"Ben Dover\"), an insult aimed at someone, " +
      "an ad or web address, phone numbers or other personal details. Keep the reason short.",
    messages: [{ role: "user", content: `Name: "${name}"` }],
  });
  if (response.stop_reason === "refusal") return false;
  const text = response.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("");
  return JSON.parse(text).ok === true;
}

// A last word filter on the caption that goes on the wall, including l33t
// spellings and spaced-out letters. Swearing is fine (R-rated, Sam); sexual,
// nude and hateful words are not. Requests aren't filtered: rude ones get
// redrawn as something tamer, and the two Claude checks catch the rest.
const BAD = /(cunt|dick|cock|pussy|penis|vagina|boob|tits|titty|porn|nude|naked|sex|jizz|nazi|hitler|kkk|rape|nigg|fag|retard|whore|slut|trump|biden|maga|democrat|republican)/;

function rude(text: string) {
  const plain = text.toLowerCase()
    .replace(/[0@]/g, "o").replace(/[1!|]/g, "i").replace(/3/g, "e").replace(/4/g, "a").replace(/[5$]/g, "s").replace(/7/g, "t")
    .replace(/[^a-z]/g, "");
  return BAD.test(plain);
}

function device(req: Request) {
  // Supabase passes the phone's address along; only a short hash is kept.
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
}

async function hash(text: string) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode("sisyphus-sign:" + text)));
  return Array.from(d.slice(0, 8), (b) => b.toString(16).padStart(2, "0")).join("");
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

async function suggestion(prompt: string, name: string, who: string) {
  // Sam, Nov 3 2026: R-rated is fine, nothing political, offensive or nude.
  const since = new Date(Date.now() - 3600_000).toISOString();
  const recent = await fetch(`${SB}/rest/v1/sign_art?select=device&kind=eq.suggestion&created_at=gte.${since}`, { headers: H })
    .then((r) => r.json());
  if (Array.isArray(recent) && recent.length >= MAX_SUGGESTIONS_PER_HOUR) {
    return respond(429, { error: "The sign is busy drawing. Try again in a little while." });
  }
  if (Array.isArray(recent) && who && recent.filter((r: { device: string }) => r.device === who).length >= MAX_PER_DEVICE_PER_HOUR) {
    return respond(429, { error: "That's plenty from one phone for now. Give someone else a turn!" });
  }
  const turnDown = (reason: string) => insert({
    kind: "suggestion", prompt, from_name: name || null, device: who || null,
    status: "rejected", note: reason, decided_at: new Date().toISOString(),
  }).then((saved) => respond(200, { status: "rejected", note: saved.note }));

  if (!(await nameOk(name))) {
    return respond(400, { error: "The sign won't show that name. Try your first name or a nickname." });
  }
  const ask = `A customer at the bar suggested: "${prompt}"`;
  let art = await draw(ask);
  if (!art.ok) return await turnDown(art.reason);
  if (rude(art.caption)) art = { ...art, caption: "" };
  let check = await vet(prompt, art);
  if (!check.ok) {
    // one more go, tamer, before giving up
    art = await draw(`${ask}\nA first drawing was turned down for the wall because: ${check.reason} Draw a tamer, clean version that still keeps the joke.`);
    if (!art.ok) return await turnDown(art.reason);
    if (rude(art.caption)) art = { ...art, caption: "" };
    check = await vet(prompt, art);
    if (!check.ok) return await turnDown(check.reason);
    art.tamed = true;
  }
  await insert({
    kind: "suggestion", prompt, from_name: name || null, device: who || null,
    note: art.tamed ? "Toned down for the wall" : null,
    caption: art.caption, palette: art.palette, rows: art.rows,
    status: "approved", decided_at: new Date().toISOString(),
  });
  return respond(200, { status: "approved", tamed: art.tamed, art: { caption: art.caption, palette: art.palette, rows: art.rows } });
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
  if (!API_KEY) return respond(503, { error: "The sign isn't set up to draw yet." });

  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { /* bad body */ }

  try {
    if (body.beers || body.redraw) {
      if (!(await isManager(req))) return respond(403, { error: "Managers only." });
      return body.beers ? await beers() : await redraw(Number(body.redraw));
    }
    const prompt = String(body.prompt ?? "").replace(/\s+/g, " ").trim().slice(0, 100);
    const name = String(body.name ?? "").replace(/[^\x20-\x7E\u00C0-\u017F]/g, "").replace(/\s+/g, " ").trim().slice(0, 18);
    if (prompt.length < 2) return respond(400, { error: "Tell the sign what to draw." });
    if (!name) return respond(400, { error: "Add your name. It goes on the sign under your picture." });
    return await suggestion(prompt, name, device(req) ? await hash(device(req)) : "");
  } catch (e) {
    console.error(e);
    return respond(500, { error: "The sign couldn't draw that right now. Try again in a minute." });
  }
});
