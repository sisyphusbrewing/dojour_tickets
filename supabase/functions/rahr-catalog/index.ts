// Sisyphus - looks up RahrBSG products for the batch planner's Order tab
// (staff.sisyphusbrewing.com/brewing/, "Fill RahrBSG cart").
//
// rahrbsg.com runs on VTEX, whose public catalog API has no CORS headers, so
// the page asks this function instead. POST { skus: ["663", ...], slugs:
// ["citra-t-90-hop-pellets-11-lb", ...] } with a signed-in staff session.
// Returns { skus: { "663": { name, avail } }, slugs: { slug: [{ id, name, avail }] } }.
// Slugs are for hops, whose item changes with each crop year; the page picks one.
// Read-only public catalog data: nothing is ordered and no RahrBSG login is used.

const BASE = "https://www.rahrbsg.com/api/catalog_system/pub/products/search";
const MAX = 80;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });
}

type Item = { id: string; name: string; avail: number };

// deno-lint-ignore no-explicit-any
function items(product: any): Item[] {
  return (product?.items ?? []).map((i: any) => ({
    id: String(i.itemId),
    name: String(i.nameComplete || i.name || ""),
    avail: Number(i.sellers?.[0]?.commertialOffer?.AvailableQuantity) || 0,
  }));
}

async function get(url: string) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`RahrBSG ${r.status}`);
  return await r.json();
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return respond(405, { error: "POST only" });
  let body: { skus?: unknown; slugs?: unknown };
  try { body = await req.json(); } catch { return respond(400, { error: "Bad JSON" }); }

  const skus = [...new Set((Array.isArray(body.skus) ? body.skus : []).map(String))].filter((s) => /^\d{1,8}$/.test(s));
  const slugs = [...new Set((Array.isArray(body.slugs) ? body.slugs : []).map(String))].filter((s) => /^[a-z0-9-]{1,120}$/.test(s));
  if (skus.length + slugs.length > MAX) return respond(400, { error: "Too many items" });

  try {
    const outSkus: Record<string, Item> = {};
    const outSlugs: Record<string, Item[]> = {};
    await Promise.all([
      ...skus.map(async (s) => {
        const d = await get(`${BASE}?fq=skuId:${s}`);
        const it = items(d?.[0]).find((i) => i.id === s);
        if (it) outSkus[s] = it;
      }),
      ...slugs.map(async (s) => {
        const d = await get(`${BASE}/${s}/p`);
        if (d?.[0]) outSlugs[s] = items(d[0]);
      }),
    ]);
    return respond(200, { skus: outSkus, slugs: outSlugs });
  } catch (e) {
    return respond(502, { error: String((e as Error).message || e) });
  }
});
