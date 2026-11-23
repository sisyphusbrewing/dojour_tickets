// Sisyphus - one person's shifts as a calendar their phone subscribes to.
//
// GET ?t=<private code>   returns an .ics calendar of that person's posted
//                         shifts (Apple Calendar, Google Calendar, Outlook).
//
// A staff member asked (Nov 23 2026) to "sync our schedule from the staff
// portal to our iCal or Google Calendar". The Schedule's My settings tab hands
// each person their link (my_calendar_feed()); their calendar app checks it on
// its own every so often, so posted, changed and removed shifts follow along.
// The database decides what the link shows (schedule_calendar(), service key
// only). Deploy with "Verify JWT" off: calendar apps send no login.

const SITE = "https://staff.sisyphusbrewing.com/schedule/";
const PLACE = "Sisyphus, 712 Ontario Ave W, Minneapolis, MN";

// Minneapolis time, so each shift lands at the right hour wherever the phone is.
const ZONE = [
  "BEGIN:VTIMEZONE",
  "TZID:America/Chicago",
  "BEGIN:DAYLIGHT",
  "TZOFFSETFROM:-0600",
  "TZOFFSETTO:-0500",
  "TZNAME:CDT",
  "DTSTART:19700308T020000",
  "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
  "END:DAYLIGHT",
  "BEGIN:STANDARD",
  "TZOFFSETFROM:-0500",
  "TZOFFSETTO:-0600",
  "TZNAME:CST",
  "DTSTART:19701101T020000",
  "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
  "END:STANDARD",
  "END:VTIMEZONE",
];

type Shift = {
  id: number; position: string; note: string; up_for_grabs: boolean; until_close: boolean;
  starts: string; ends: string; updated: string; with: string[];
};

// Calendar text: commas, semicolons, backslashes and line breaks are escaped.
function esc(s: string) {
  return String(s ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

// Lines longer than 75 bytes are folded onto the next line with a leading space.
function fold(line: string) {
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 75) return line;
  const out: string[] = [];
  let cur = "", size = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > (out.length ? 74 : 75)) { out.push(cur); cur = ""; size = 0; }
    cur += ch; size += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

export function buildCalendar(shifts: Shift[], now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Sisyphus//Staff schedule//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Sisyphus shifts",
    "X-WR-TIMEZONE:America/Chicago",
    "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    "X-PUBLISHED-TTL:PT1H",
    ...ZONE,
  ];
  for (const s of shifts) {
    const title = `Sisyphus: ${s.position}${s.up_for_grabs ? " (up for grabs)" : ""}`;
    const about: string[] = [];
    if (s.until_close) about.push("Until close.");
    if (s.note) about.push(s.note);
    if (s.with && s.with.length) about.push(`Also on: ${s.with.join(", ")}`);
    about.push(`Swap or give it up: ${SITE}`);
    lines.push(
      "BEGIN:VEVENT",
      `UID:shift-${s.id}@staff.sisyphusbrewing.com`,
      `DTSTAMP:${stamp}`,
      `LAST-MODIFIED:${s.updated}`,
      `DTSTART;TZID=America/Chicago:${s.starts}`,
      `DTEND;TZID=America/Chicago:${s.ends}`,
      `SUMMARY:${esc(title)}`,
      `LOCATION:${esc(PLACE)}`,
      `DESCRIPTION:${esc(about.join("\n"))}`,
      `URL:${SITE}`,
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

Deno.serve(async (req) => {
  if (req.method !== "GET" && req.method !== "HEAD") return new Response("GET only", { status: 405 });
  const token = new URL(req.url).searchParams.get("t") ?? "";
  if (!/^[a-f0-9]{32}$/.test(token)) return new Response("Not a calendar link", { status: 404 });

  const url = Deno.env.get("SUPABASE_URL") ?? "";
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const r = await fetch(`${url}/rest/v1/rpc/schedule_calendar`, {
    method: "POST",
    headers: { apikey: service, Authorization: `Bearer ${service}`, "Content-Type": "application/json" },
    body: JSON.stringify({ p_token: token }),
  });
  if (!r.ok) {
    console.error(`schedule_calendar failed (${r.status})`);
    return new Response("Try again soon", { status: 503 });
  }
  const cal = await r.json();
  if (!cal) return new Response("This calendar link has been switched off", { status: 404 });

  return new Response(buildCalendar(cal.shifts ?? []), {
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": 'inline; filename="sisyphus-shifts.ics"',
      "Cache-Control": "no-cache",
    },
  });
});
