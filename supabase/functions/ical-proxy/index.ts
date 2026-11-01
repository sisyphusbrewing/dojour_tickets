// Sisyphus - lets Sam's home screen (/home/) read a private calendar feed.
//
// GET ?url=<secret iCal address>   returns the .ics text with CORS headers.
// GET ?k=<board key>                returns every calendar saved for that board
//                                   in boards.ts, one after another, so the
//                                   screen's URL stays short enough to type.
//
// Calendar sites don't send CORS headers, so the page can't fetch them itself.
// Only calendar hosts pass through, so this can't be used as an open proxy.
// Secret addresses live in the screen's URL or in boards.ts, which is
// deployed with the function but never committed (see boards.example.ts).

import { BOARDS } from "./boards.ts";

const ALLOWED = [
  /^calendar\.google\.com$/,
  /^p\d+-caldav\.icloud\.com$/,
  /^outlook\.(live|office365)\.com$/,
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  const params = new URL(req.url).searchParams;
  const key = params.get("k");
  const urls = key ? BOARDS[key] : [params.get("url") ?? ""];
  if (!urls) return new Response("unknown board", { status: 404, headers: CORS });

  const targets: URL[] = [];
  for (const raw of urls) {
    let target: URL;
    try {
      target = new URL(raw);
    } catch {
      return new Response("bad url", { status: 400, headers: CORS });
    }
    if (target.protocol === "webcal:") target = new URL(target.href.replace(/^webcal:/, "https:"));
    if (target.protocol !== "https:" || !ALLOWED.some((re) => re.test(target.hostname))) {
      return new Response("not a calendar address", { status: 403, headers: CORS });
    }
    targets.push(target);
  }

  const results = await Promise.all(targets.map(async (t) => {
    const res = await fetch(t.href, { headers: { "User-Agent": "sisyphus-home-screen" } });
    return res.ok ? await res.text() : "";
  }));
  const body = results.join("\r\n");
  return new Response(body, {
    status: body ? 200 : 502,
    headers: { ...CORS, "Content-Type": "text/calendar; charset=utf-8", "Cache-Control": "max-age=300" },
  });
});
