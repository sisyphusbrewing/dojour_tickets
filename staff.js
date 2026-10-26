// Shared by the door page (index.html) and the manager page (manager/).
// Sign-in, the guest list cards, and small helpers.

var SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co";
var SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ";
var LOGIN_DOMAIN = "sisyphusbrewing.com";

var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
window.supabaseClient = sb;

function $(id) { return document.getElementById(id); }

// Guest names and emails come from public checkout forms, so they must never
// be inserted as raw HTML.
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
// Safely embed a value as a JS string argument inside an onclick="..." attribute.
function jsArg(value) {
  return escapeHtml(JSON.stringify(String(value == null ? '' : value)));
}

// Staff type a username ("rjoseph"); the login is rjoseph@sisyphusbrewing.com.
function loginToEmail(login) {
  var v = String(login || '').trim().toLowerCase();
  return v.indexOf('@') === -1 ? v + '@' + LOGIN_DOMAIN : v;
}

var toastTimer = null;
function toast(msg, bad) {
  var el = $('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle('bad', !!bad);
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.classList.add('hidden'); }, bad ? 4000 : 2200);
}

var audioCtx = null;
function chime(ok) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = audioCtx.createOscillator();
    var gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.frequency.setValueAtTime(ok ? 880 : 300, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.15);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.15);
  } catch (e) {}
}

// Turns "Sat, Apr 3 • 7:00 PM" into a timestamp. When no year is written,
// the weekday decides it: Apr 3 is a Saturday in 2027, not 2026.
function parseShowDateToMillis(str) {
  if (!str) return 0;
  var months = { jan:0, feb:1, mar:2, apr:3, may:4, jun:5, jul:6, aug:7, sep:8, oct:9, nov:10, dec:11 };
  var weekdays = { sun:0, mon:1, tue:2, wed:3, thu:4, fri:5, sat:6 };
  var md = str.match(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b/i);
  if (!md) return 0;
  var month = months[md[1].toLowerCase().slice(0, 3)];
  var day = parseInt(md[2], 10);
  var hour = 19, minute = 0;
  var tm = str.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i);
  if (tm) {
    hour = parseInt(tm[1], 10) % 12;
    minute = tm[2] ? parseInt(tm[2], 10) : 0;
    if (tm[3].toLowerCase() === 'pm') hour += 12;
  }
  var ym = str.match(/\b(20\d{2})\b/);
  if (ym) return new Date(parseInt(ym[1], 10), month, day, hour, minute).getTime();
  var now = new Date();
  var candidates = [now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map(function (y) {
    return new Date(y, month, day, hour, minute);
  }).filter(function (d) { return d.getMonth() === month; });   // drops Feb 29 in non-leap years
  var wd = str.match(/^\s*(Sun|Mon|Tue|Wed|Thu|Fri|Sat)/i);
  if (wd) {
    var target = weekdays[wd[1].toLowerCase()];
    var matching = candidates.filter(function (d) { return d.getDay() === target; });
    if (matching.length) candidates = matching;
  }
  if (!candidates.length) return 0;
  var floor = now.getTime() - 60 * 24 * 60 * 60 * 1000;
  var upcoming = candidates.filter(function (d) { return d.getTime() >= floor; });
  var pick = upcoming.length ? upcoming[0] : candidates[candidates.length - 1];
  return pick.getTime();
}

// "Sat, Oct 17 • 7:00 PM" -> "7:00 PM"
function showTime(showDate) {
  var parts = String(showDate || '').split('•');
  return (parts[1] || parts[0]).trim();
}

// ---------- Guest list ----------
// The page defines checkIn(id, count) and, on the manager page, removeComp(id).

