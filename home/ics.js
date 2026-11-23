// Reads iCal (.ics) calendars for the home screens: one event list for a
// date range, with repeating events expanded. Shared by the kitchen display
// (/home/kitchen/); copied from the wall board's own copy in /home/.
function dayKey(d) { return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate(); }
function icsDate(v, params) {
  var m = v.match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?/);
  if (!m) return null;
  if (!m[4]) return { d: new Date(+m[1], +m[2] - 1, +m[3]), allDay: true };
  if (m[7]) return { d: new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])), allDay: false };
  return { d: new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]), allDay: false };   // TZID times: the screen is in Central too
}

function parseIcs(text, from, to) {
  var lines = text.replace(/\r?\n[ \t]/g, '').split(/\r?\n/), out = [], ev = null, recurIds = {};
  lines.forEach(function (ln) {
    if (ln === 'BEGIN:VEVENT') { ev = { ex: [] }; return; }
    if (ln === 'END:VEVENT') { if (ev && ev.start) out.push(ev); ev = null; return; }
    if (!ev) return;
    var c = ln.indexOf(':'); if (c < 0) return;
    var key = ln.slice(0, c).split(';')[0], val = ln.slice(c + 1);
    if (key === 'DTSTART') ev.start = icsDate(val);
    else if (key === 'SUMMARY') ev.title = val.replace(/\\,/g, ',').replace(/\\;/g, ';').replace(/\\n/g, ' ');
    else if (key === 'RRULE') ev.rrule = val;
    else if (key === 'EXDATE') val.split(',').forEach(function (x) { var e = icsDate(x); if (e) ev.ex.push(dayKey(e.d)); });
    else if (key === 'RECURRENCE-ID') { ev.recurId = icsDate(val); }
    else if (key === 'UID') ev.uid = val;
    else if (key === 'STATUS') ev.status = val;
  });
  // Moved or cancelled single instances replace that day of the series.
  out.forEach(function (e) { if (e.recurId) recurIds[e.uid + dayKey(e.recurId.d)] = 1; });
  var res = [];
  out.forEach(function (e) {
    if (e.status === 'CANCELLED') return;
    var occ = e.rrule ? expand(e, to) : [e.start.d];
    occ.forEach(function (d) {
      if (d < from || d >= to) return;
      if (e.rrule && (e.ex.indexOf(dayKey(d)) !== -1 || recurIds[e.uid + dayKey(d)])) return;
      res.push({ at: d, allDay: e.start.allDay, title: e.title || '(busy)' });
    });
  });
  return res;
}

// DAILY / WEEKLY (BYDAY) / MONTHLY / YEARLY with INTERVAL, COUNT and UNTIL: enough for family calendars.
function expand(e, to) {
  var r = {}; e.rrule.split(';').forEach(function (p) { var kv = p.split('='); r[kv[0]] = kv[1]; });
  var step = +(r.INTERVAL || 1), until = r.UNTIL ? icsDate(r.UNTIL).d : null, count = r.COUNT ? +r.COUNT : 1e9;
  var days = r.BYDAY ? r.BYDAY.split(',').map(function (x) { return ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'].indexOf(x.slice(-2)); }) : null;
  var s = e.start.d, out = [], n = 0, cur = new Date(s);
  for (var guard = 0; guard < 4000 && cur < to && n < count; guard++) {
    if (r.FREQ === 'WEEKLY' && days) {
      var wk = new Date(cur); wk.setDate(wk.getDate() - wk.getDay());
      for (var k = 0; k < 7; k++) {
        var d = new Date(wk); d.setDate(wk.getDate() + k); d.setHours(s.getHours(), s.getMinutes());
        if (days.indexOf(d.getDay()) === -1 || d < s) continue;
        if ((until && d > until) || n >= count) return out;
        out.push(d); n++;
      }
      cur.setDate(cur.getDate() - cur.getDay() + 7 * step);
      continue;
    }
    if (until && cur > until) break;
    out.push(new Date(cur)); n++;
    if (r.FREQ === 'DAILY') cur.setDate(cur.getDate() + step);
    else if (r.FREQ === 'WEEKLY') cur.setDate(cur.getDate() + 7 * step);
    else if (r.FREQ === 'MONTHLY') cur.setMonth(cur.getMonth() + step);
    else if (r.FREQ === 'YEARLY') cur.setFullYear(cur.getFullYear() + step);
    else break;
  }
  return out;
}
