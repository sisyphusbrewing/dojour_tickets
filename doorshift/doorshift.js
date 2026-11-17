// The "I worked the door" form (Sam, Nov 17 2026: "We need a seperate form
// where people can submit if they worked the door"). index.html says who it
// is for. This file: list the last few show nights, take a name and a Venmo
// username, and send it to the pay sheet's "Asking to be paid" list.

var SUPABASE_URL = 'https://idsdwkubqnavkazlteis.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ';
// Always the public key, never somebody's login, so the form works the same
// on any phone, signed in to the staff site or not.
var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY,
  { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });

// No dollar amount is asked for or sent from here. What a door shift pays is
// Sam's to say on the pay sheet when he approves it (this code is public).
var SHOW_FIRST = 5;     // nights listed before "Earlier nights" is tapped
var LIST_DAYS = 30;     // how far back the list goes
var TYPED_DAYS = 60;    // how far back a typed day may go

var $ = function (id) { return document.getElementById(id); };
function esc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

// ---------- Days ----------
// Days are kept as 2026-11-17. "Tonight" is the night it is in Minneapolis;
// until 5 in the morning it is still last night, the same as on the door list.
function tonight() { return new Date(Date.now() - 5 * 3600 * 1000).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' }); }
function hourNow() { return Number(new Date().toLocaleString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', hourCycle: 'h23' })); }
function addDays(day, n) { var p = day.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n)).toISOString().slice(0, 10); }
// "Tue, Nov 17"
function dayName(day) {
  var p = day.split('-');
  return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

// ---------- What this phone remembers ----------
// A name and Venmo, so the next shift is two taps, and which nights were sent
// from here, so nobody wonders "did I send Friday?". Only when the box is
// ticked. Nothing is remembered anywhere else.
var ME_KEY = 'doorShiftMe', SENT_KEY = 'doorShiftSent';
function recall(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (e) { return fallback; } }
function keep(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} }
function forget(key) { try { localStorage.removeItem(key); } catch (e) {} }
function nameKey(n) { return String(n || '').trim().toLowerCase().replace(/\s+/g, ' '); }
function wasSent(day, name) {
  var who = nameKey(name);
  return !!who && recall(SENT_KEY, []).some(function (s) { return s.d === day && s.n === who; });
}
// A phone signed in to the staff site with one of the logins people share
// (door, staff) is probably the club's, or passed around: there the
// "Remember me" box starts out unticked, so one person's Venmo is never left
// waiting for the next person.
function sharedLogin() {
  try {
    var s = JSON.parse(localStorage.getItem('sb-idsdwkubqnavkazlteis-auth-token') || 'null');
    return /^(door|staff)@/i.test((s && s.user && s.user.email) || '');
  } catch (e) { return false; }
}

// ---------- The nights ----------
var nights = [];        // [{ d: '2026-11-17', shows: ['Tuesday Open Mic'] }], newest first
var picked = null;      // a day, or 'other' for a night that isn't listed
var showAll = false;
var listDown = false;   // the list of shows could not be loaded

async function loadNights() {
  var today = tonight(), oldest = addDays(today, -LIST_DAYS), by = {};
  try {
    // The same list payme/ uses: every show of the last 60 days, website and
    // Dojour, each run with its first and last night. Titles only.
    var res = await sb.rpc('pay_shows');
    if (res.error) throw res.error;
    (res.data || []).forEach(function (run) {
      for (var d = run.first; d <= run.last; d = addDays(d, 1)) {
        if (d > today || d < oldest) continue;
        (by[d] = by[d] || []).push(run.title);
      }
    });
  } catch (e) { listDown = true; }
  nights = Object.keys(by).sort().reverse().map(function (d) { return { d: d, shows: by[d] }; });

  // At the door on a show night (5 PM on), tonight is already picked. Any
  // other time the person picks, so a shift is never sent for the wrong night
  // by not looking.
  var h = hourNow();
  if (nights.length && nights[0].d === today && (h >= 17 || h < 5)) picked = today;
  if (!nights.length) picked = 'other';
  drawNights();
}

function drawNights() {
  var today = tonight(), who = $('f_name').value;
  var list = showAll ? nights : nights.slice(0, SHOW_FIRST);
  var html = list.map(function (n) {
    var lead = n.d === today ? 'Tonight · ' : n.d === addDays(today, -1) ? 'Last night · ' : '';
    return '<label class="night' + (picked === n.d ? ' on' : '') + '">' +
      '<input type="radio" name="night" value="' + n.d + '"' + (picked === n.d ? ' checked' : '') + '>' +
      '<span class="n-main"><b>' + lead + esc(dayName(n.d)) + '</b><small>' + esc(n.shows.join(' · ')) + '</small></span>' +
      (wasSent(n.d, who) ? '<span class="sent">Sent ✓</span>' : '') + '</label>';
  }).join('');
  if (!nights.length) {
    html = '<div class="quiet">' + (listDown ? 'The list of shows didn’t load. Type the day below.' : 'No shows in the last few weeks. Type the day below.') + '</div>';
  } else {
    html += '<label class="night' + (picked === 'other' ? ' on' : '') + '">' +
      '<input type="radio" name="night" value="other"' + (picked === 'other' ? ' checked' : '') + '>' +
      '<span class="n-main"><b>A different night</b></span></label>';
  }
  $('nights').innerHTML = html;
  $('moreBtn').classList.toggle('hidden', showAll || nights.length <= SHOW_FIRST);
  $('otherBox').classList.toggle('hidden', picked !== 'other');
  drawAgain();
}

// The day and the show for what is picked, or a sentence saying what is missing.
function pickedNight() {
  var today = tonight();
  if (!picked) return { missing: 'Pick the night you worked.' };
  if (picked !== 'other') {
    var n = nights.filter(function (x) { return x.d === picked; })[0];
    return { day: picked, show: n ? n.shows.join(' + ') : '' };
  }
  var day = $('f_day').value;
  if (!day) return { missing: 'Which day did you work?' };
  if (day > today) return { missing: 'That day hasn’t happened yet.' };
  if (day < addDays(today, -TYPED_DAYS)) return { missing: 'That one is a while back. Email booking@sisyphusbrewing.com about it.' };
  var known = nights.filter(function (x) { return x.d === day; })[0];
  var show = $('f_show').value.trim() || (known ? known.shows.join(' + ') : '');
  if (!show) return { missing: 'Which show or event was it?' };
  return { day: day, show: show };
}

// "You already sent this one": say so, and let them send again to fix a typo.
function drawAgain() {
  var p = pickedNight(), again = !p.missing && wasSent(p.day, $('f_name').value);
  $('againNote').textContent = again ? 'You already sent ' + dayName(p.day) + ' from this phone. Send it again only to fix something.' : '';
  $('againNote').classList.toggle('hidden', !again);
  $('sendBtn').textContent = again ? 'Send it again' : 'Send it';
}

$('nights').addEventListener('change', function (e) {
  if (!e.target || e.target.name !== 'night') return;
  picked = e.target.value;
  $('formError').classList.add('hidden');
  drawNights();
  if (picked === 'other' && !$('f_day').value) $('f_day').focus();
});
$('moreBtn').addEventListener('click', function () { showAll = true; drawNights(); });
$('f_day').addEventListener('change', drawAgain);
$('f_name').addEventListener('input', drawNights);
// Once they start fixing what was missing, the red line goes away.
$('doorForm').addEventListener('input', function () { $('formError').classList.add('hidden'); });

// ---------- Sending ----------
function cleanHandle(v) {
  var h = String(v || '').trim().replace(/^(https?:\/\/)?(www\.)?venmo\.com\/(u\/)?/i, '').replace(/\s+/g, '');
  if (!h || h === '@') return '';
  return h.charAt(0) === '@' ? h : '@' + h;
}

$('doorForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var err = $('formError'), btn = $('sendBtn');
  var fail = function (m) { err.textContent = m; err.classList.remove('hidden'); };
  err.classList.add('hidden');

  var p = pickedNight();
  if (p.missing) return fail(p.missing);
  var name = $('f_name').value.trim().replace(/\s+/g, ' ');
  if (!name) return fail('We need your name.');
  var handle = cleanHandle($('f_handle').value);
  if (!handle) return fail('We need your Venmo username.');
  var show = p.show.length > 120 ? p.show.slice(0, 119) + '…' : p.show;

  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    // One line on the pay sheet's "Asking to be paid" list, marked Door.
    var res = await sb.rpc('pay_request', { p_data: {
      name: name, handle: handle, role: 'Door', show_name: show,
      show_dates: dayName(p.day), show_end: p.day } });
    if (res.error) throw new Error(res.error.message);
    // Tell booking@ there is one waiting. The shift is saved either way.
    sb.functions.invoke('job-applied', { body: { id: res.data, kind: 'pay' } }).catch(function () {});

    if ($('f_keep').checked) {
      keep(ME_KEY, { name: name, handle: handle });
      $('f_name').value = name; $('f_handle').value = handle;     // tidied, as it was sent
      var sent = recall(SENT_KEY, []).filter(function (s) { return !(s.d === p.day && s.n === nameKey(name)); });
      sent.push({ d: p.day, n: nameKey(name) });
      keep(SENT_KEY, sent.slice(-40));
    } else {
      forget(ME_KEY);
      $('f_name').value = ''; $('f_handle').value = '';
    }
    $('doneHead').textContent = 'Got it, ' + name.split(' ')[0] + '.';
    $('doneLine').textContent = dayName(p.day) + ' is in. Venmo to ' + handle + '.';
    $('viewForm').classList.add('hidden'); $('viewDone').classList.remove('hidden');
    window.scrollTo(0, 0);
  } catch (ex) {
    var m = String(ex && ex.message || '');
    fail(!m || /fetch|network|load failed/i.test(m) ? 'That didn’t send. Check your signal and try again.' : m);
  } finally {
    btn.disabled = false; drawAgain();
  }
});

$('anotherBtn').addEventListener('click', function () {
  picked = null; $('f_day').value = ''; $('f_show').value = '';
  $('viewDone').classList.add('hidden'); $('viewForm').classList.remove('hidden');
  drawNights();
  window.scrollTo(0, 0);
});

// ---------- Start ----------
(function () {
  var today = tonight(), me = recall(ME_KEY, null);
  $('f_day').max = today; $('f_day').min = addDays(today, -TYPED_DAYS);
  if (me && me.name) { $('f_name').value = me.name; $('f_handle').value = me.handle || ''; }
  $('f_keep').checked = me ? true : !sharedLogin();
  loadNights();
})();
