// Sisyphus - customers swap their own website tickets (exchange/index.html,
// on the site at sisyphusbrewing.com/pages/exchange).
//
//   { action: "lookup", order, email }   the order's upcoming tickets + the
//                                        showtimes they can move to
//   { action: "swap", order, email, unique_id, variant_id, tickets }
//                                        saves the request and starts the
//                                        "Ticket exchange" action
//   { action: "status", id }             how that request is going
//
// Order number + email is the key, like a store's order-status page. Only the
// service key reads the tables. The swap itself (Shopify order edit, door list,
// email) is exchange_ticket.py. Same price or cheaper only, and only to another
// showtime of the same product (Sam, Oct 28-29 2026).
// Needs the GITHUB_TOKEN secret, like run-workflow.

const REPO = "sisyphusbrewing/dojour_tickets";
const WORKFLOW = "exchange_ticket.yml";
const CUTOFF_HOURS = 48; // same as exchange_ticket.py (Sam, Oct 30 2026)
const REFRESH_COOLDOWN_MS = 3 * 60 * 1000;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}

const URL_ = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const HEADERS = { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, "Content-Type": "application/json" };

async function db(path: string, init: RequestInit = {}) {
  const r = await fetch(`${URL_}/rest/v1/${path}`, { ...init, headers: { ...HEADERS, ...(init.headers ?? {}) } });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}

async function dispatch(inputs: Record<string, string>) {
  const gh = Deno.env.get("GITHUB_TOKEN");
  if (!gh) throw new Error("GITHUB_TOKEN secret is not set in Supabase.");
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${gh}`, "Content-Type": "application/json", "User-Agent": "sisyphus-exchange" },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  if (r.status !== 204) throw new Error(`GitHub said ${r.status}: ${await r.text()}`);
}

function orderName(raw: unknown) {
  const digits = String(raw ?? "").replace(/[^0-9]/g, "");
  return digits ? `#${digits}` : "";
}

type Showtime = { variant_id: number; product_id: number; show_title: string; date_text: string; ticket_type: string | null; starts_at: string; price: number; seats_left: number };

// The customer's upcoming website tickets on that order, with what each cost.
async function findLines(order: string, email: string) {
  const rows = await db(`tickets?order_name=eq.${encodeURIComponent(order)}&source=eq.Website&select=unique_id,show_title,show_date,tickets,ticket_type,email,variant_id,checked_in_count`);
  const mine = (rows ?? []).filter((r: { email?: string }) => (r.email ?? "").trim().toLowerCase() === email);
  const ids = mine.map((r: { variant_id?: number }) => r.variant_id).filter(Boolean);
  const times: Showtime[] = ids.length ? await db(`exchange_showtimes?variant_id=in.(${ids.join(",")})&select=*`) : [];
  const byVariant = new Map(times.map((t) => [Number(t.variant_id), t]));
  const soon = Date.now() + CUTOFF_HOURS * 3600e3;
  const pending = mine.length
    ? await db(`ticket_exchanges?from_unique_id=in.(${mine.map((r: { unique_id: string }) => `"${r.unique_id}"`).join(",")})&status=in.(queued,working)&select=from_unique_id`)
    : [];
  const busy = new Set((pending ?? []).map((p: { from_unique_id: string }) => p.from_unique_id));
  return mine.map((r: { unique_id: string; show_title: string; show_date: string; tickets: number; ticket_type: string | null; variant_id: number; checked_in_count: number }) => {
    const t = byVariant.get(Number(r.variant_id));
    let blocked = "";
    if (!t) blocked = "This show isn't on sale anymore, so it can't be swapped here.";
    else if (Date.parse(t.starts_at) <= soon) blocked = `Swaps close ${CUTOFF_HOURS} hours before the show.`;
    if ((r.checked_in_count ?? 0) > 0) blocked = "Already checked in.";
    if (busy.has(r.unique_id)) blocked = "A swap for these is already in progress.";
    return {
      unique_id: r.unique_id, show_title: r.show_title, show_date: r.show_date, tickets: r.tickets,
      ticket_type: r.ticket_type, variant_id: r.variant_id, price: t ? Number(t.price) : null, blocked,
      product_id: t ? Number(t.product_id) : null,
    };
  });
}

