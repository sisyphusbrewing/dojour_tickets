// Sisyphus - lets Sam's home screen (/home/) read a private calendar feed.
//
// GET ?url=<secret iCal address>   returns the .ics text with CORS headers.
//
// Calendar sites don't send CORS headers, so the page can't fetch them itself.
// Only calendar hosts pass through, so this can't be used as an open proxy.
// The secret address lives in the screen's URL, never in this repo.

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
  let target: URL;
  try {
    target = new URL(new URL(req.url).searchParams.get("url") ?? "");
  } catch {
    return new Response("bad url", { status: 400, headers: CORS });
  }
  if (target.protocol === "webcal:") target = new URL(target.href.replace(/^webcal:/, "https:"));
  if (target.protocol !== "https:" || !ALLOWED.some((re) => re.test(target.hostname))) {
    return new Response("not a calendar address", { status: 403, headers: CORS });
  }
  const res = await fetch(target.href, { headers: { "User-Agent": "sisyphus-home-screen" } });
  const body = await res.text();
  return new Response(body, {
    status: res.ok ? 200 : 502,
    headers: { ...CORS, "Content-Type": "text/calendar; charset=utf-8", "Cache-Control": "max-age=300" },
  });
});