function guestCard(t, opts) {
  var tickets = t.tickets || 1;
  var inCount = t.checked_in_count || 0;
  var done = inCount >= tickets;
  var isComp = t.source === 'Comp';
  var id = jsArg(t.unique_id);
  var type = (t.ticket_type || '').trim();
  var lower = type.toLowerCase();
  var vip = /vip|premium|reserved/.test(lower);
  var vipLabel = lower.indexOf('vip') !== -1 ? 'VIP' : (lower.indexOf('premium') !== -1 ? 'Premium' : 'Reserved');

  var act;
  if (tickets === 1) {
    act = '<button class="in-btn' + (done ? ' is-in' : '') + '" onclick="checkIn(' + id + ',' + (done ? 0 : 1) + ')">' +
      (done ? '✓ In' : 'Check in') + '</button>';
  } else {
    act = '<div class="stepper' + (done ? ' full' : '') + '">' +
      '<button aria-label="One fewer" onclick="checkIn(' + id + ',' + Math.max(0, inCount - 1) + ')">−</button>' +
      '<span>' + inCount + '/' + tickets + '</span>' +
      '<button class="plus" aria-label="One more" onclick="checkIn(' + id + ',' + Math.min(tickets, inCount + 1) + ')">+</button>' +
    '</div>';
  }

  var tags = '';
  if (vip) tags += '<span class="tag vip" title="' + escapeHtml(type) + '">★ ' + vipLabel + '</span>';
  else if (type && lower !== 'general admission') tags += '<span class="tag">' + escapeHtml(type) + '</span>';
  if (isComp) tags += '<span class="tag comp">Comp</span>';

  var sub = '';
  if (isComp) {
    var note = String(t.email || '').replace(/^Comp:?\s*/, '');
    if (note) sub = escapeHtml(note);
  } else if (opts.showEmail && t.email) {
    sub = escapeHtml(t.email);
  }

  return '<div class="guest' + (done ? ' done' : (inCount ? ' partial' : '')) + (vip && !done ? ' vip' : '') + '">' +
    '<div class="g-main">' +
      '<div class="g-name">' + (done ? '<span class="tick">✓</span>' : '') + escapeHtml(t.guest_name || 'No name') + '</div>' +
      (sub ? '<div class="g-sub">' + sub + '</div>' : '') +
      '<div class="g-meta">' + tags +
        '<span>' + tickets + ' ticket' + (tickets > 1 ? 's' : '') + (isComp ? '' : ' · ' + escapeHtml(t.source || '')) + '</span>' +
        (isComp && opts.removeComps ? '<button class="btn-link" onclick="removeComp(' + id + ')">Remove</button>' : '') +
      '</div>' +
    '</div>' +
    '<div class="g-act">' + act + '</div>' +
  '</div>';
}

// opts: { query, showDoneOpen, showEmail, removeComps, toggleFn }
function renderGuests(container, list, opts) {
  var query = (opts.query || '').toLowerCase().trim();
  if ((!list || !list.length) && !query) {
    container.innerHTML = '<div class="empty"><b>Nobody on the list yet</b>Tap Sync if a sale just came in.</div>';
    return;
  }
  var filtered = (list || []).filter(function (t) {
    return (t.guest_name || '').toLowerCase().indexOf(query) !== -1 ||
      (t.email || '').toLowerCase().indexOf(query) !== -1;
  });
  if (!filtered.length) {
    container.innerHTML = '<div class="empty"><b>No one named “' + escapeHtml(query) + '”</b>' +
      (list && list.length ? 'Try a last name, or part of their email.' : 'Nobody on this show’s list yet.') + '</div>' +
      (opts.otherShows ? '<div id="otherShows">' + (otherCache.key === otherKey(opts.otherShows, query) ? otherCache.html : '') + '</div>' : '');
    if (opts.otherShows) findOnOtherShows(opts.otherShows, query);
    return;
  }
  var waiting = filtered.filter(function (t) { return (t.checked_in_count || 0) < (t.tickets || 1); });
  var inside = filtered.filter(function (t) { return (t.checked_in_count || 0) >= (t.tickets || 1); });
  var open = query ? true : !!opts.showDoneOpen;
  var heads = function (arr) { return arr.reduce(function (a, t) { return a + (t.tickets || 1) - (t.checked_in_count || 0); }, 0); };

  var html = '';
  if (waiting.length) {
    html += '<div class="band-row"><span class="band">Waiting</span><span class="band-note">' + heads(waiting) + ' people · ' + waiting.length + ' orders</span></div>' +
      '<div class="guests">' + waiting.map(function (t) { return guestCard(t, opts); }).join('') + '</div>';
  } else if (!query) {
    html += '<div class="all-in"><b>Everyone’s in</b>One must imagine the bouncer happy.</div>';
  }
  if (inside.length) {
    html += '<div class="band-row"><button class="band" onclick="' + opts.toggleFn + '()">Checked in ' + (open ? '▾' : '▸') + '</button>' +
      '<span class="band-note">' + inside.length + ' orders</span></div>' +
      (open ? '<div class="guests">' + inside.map(function (t) { return guestCard(t, opts); }).join('') + '</div>' : '');
  }
  container.innerHTML = html;
}