async function showtimes(): Promise<Showtime[]> {
  const after = new Date(Date.now() + CUTOFF_HOURS * 3600e3).toISOString();
  return await db(`exchange_showtimes?starts_at=gt.${encodeURIComponent(after)}&seats_left=gt.0&select=variant_id,product_id,show_title,date_text,ticket_type,starts_at,price,seats_left&order=starts_at,show_title,price`);
}

// A brand-new order isn't on the door list until the next sync; ask for a quick one.
async function refreshSoon() {
  const state = await db("exchange_state?id=eq.1&select=refreshed_at");
  const last = state?.[0]?.refreshed_at ? Date.parse(state[0].refreshed_at) : 0;
  if (Date.now() - last < REFRESH_COOLDOWN_MS) return;
  await db("exchange_state?id=eq.1", { method: "PATCH", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ refreshed_at: new Date().toISOString() }) });
  await dispatch({ exchange_id: "" });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });

  let p: Record<string, unknown>;
  try {
    p = await req.json();
  } catch {
    return respond(400, { error: "Bad request" });
  }

  try {
    if (p.action === "status") {
      const id = String(p.id ?? "");
      if (!/^[0-9a-f-]{36}$/.test(id)) return respond(400, { error: "Bad id" });
      const rows = await db(`ticket_exchanges?id=eq.${id}&select=status,message`);
      if (!rows?.length) return respond(404, { error: "Not found" });
      return respond(200, rows[0]);
    }

    const order = orderName(p.order);
    const email = String(p.email ?? "").trim().toLowerCase();
    if (!order || !email.includes("@")) return respond(400, { error: "We need the order number and the email you used." });
    const lines = await findLines(order, email);

    if (p.action === "lookup") {
      if (!lines.length) {
        try { await refreshSoon(); } catch (e) { console.error(e); }
        return respond(404, { error: "not_found" });
      }
      return respond(200, { order, lines, showtimes: await showtimes() });
    }

    if (p.action === "swap") {
      const line = lines.find((l: { unique_id: string }) => l.unique_id === p.unique_id);
      if (!line) return respond(404, { error: "We couldn't find those tickets on the order." });
      if (line.blocked) return respond(409, { error: line.blocked });
      const qty = Number(p.tickets ?? line.tickets);
      if (!Number.isInteger(qty) || qty < 1 || qty > line.tickets) return respond(400, { error: "Pick how many tickets to move." });
      const target = (await showtimes()).find((t) => Number(t.variant_id) === Number(p.variant_id));
      if (!target) return respond(409, { error: "That showtime isn't available anymore. Pick another." });
      if (target.seats_left < qty) return respond(409, { error: "Not enough seats left for that showtime." });
      if (Number(target.product_id) !== line.product_id) return respond(409, { error: "Tickets can only move to another night of the same show." });
      if (Number(target.variant_id) === Number(line.variant_id)) return respond(400, { error: "Those are the tickets you already have." });
      if (line.price !== null && Number(target.price) > Number(line.price) + 0.001) {
        return respond(409, { error: "Those cost more than what you have. Email ticketing@sisyphusbrewing.com and we'll sort it out." });
      }
      const diff = line.price === null ? null : Math.round((Number(target.price) - Number(line.price)) * qty * 100) / 100;
      const [row] = await db("ticket_exchanges?select=id", {
        method: "POST", headers: { Prefer: "return=representation" },
        body: JSON.stringify({
          order_name: order, email, from_unique_id: line.unique_id, from_show: `${line.show_title}, ${line.show_date}`,
          to_variant_id: target.variant_id, to_show: `${target.show_title}, ${target.date_text}`, tickets: qty, price_change: diff,
        }),
      });
      try {
        await dispatch({ exchange_id: row.id });
      } catch (e) {
        await db(`ticket_exchanges?id=eq.${row.id}`, { method: "PATCH", body: JSON.stringify({ status: "failed", message: "Couldn't start the swap. Try again in a minute." }) });
        throw e;
      }
      return respond(200, { id: row.id });
    }

    return respond(400, { error: "Unknown action" });
  } catch (e) {
    console.error(e);
    return respond(500, { error: "Something broke on our end. Try again, or email ticketing@sisyphusbrewing.com." });
  }
});
