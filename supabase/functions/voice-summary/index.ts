// Sisyphus - voice notes: Claude reads a transcript and writes the summary.
//
// Sam (or Lindsey) records a conversation or meeting on /voice/. The "Voice notes" GitHub
// Action (voice_notes.py) transcribes it, saves the transcript on the
// voice_notes row, then calls this function with { id }. Claude writes a
// title, a summary, decisions and to-dos; this saves them on the row and
// returns them so the action can email sam@.
//
// It reads and writes the row with the caller's own key, so only the action
// (service role) or the person who recorded the note can use it; anyone else
// sees no row. Needs the Claude API key secret that sign-art already uses: ANTHROPIC_CLIENT_API (or ANTHROPIC_API_KEY).

import Anthropic from "npm:@anthropic-ai/sdk@1.3.0";

const MODEL = "claude-opus-5-5";
const SB = Deno.env.get("SUPABASE_URL") ?? "";
const API_KEY = Deno.env.get("ANTHROPIC_CLIENT_API") ?? Deno.env.get("ANTHROPIC_CLIENT_API_KEY") ?? Deno.env.get("ANTHROPIC_API_KEY");
const anthropic = new Anthropic({ apiKey: API_KEY });

// Written for whoever recorded it: their name and a line about them come from
// voice_users (Sam's has the club glossary; Lindsey's notes are her own).
function systemFor(name: string, context: string) {
  return `You turn a recorded conversation into notes for ${name}. ${context}

${name} recorded it on a phone; the transcript comes from speech recognition, so it has no speaker names and some words will be misheard. Work out who is talking from context where you can, and fix obvious mishearings of names and terms.

Write for ${name} reading on a phone later: plain words, first names, no filler, no corporate language. ${name} is "you" in the notes. Keep every concrete fact that matters later: numbers, prices, dates, names, phone numbers, promises. Only list to-dos that someone actually agreed to or clearly needs to do; don't invent work. If the recording is just ${name} thinking out loud, treat the ideas as notes and pull out anything ${name} said they'd do. If it is mostly silence or noise, say so in the summary and leave the lists empty.`;
}

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["title", "gist", "summary", "decisions", "todos_sam", "todos_others", "key_details", "people"],
  properties: {
    title: { type: "string", description: "A short title, 3 to 8 words, like 'Grace: December staffing and crowlers'" },
    gist: { type: "string", description: "One sentence: what this conversation was and the main outcome" },
    summary: { type: "string", description: "The summary in short paragraphs separated by blank lines. As long as the conversation needs, no longer." },
    decisions: { type: "array", items: { type: "string" }, description: "What was decided" },
    todos_sam: {
      type: "array",
      items: {
        type: "object", additionalProperties: false, required: ["task", "when"],
        properties: { task: { type: "string" }, when: { type: "string", description: "Due date or timing if said, else empty" } },
      },
      description: "Things the person who recorded it said they'd do or need to do",
    },
    todos_others: {
      type: "array",
      items: {
        type: "object", additionalProperties: false, required: ["who", "task", "when"],
        properties: { who: { type: "string" }, task: { type: "string" }, when: { type: "string" } },
      },
      description: "Things other people agreed to do",
    },
    key_details: { type: "array", items: { type: "string" }, description: "Numbers, prices, dates, contacts and facts worth keeping" },
    people: { type: "array", items: { type: "string" }, description: "Who was in the conversation or talked about, first names where known" },
  },
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function db(caller: Request, path: string, init: RequestInit = {}) {
  const auth = caller.headers.get("authorization") ?? "";
  const apikey = caller.headers.get("apikey") ?? auth.replace(/^Bearer\s+/i, "");
  return await fetch(`${SB}/rest/v1/${path}`, {
    ...init,
    headers: { apikey, Authorization: auth, "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return respond(405, { error: "POST only" });
  if (!API_KEY) return respond(503, { error: "No Claude API key secret is set." });

  let id = "", effort = "medium";
  try {
    const body = await req.json();
    id = String(body.id ?? "");
    if (["low", "medium", "high"].includes(body.effort)) effort = body.effort;
  } catch {
    return respond(400, { error: "Bad request" });
  }

  const r = await db(req, `voice_notes?id=eq.${encodeURIComponent(id)}&select=id,label,created_at,duration_s,transcript,created_by`);
  const rows = r.ok ? await r.json() : [];
  if (!rows.length) return respond(404, { error: "No such note" });
  const note = rows[0];
  if (!note.transcript || !String(note.transcript).trim()) return respond(400, { error: "No transcript yet" });

  let who = { name: "Sam", context: "Sam Harriman owns Sisyphus, a comedy club and brewery in Minneapolis." };
  if (note.created_by) {
    const v = await db(req, `voice_users?user_id=eq.${note.created_by}&select=name,context`);
    const vr = v.ok ? await v.json() : [];
    if (vr.length) who = vr[0];
  }

  const when = new Date(note.created_at).toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "full", timeStyle: "short" });
  const ask = `Recorded ${when}, about ${Math.round((note.duration_s ?? 0) / 60)} minutes.` +
    (note.label ? ` ${who.name}'s label for it: "${note.label}".` : "") +
    `\n\n<transcript>\n${note.transcript}\n</transcript>`;

  const response = await anthropic.beta.messages.create({
    model: MODEL,
    max_tokens: 16000,
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
    output_config: { effort, format: { type: "json_schema", schema: SCHEMA } },
    system: systemFor(who.name, who.context),
    messages: [{ role: "user", content: ask }],
  // deno-lint-ignore no-explicit-any
  } as any);

  if (response.stop_reason === "refusal") return respond(422, { error: "Claude declined to summarize this one." });
  const text = response.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("");
  let summary;
  try {
    summary = JSON.parse(text);
  } catch {
    return respond(502, { error: `Summary was not JSON (stop: ${response.stop_reason})` });
  }

  await db(req, `voice_notes?id=eq.${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({ title: summary.title, summary }),
  });
  return respond(200, { ok: true, summary });
});