// ---------- Same comic, other shows ----------
// Callers mix up dates. When a search finds no one on this show, look on the
// same comic's other shows (a renamed show counts too, see show_family()).
// other: { show_date, show_title, canOpen(show) -> bool, openFn: 'name' }
var otherTimer = null, otherSeq = 0;
var otherCache = { key: null, html: '' };   // so the 20-second refresh doesn't flicker
function otherKey(other, query) { return other.show_date + '|' + other.show_title + '|' + query; }
function findOnOtherShows(other, query) {
  clearTimeout(otherTimer);
  var seq = ++otherSeq;
  if (query.length < 2) return;
  otherTimer = setTimeout(async function () {
    var res = await sb.rpc('other_show_matches', { p_show_date: other.show_date, p_show_title: other.show_title, p_query: query });
    if (seq !== otherSeq || !$('otherShows')) return;   // the search changed while loading
    function show(html) { otherCache = { key: otherKey(other, query), html: html }; $('otherShows').innerHTML = html; }
    if (res.error) { show('<p class="help other-note">Couldn’t check the other shows.</p>'); return; }
    var rows = (res.data || []).slice().sort(function (a, b) {
      return parseShowDateToMillis(a.show_date) - parseShowDateToMillis(b.show_date);
    });
    if (!rows.length) {
      show('<p class="help other-note">Not on any other ' + escapeHtml(other.show_title) + ' show either.</p>');
      return;
    }
    var groups = [];
    rows.forEach(function (t) {
      var g = groups[groups.length - 1];
      if (!g || g.show_date !== t.show_date || g.show_title !== t.show_title) {
        g = { show_date: t.show_date, show_title: t.show_title, rows: [] };
        groups.push(g);
      }
      g.rows.push(t);
    });
    show('<div class="band-row"><span class="band">Other shows</span><span class="band-note">Wrong date, maybe</span></div>' +
      groups.map(function (g) {
        var title = g.show_title !== other.show_title ? ' · ' + escapeHtml(g.show_title) : '';
        var open = other.canOpen && other.canOpen(g)
          ? '<button class="btn btn-sm" onclick="' + other.openFn + '(' + jsArg(g.show_date) + ',' + jsArg(g.show_title) + ')">Go to show</button>' : '';
        return '<div class="other-show"><div class="other-head"><b>' + escapeHtml(g.show_date) + title + '</b>' + open + '</div>' +
          g.rows.map(function (t) {
            var n = t.tickets || 1;
            var inCount = t.checked_in_count || 0;
            return '<div class="other-guest"><span>' + escapeHtml(t.guest_name || 'No name') +
              (t.email && t.source !== 'Comp' ? ' <small>' + escapeHtml(t.email) + '</small>' : '') + '</span>' +
              '<span class="other-count">' + n + ' ticket' + (n > 1 ? 's' : '') + (inCount ? ' · ' + inCount + ' in' : '') + '</span></div>';
          }).join('') + '</div>';
      }).join(''));
  }, 300);
}

// ---------- Sign-in ----------
// Each login has one role, and each role can do everything the ones below it
// can: door (tonight's check-in), staff (staff tools), manager, owner (Sam).
var ROLE_RANK = { door: 1, staff: 2, manager: 3, owner: 4 };
var ROLE_LABEL = { door: 'Door', staff: 'Staff', manager: 'Manager', owner: 'Owner' };
function roleAtLeast(role, min) { return (ROLE_RANK[role] || 1) >= ROLE_RANK[min]; }
// What a page shows a login that can't open it.
function showNoAccess(min, hide) {
  (hide || []).forEach(function (id) { var el = $(id); if (el) el.classList.add('hidden'); });
  var el = $('notManager');
  if (!el) return;
  var who = { staff: 'Staff', manager: 'Managers', owner: 'Owner' }[min] || 'Staff';
  el.innerHTML = '<b>' + who + ' only</b>This login can’t open this page. <a href="/staff/">Back to the staff page</a>.';
  el.classList.remove('hidden');
}

// onReady(role) runs once a login is confirmed; role is door, staff, manager or owner.
function setupSignIn(onReady) {
  var started = false;
  async function ready() {
    var r = await sb.rpc('my_role');
    var role = r.data || 'door';
    $('lock').classList.add('hidden');
    if (!started) { started = true; onReady(role); }
  }
  $('loginForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    var btn = $('loginBtn'), err = $('loginError');
    err.classList.add('hidden');
    btn.disabled = true; btn.textContent = 'Signing in…';
    try {
      var res = await sb.auth.signInWithPassword({ email: loginToEmail($('login').value), password: $('password').value });
      if (res.error) {
        err.textContent = /invalid/i.test(res.error.message) ? 'That username and password don’t match.' : res.error.message;
        err.classList.remove('hidden');
        return;
      }
      $('password').value = '';
      await ready();
    } catch (ex) {
      err.textContent = 'Could not reach the server. Check the wifi.';
      err.classList.remove('hidden');
    } finally {
      btn.disabled = false; btn.textContent = 'Sign in';
    }
  });
  sb.auth.getSession().then(function (res) {
    if (res.data && res.data.session) ready();
    else $('lock').classList.remove('hidden');
  }).catch(function () { $('lock').classList.remove('hidden'); });
  sb.auth.onAuthStateChange(function (event, session) {
    if (event === 'SIGNED_OUT' && started) location.reload();
  });
}

async function signOut() {
  await sb.auth.signOut();
  location.reload();
}

// Starts a GitHub Action through the "run-workflow" Supabase function.
async function runWorkflow(workflow, inputs) {
  try {
    var res = await sb.functions.invoke('run-workflow', { body: { workflow: workflow, inputs: inputs } });
    if (!res.error) return { ok: true };
    var msg = res.error.message;
    try {
      var body = await res.error.context.json();
      if (body && body.error) msg = body.error;
    } catch (e) {}
    return { ok: false, error: msg };
  } catch (err) {
    return { ok: false, error: 'network error' };
  }
}
