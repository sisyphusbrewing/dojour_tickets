// The time clock page. See index.html for what it is and who uses it.
// Everything here only shows the clock and asks the database for changes; who
// may do what, and all the hours-and-tips arithmetic for payroll, is in the
// database (supabase/migrations/20261117060000_time_clock.sql), not here.

var TZ = 'America/Chicago';            // every time on this page is Minneapolis time, wherever the phone is
var PERIOD_ANCHOR = '2026-11-02';      // a Monday that started a two-week pay period
var UNDO_MS = 2 * 60 * 1000;           // clocking out this soon after clocking in just drops the punch
var FORGOT_MS = 16 * 3600 * 1000;      // a punch open this long was forgotten, not worked
var CODE_GOOD_MS = 10 * 60 * 1000;     // how long a tap on the bar sticker counts as "at the bar"
var TAP_WAIT_MS = 4000;                // a sticker tap waits this long before clocking out, so "Not yet" can stop it
var TAP_STALE_MS = 60 * 1000;          // a phone that slept through that wait doesn't clock out when it wakes up
var TAP_LONGEST_MS = 12 * 3600 * 1000; // on the clock longer than this, a sticker tap asks instead of clocking out (a forgotten clock-out)

var role = 'door', isMgr = false, isOwner = false, me = null;
var st = null;                         // what the database says about me right now (clock_status)
var people = [], nameOf = {};
var period = null;                     // the first Monday of the pay period on screen, as a Date at noon
var myPunches = [], allPunches = [], shiftOf = {}, payRows = [], run = null, latestRun = null;
var busy = false, editing = null, formMode = 'mine', tipsFor = null, leftFor = null;

// The code from the bar sticker's link ("?at=..."). Kept in memory for a few
// minutes and taken out of the address bar, so a bookmark doesn't carry it and
// reloading the page doesn't count as a second tap.
var barCode = null, barCodeAt = 0;
var tapped = false;                    // this page was opened by a tap on the sticker, and the tap hasn't been used yet
var tapDue = 0, tapTimer = null;       // a sticker tap is about to clock out (see "A tap on the bar sticker")
var stickerOk = null;                  // true / false once we know whether the sticker carries today's link
var skew = 0, skewFrom = null;         // how far this phone's clock is from the database's
// "What's new" updates this login hasn't read. Clocking in walks through them
// first (see "Read the updates first"). Only updates posted from this day on
// count, so nobody meets a pile of old ones the first time they clock in.
var NEWS_FROM = '2026-11-17T06:00:00Z';  // midnight on Nov 17 2026 in Minneapolis, the day Sam asked for this
var unread = [], newsAt = 0, newsUnsaved = [];
(function () {
  try {
    var q = new URLSearchParams(location.search), at = q.get('at');
    if (at) { barCode = at; barCodeAt = Date.now(); tapped = true; history.replaceState(null, '', location.pathname + location.hash); }
  } catch (e) {}
})();
function freshCode() { return barCode && Date.now() - barCodeAt < CODE_GOOD_MS ? barCode : null; }
// The time by the database's clock. "Two minutes since you clocked in" is the
// database's call, so a phone with the wrong time mustn't get it wrong.
function srvNow() { return Date.now() + skew; }
// Clocked in so recently that it can still be undone. A few seconds short of
// the database's two minutes, so "undo" never arrives a moment too late.
function justIn() { return !!(st && st.open) && srvNow() - new Date(st.open.clock_in) < UNDO_MS - 5000; }

// ---------- Small helpers ----------
function iso(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
function fromIso(s) { var p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2], 12); }
function addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
function today() { return new Date().toLocaleDateString('en-CA', { timeZone: TZ }); }       // "2026-11-17" in Minneapolis
function periodOf(day) {               // the Monday that starts the pay period a day is in
  var days = Math.round((fromIso(day) - fromIso(PERIOD_ANCHOR)) / 86400000);
  return iso(addDays(fromIso(PERIOD_ANCHOR), Math.floor(days / 14) * 14));
}
function timeOf(ts) { return new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ }); }
function hm(ts) {                      // "17:34", for a time box
  var p = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ }).formatToParts(new Date(ts));
  var h = p.filter(function (x) { return x.type === 'hour'; })[0].value, m = p.filter(function (x) { return x.type === 'minute'; })[0].value;
  return (h === '24' ? '00' : h) + ':' + m;
}
function niceDay(s) { return fromIso(s).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }); }
function shortDay(s) { return fromIso(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }
function hoursOf(p) { return p.clock_out ? Math.round((new Date(p.clock_out) - new Date(p.clock_in)) / 36000) / 100 : 0; }
function hrs(n) { return Number(n).toFixed(2) + ' h'; }
function money(n) { return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function span(p) { return timeOf(p.clock_in) + (p.clock_out ? ' to ' + timeOf(p.clock_out) : ''); }
function elapsed(ts) {
  var m = Math.max(0, Math.floor((Date.now() - new Date(ts)) / 60000));
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60) + ' min';
}
function clock(t) {                    // a Schedule time: "16:00:00" -> "4 PM"
  if (!t) return 'close';
  var p = t.split(':'), h = +p[0], m = p[1];
  return ((h + 11) % 12 + 1) + (m === '00' ? '' : ':' + m) + (h < 12 ? ' AM' : ' PM');
}
function sched(s) {                    // "4 to 9 PM · Bar"
  var a = clock(s.start_time), b = clock(s.end_time);
  if (s.end_time && a.slice(-2) === b.slice(-2)) a = a.slice(0, -3);
  return a + ' to ' + b + ' · ' + s.position;
}
function first(name) { return String(name || '').split(' ')[0]; }
function who(id) { return nameOf[id] || 'Someone'; }
function lastFirst(name) {             // "Pat Example" -> "Example, Pat", the order ADP lists people in
  var p = String(name || '').trim().split(' ');
  return p.length > 1 ? p.slice(1).join(' ') + ', ' + p[0] : p[0];
}
function lastName(name) { var p = String(name || '').trim().split(' '); return (p.length > 1 ? p.slice(1).join(' ') : p[0]).toLowerCase(); }
// "$1,234.50" or "123.4" -> a number. Empty -> null. Nonsense -> NaN.
function parseMoney(v) {
  var t = String(v == null ? '' : v).replace(/[$,\s]/g, '');
  if (t === '') return null;
  return /^\d+(\.\d{1,2})?$|^\.\d{1,2}$/.test(t) ? Number(t) : NaN;
}
function fail(r, what) { toast((r && r.error && r.error.message) || what || 'That didn’t save. Try again.', true); }
function tags(p) {
  var t = '';
  if (p.in_typed) t += '<span class="tag">Written in</span>';
  else if (p.out_typed) t += '<span class="tag">Clock-out typed</span>';
  if (p.fixed_by) t += '<span class="tag">Changed by ' + escapeHtml(first(p.fixed_by)) + '</span>';
  if (p.hours_run) t += '<span class="tag paid">Paid</span>';
  return t;
}

// ---------- Start ----------
setupSignIn(async function (r) {
  role = r; isMgr = roleAtLeast(role, 'manager'); isOwner = role === 'owner';
  try { localStorage.setItem('staffRoleSeen', role); } catch (e) {}
  if (!roleAtLeast(role, 'staff')) {
    $('page').classList.remove('hidden');
    showNoAccess('staff', ['tab-clock', 'tab-hours', 'tab-payroll']);
    return;
  }
  me = (await sb.auth.getUser()).data.user;
  period = fromIso(periodOf(today()));
  $('payrollTab').classList.toggle('hidden', !isMgr);
  $('page').classList.remove('hidden');
  $('tabs').classList.remove('hidden');
  // The updates get four seconds at most: slow wifi mustn't keep a tap from clocking in.
  await Promise.all([loadPeople(), loadStatus(), within(loadUnread(), 4000)]);
  var tap = tapped && !!freshCode();
  tapped = false;
  // A manager login that doesn't take shifts (Sam's) has nothing to clock, so it opens on Payroll.
  // Unless it just tapped the sticker: then it stays here to be told whether the sticker works.
  if (!location.hash && isMgr && st && !st.on_schedule && !tap) { try { history.replaceState(null, '', '#payroll'); } catch (e) {} }
  showTab();
  if (tap) afterTap();
});

// ---------- Tabs ----------
// Clock, My hours and Payroll are parts of this one page. The part on screen
// is in the web address (#hours), so the back button and links work.
function tabNow() {
  var h = location.hash.replace('#', '');
  if (['clock', 'hours', 'payroll'].indexOf(h) === -1 || (h === 'payroll' && !isMgr)) h = 'clock';
  return h;
}
function showTab() {
  var h = tabNow();
  ['clock', 'hours', 'payroll'].forEach(function (t) { $('tab-' + t).classList.toggle('hidden', t !== h); });
  document.querySelectorAll('#tabs a').forEach(function (a) {
    a.classList.toggle('on', a.dataset.tab === h);
    if (a.dataset.tab === h) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  drawPeriod();
  if (h === 'hours') loadMine();
  if (h === 'payroll') loadPayroll();
}
window.addEventListener('hashchange', function () { if (me) { showTab(); window.scrollTo(0, 0); } });
// Come back to the page after a while and it's fresh.
document.addEventListener('visibilitychange', function () {
  if (document.hidden || !me || document.querySelector('dialog[open]')) return;
  loadStatus(); loadUnread(); if (tabNow() === 'hours') loadMine(); if (tabNow() === 'payroll') loadPayroll();
});
// The "2 h 10 min" under the button, and the Undo that turns into Clock out.
setInterval(function () { if (st && st.open && !document.hidden) drawClock(); }, 20000);

async function loadPeople() {
  var r = await sb.rpc('schedule_people');
  people = r.data || [];
  nameOf = {};
  people.forEach(function (p) { nameOf[p.user_id] = p.name; });
}
async function loadStatus() {
  var r = await sb.rpc('clock_status');
  st = r.error ? null : r.data;
  if (st && !nameOf[me.id]) nameOf[me.id] = st.name;
  // Managers get "The club wifi" under Payroll once the database has that part.
  $('wifiFold').classList.toggle('hidden', !(isMgr && st && st.wifi));
  drawClock();
}

// ---------- Clock: the one button ----------
function drawClock() {
  var btn = $('punchBtn'), other = $('otherBtn');
  if (!st) {
    $('hello').textContent = '';
    $('state').textContent = 'The time clock isn’t switched on yet';
    $('stateSub').textContent = 'It will show up here as soon as it is.';
    btn.classList.add('hidden'); other.classList.add('hidden');
    return;
  }
  if (st.now && st.now !== skewFrom) { skewFrom = st.now; skew = new Date(st.now) - Date.now(); }
  var open = st.open;
  var fresh = justIn(), leaving = !!(tapDue && open);
  $('hello').textContent = 'Hi ' + first(st.name) + '.';
  $('punchCard').classList.toggle('on', !!open);
  $('punchCard').classList.toggle('just', fresh && !leaving);
  // The line under the button: "At the bar" after a sticker tap, or a warning
  // when the sticker carries a link that has since been changed.
  $('atBar').classList.toggle('hidden', !(st.on_schedule && (stickerOk === false || freshCode())));
  $('atBar').classList.toggle('old', stickerOk === false);
  $('atBar').textContent = stickerOk === false ? 'This tag has an old link, so this doesn’t count as “at the bar”. Tell a manager.' : '✓ At the bar';
  btn.classList.toggle('hidden', !st.on_schedule || (fresh && !leaving));
  other.classList.toggle('hidden', !st.on_schedule || leaving);
  // Off the club wifi the button won't clock anyone (Sam, Nov 17 2026: "People
  // can also clock in and out on their phone but they have to be connected to
  // our wifi to do so"), so the page says so before it is tapped. A tap on
  // the tag works on any connection. The database decides; this is only the
  // heads-up, and it is quiet until a manager has set the club wifi.
  var offWifi = !!st.on_schedule && st.wifi === 'off' && !freshCode() && !leaving && !fresh;
  $('wifiNote').classList.toggle('hidden', !offWifi);
  if (offWifi) $('wifiNote').textContent = 'You’re not on the club wifi, so the button won’t clock you ' + (open ? 'out' : 'in') +
    '. Join the wifi, or hold your phone to the tag at the bar.';
  btn.classList.toggle('dim', offWifi);
  // Not clocked in, with updates waiting: say so before the button is pressed.
  var toRead = !!st.on_schedule && !open && !offWifi ? unread.length : 0;
  $('newsNote').classList.toggle('hidden', !toRead);
  if (toRead) $('newsNote').textContent = 'First, ' + toRead + (toRead === 1 ? ' update' : ' updates') + ' to read.';
  if (!st.on_schedule) {
    $('state').textContent = stickerOk === true ? '✓ This tag works' : stickerOk === false ? 'This tag has an old link' : 'Nothing to clock';
    $('stateSub').textContent = stickerOk === true ? 'Staff who tap it are clocked in or out. This login isn’t on the schedule, so it has nothing to clock.'
      : stickerOk === false ? 'Write today’s link onto it. The link is under Payroll, “The tag at the bar”.'
      : 'This login isn’t on the schedule. A manager can add it on the Schedule page, under My settings.';
  } else if (open) {
    var planned = st.shift ? '<br><span class="quiet">Scheduled ' + escapeHtml(sched(st.shift)) + '</span>' : '';
    if (leaving) {
      // A sticker tap is about to clock them out. The button stops it.
      $('state').textContent = 'Clocking you out…';
      $('stateSub').innerHTML = 'On the clock since ' + timeOf(open.clock_in) + ' · ' + elapsed(open.clock_in);
      btn.textContent = 'Not yet';
      btn.classList.remove('out');
    } else if (fresh) {
      // Just clocked in: say so in big letters and get out of the way. The
      // big button is gone for these two minutes so a pocket can't press it.
      $('state').textContent = '✓ Clocked in';
      $('stateSub').innerHTML = 'At ' + timeOf(open.clock_in) + '. You can put your phone away.' + planned;
      other.textContent = 'That was a mistake, undo it';
    } else {
      $('state').textContent = 'On the clock';
      $('stateSub').innerHTML = 'Since ' + timeOf(open.clock_in) + ' · ' + elapsed(open.clock_in) + planned;
      btn.textContent = 'Clock out';
      btn.classList.add('out');
      other.textContent = 'I left earlier';
    }
  } else {
    $('state').textContent = 'Not clocked in';
    $('stateSub').textContent = st.last ? 'Clocked out at ' + timeOf(st.last.clock_out) + ' · ' + hrs(hoursOf(st.last))
      : st.shift ? 'You work today, ' + sched(st.shift) : 'You’re not on today’s schedule.';
    btn.textContent = 'Clock in';
    btn.classList.remove('out');
    other.textContent = 'I forgot to clock in';
  }
  var need = st.need_tips || [], forgot = st.forgot || [];
  $('tipsSection').classList.toggle('hidden', !need.length);
  $('tipsList').innerHTML = need.map(function (p) {
    return '<div class="row"><div><b>' + niceDay(p.work_date) + '</b><small>' + span(p) + '</small></div>' +
      '<div class="row-r"><button class="btn btn-sm btn-primary" onclick="openTips(' + p.id + ')">Add tips</button></div></div>';
  }).join('');
  $('forgotSection').classList.toggle('hidden', !forgot.length);
  $('forgotList').innerHTML = forgot.map(function (p) {
    return '<div class="row"><div><b>' + niceDay(p.work_date) + '</b><small>Clocked in at ' + timeOf(p.clock_in) + '</small></div>' +
      '<div class="row-r"><button class="btn btn-sm btn-primary" onclick="openLeft(' + p.id + ')">When did you leave?</button></div></div>';
  }).join('');
}

// Clock in if I'm out, out if I'm in (the database decides which). Used by
// the big button, by a tap on the bar sticker, and by "undo".
async function punch(byTap) {
  var btn = $('punchBtn');
  if (busy) return;
  busy = true; btn.disabled = true;
  var code = freshCode();
  var r = await sb.rpc('clock_punch', { p_code: code });
  if (r.error) {
    busy = false; btn.disabled = false;
    if (!byTap) chime(false);
    // Refused for not being on the club wifi even though a tag's code was
    // sent: a good code is never refused for that, so the tag has an old link.
    if (r.error.hint === 'wifi' && code) stickerOk = false;
    drawClock();
    fail(r, 'That didn’t go through. Check the wifi and tap again.');
    // They may have joined the wifi since the page last asked.
    if (r.error.hint === 'wifi') loadStatus();
    return;
  }
  st = r.data;
  // The database says whether the code on the sticker was the right one.
  if (code && st.did === 'in' && st.open && st.open.in_at_bar === false) stickerOk = false;
  // The beep and the buzz only work after a finger has touched the page, so a
  // sticker tap gets its answer in big letters instead.
  if (!byTap) {
    chime(true);
    try { if (navigator.vibrate) navigator.vibrate(60); } catch (e) {}
  }
  drawClock();
  toast(st.did === 'in' ? 'Clocked in. Have a good one.' : st.did === 'out' ? 'Clocked out. Thank you.' : 'Undone. You’re not clocked in.');
  // A short pause, so a double tap can't clock straight back out.
  setTimeout(function () { busy = false; btn.disabled = false; }, 1500);
  // When the two minutes to undo are up, the Clock out button comes back.
  if (st.did === 'in') setTimeout(drawClock, UNDO_MS);
  if (st.did === 'out' && st.last) openTips(st.last.id);
}
$('punchBtn').addEventListener('click', function () {
  if (tapDue) return stopTap();
  if (st && st.open) punch(false); else clockIn(false);
});
$('otherBtn').addEventListener('click', function () {
  if (st && st.open) { if (justIn()) punch(false); else openLeft(st.open.id); }
  else openShift('mine');
});

// ---------- Read the updates first ----------
// Sam, Nov 17 2026: "When employees clock in on the app now (either with tap
// or with their login) they should have to click through the updates before
// they can clock in." So clocking in, by the tag or by the button, first shows
// each "What's new" update this login hasn't read, one at a time. "Got it"
// marks it read (the same mark the staff home page keeps) and moves on; "Got
// it" on the last one clocks them in. "Not now" closes it and they are not
// clocked in. Clocking out never waits on this.
//   - Only updates posted since NEWS_FROM count, and for a login made after
//     that, only those posted since it was made: a new hire doesn't click
//     through a year of old news.
//   - If the updates can't be loaded, or a "Got it" can't be saved, nobody is
//     kept off the clock for it. The update comes up again next time.
function within(p, ms) { return Promise.race([p, new Promise(function (done) { setTimeout(done, ms); })]); }
async function loadUnread() {
  var list = [];
  try {
    var from = me.created_at && new Date(me.created_at) > new Date(NEWS_FROM) ? me.created_at : NEWS_FROM;
    var got = await Promise.all([
      sb.from('staff_updates').select('id,title,body,created_at').gte('created_at', from).order('created_at', { ascending: true }).limit(40),
      sb.from('staff_update_reads').select('update_id').eq('user_id', me.id)
    ]);
    if (!got[0].error && !got[1].error) {
      var seen = {};
      (got[1].data || []).forEach(function (r) { seen[r.update_id] = true; });
      list = (got[0].data || []).filter(function (n) { return !seen[n.id]; });
    }
  } catch (e) {}
  if ($('newsDialog').open) return;      // someone is reading: don't change the list under them
  unread = list;
  if (st) drawClock();
}
function drawNews() {
  var n = unread[newsAt], left = unread.length - newsAt;
  $('newsCount').textContent = 'Before you clock in' + (unread.length > 1 ? ' · ' + (newsAt + 1) + ' of ' + unread.length : '');
  $('newsTitle').textContent = n.title;
  $('newsWhen').textContent = 'Posted ' + new Date(n.created_at).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: TZ });
  $('newsBody').textContent = n.body || '';
  $('newsGot').textContent = left > 1 ? 'Got it, next' : 'Got it, clock me in';
}
// Clock in, by the button or by a tap on the tag: the updates first, if there are any.
function clockIn(byTap) {
  if (busy) return;
  // Off the club wifi the button is refused anyway. Say that now, not after the reading.
  var refused = !!st && st.wifi === 'off' && !freshCode();
  if (!unread.length || refused) return punch(byTap);
  newsAt = 0; newsUnsaved = [];
  drawNews();
  $('newsGot').disabled = false;
  $('newsDialog').showModal();
  $('newsDialog').scrollTop = 0;
}
$('newsGot').addEventListener('click', async function () {
  var n = unread[newsAt], btn = $('newsGot');
  if (!n || btn.disabled) return;
  btn.disabled = true;
  var r = null;
  try { r = await sb.from('staff_update_reads').insert({ update_id: n.id }); } catch (e) { r = { error: e }; }
  // "Already read" (23505) is fine. Anything else didn't save: it comes up again next time.
  if (r && r.error && r.error.code !== '23505') newsUnsaved.push(n);
  newsAt++;
  if (newsAt < unread.length) {
    drawNews();
    $('newsDialog').scrollTop = 0;
    // The button sits out a moment, so a double press can't skip an update unread.
    setTimeout(function () { btn.disabled = false; }, 700);
    return;
  }
  btn.disabled = false;
  unread = newsUnsaved; newsUnsaved = [];
  $('newsDialog').close();
  drawClock();
  punch(false);
});
// "Not now", or the Escape key: closed without clocking in. What was already read stays read.
function stopNews() {
  unread = newsUnsaved.concat(unread.slice(newsAt)); newsUnsaved = [];
  if ($('newsDialog').open) $('newsDialog').close();
  drawClock();
  toast('OK. You’re not clocked in.');
}
$('newsNot').addEventListener('click', stopNews);
$('newsDialog').addEventListener('cancel', function (e) { e.preventDefault(); stopNews(); });

// ---------- A tap on the bar sticker ----------
// The NFC sticker at the bar holds this page's link with a code on the end.
// Holding a phone to it opens the page, and the page then does the clocking by
// itself (Sam, Nov 17 2026: "I would rather do nfc tap for clock in and out vs
// QR code"). The rules:
//   - Not clocked in: clock in at once (after any unread updates, see "Read
//     the updates first"). It can be undone for two minutes.
//   - Clocked in: count a few seconds with a "Not yet" button, then clock out
//     and ask for tips. The wait is there because a clock-out can't be undone.
//   - Nothing happens by itself within two minutes of the last punch, so a
//     phone that reads the sticker twice doesn't undo what the first read did.
//   - On the clock for more than twelve hours means last night's clock-out
//     was forgotten: the tap asks instead of writing down a 15-hour shift.
function afterTap() {
  if (!st) return;
  if (isMgr) checkSticker();
  if (!st.on_schedule) return;
  if (st.open) {
    var age = srvNow() - new Date(st.open.clock_in);
    if (age < UNDO_MS) return;                                         // the page already says "Clocked in"
    if (age > TAP_LONGEST_MS) return toast('Still on the clock from ' + timeOf(st.open.clock_in) + '? Clock out, or tap “I left earlier”.', true);
    tapDue = Date.now() + TAP_WAIT_MS;
    tapTimer = setTimeout(tapOut, TAP_WAIT_MS);
    drawClock();
  } else {
    if (st.last && srvNow() - new Date(st.last.clock_out) < UNDO_MS) return toast('You just clocked out.');
    clockIn(true);
  }
}
function tapOut() {
  var late = Date.now() - tapDue;
  tapTimer = null; tapDue = 0;
  // A phone that fell asleep mid-count wakes up much later. Don't clock out
  // then; show where things stand instead.
  if (late > TAP_STALE_MS || !st || !st.open) { loadStatus(); return; }
  punch(true);
}
function stopTap() {
  var btn = $('punchBtn');
  clearTimeout(tapTimer);
  tapTimer = null; tapDue = 0;
  // "Not yet" turns back into "Clock out" under the same finger, so it sits
  // out a moment: a double press mustn't clock out after all.
  busy = true; btn.disabled = true;
  setTimeout(function () { busy = false; btn.disabled = false; }, 1500);
  drawClock();
  toast('OK. You’re still on the clock.');
}
// A manager who taps a sticker is told whether it carries today's link, so a
// freshly written sticker can be checked with one tap.
async function checkSticker() {
  var r = await sb.rpc('clock_bar_code');
  if (r.error || !barCode) return;
  stickerOk = r.data === barCode;
  drawClock();
}

// ---------- Credit tips for one shift ----------
function findPunch(id) {
  var all = [].concat(st ? (st.need_tips || []) : [], st && st.last ? [st.last] : [], st && st.open ? [st.open] : [], st ? (st.forgot || []) : [], myPunches);
  return all.filter(function (p) { return p.id === id; })[0];
}
function openTips(id) {
  var p = findPunch(id);
  if (!p) return;
  tipsFor = p;
  $('tipsWhen').textContent = niceDay(p.work_date || today()) + ' · ' + span(p);
  $('tipsAmount').value = p.tips != null ? Number(p.tips).toFixed(2) : '';
  $('tipsDialog').showModal();
  $('tipsAmount').focus();
}
$('tipsLater').addEventListener('click', function () { $('tipsDialog').close(); });
$('tipsForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var v = parseMoney($('tipsAmount').value);
  if (v === null || isNaN(v)) return toast('Type the tips as a dollar amount, like 123.45. No tips? Type 0.', true);
  $('tipsSave').disabled = true;
  var r = await sb.rpc('clock_tips', { p_id: tipsFor.id, p_tips: v });
  $('tipsSave').disabled = false;
  if (r.error) return fail(r);
  st = r.data;
  $('tipsDialog').close();
  toast('Tips saved: ' + money(v));
  drawClock();
  if (tabNow() === 'hours') loadMine();
});

// ---------- "I left earlier" / "When did you leave?" ----------
function openLeft(id) {
  var p = findPunch(id);
  if (!p) return;
  leftFor = p;
  var old = Date.now() - new Date(p.clock_in) > FORGOT_MS;
  $('leftWhen').textContent = niceDay(p.work_date || today()) + ' · clocked in at ' + timeOf(p.clock_in);
  $('leftTime').value = old ? '' : hm(Date.now());
  $('leftDialog').showModal();
}
$('leftCancel').addEventListener('click', function () { $('leftDialog').close(); });
$('leftForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  if (!$('leftTime').value) return;
  $('leftSave').disabled = true;
  var r = await sb.rpc('clock_left_at', { p_id: leftFor.id, p_time: $('leftTime').value });
  $('leftSave').disabled = false;
  if (r.error) return fail(r);
  st = r.data;
  $('leftDialog').close();
  toast('Saved. A manager can see it was typed in.');
  drawClock();
  if (tabNow() === 'hours') loadMine();
  var done = (st.need_tips || []).filter(function (x) { return x.id === leftFor.id; })[0];
  if (done) openTips(done.id);
});

// ---------- A whole shift: "I forgot to clock in", and the manager's add / fix ----------
// mode: 'mine' (staff write in their own shift), 'add' (manager adds hours for
// someone), 'fix' (manager changes the punch with this id).
function openShift(mode, id) {
  formMode = mode;
  editing = mode === 'fix' ? allPunches.filter(function (p) { return p.id === id; })[0] : null;
  if (mode === 'fix' && !editing) return;
  var p = editing || {};
  $('sfTitle').textContent = mode === 'mine' ? 'I forgot to clock in' : mode === 'add' ? 'Add hours for someone' : 'Change ' + first(who(p.user_id)) + '’s hours';
  $('sfWhoField').classList.toggle('hidden', mode !== 'add');
  $('sfNoteField').classList.toggle('hidden', mode !== 'mine');
  $('sfRemove').classList.toggle('hidden', mode !== 'fix');
  if (mode === 'add') {
    $('sfWho').innerHTML = '<option value="">Pick a person</option>' + people.filter(function (x) { return x.on_schedule; })
      .sort(function (a, b) { return lastName(a.name) < lastName(b.name) ? -1 : 1; })
      .map(function (x) { return '<option value="' + x.user_id + '">' + escapeHtml(x.name) + '</option>'; }).join('');
  }
  $('sfDate').value = p.work_date || today();
  $('sfDate').max = today();
  $('sfIn').value = p.clock_in ? hm(p.clock_in) : '';
  $('sfOut').value = p.clock_out ? hm(p.clock_out) : '';
  $('sfOut').required = mode === 'mine';
  $('sfTips').value = p.tips != null ? Number(p.tips).toFixed(2) : '';
  $('sfNote').value = '';
  $('sfHelp').textContent = mode === 'mine' ? 'A manager is told this shift was written in.'
    : mode === 'add' ? 'They’re told the hours were added.' : 'They’re told what changed.';
  $('shiftDialog').showModal();
}
$('sfCancel').addEventListener('click', function () { $('shiftDialog').close(); });
$('addMineBtn').addEventListener('click', function () { openShift('mine'); });
$('addBtn').addEventListener('click', function () { openShift('add'); });
$('shiftForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var tips = parseMoney($('sfTips').value);
  if (tips !== null && isNaN(tips)) return toast('Type the tips as a dollar amount, like 123.45.', true);
  if (formMode === 'add' && !$('sfWho').value) return toast('Pick who the hours are for.', true);
  $('sfSave').disabled = true;
  var r;
  if (formMode === 'mine') {
    r = await sb.rpc('clock_add_mine', { p_date: $('sfDate').value, p_in: $('sfIn').value, p_out: $('sfOut').value, p_tips: tips, p_note: $('sfNote').value });
  } else {
    r = await sb.rpc('clock_fix', { p_id: editing ? editing.id : null, p_user: editing ? null : $('sfWho').value, p_date: $('sfDate').value,
      p_in: $('sfIn').value, p_out: $('sfOut').value || null, p_tips: tips, p_remove: false });
  }
  $('sfSave').disabled = false;
  if (r.error) return fail(r);
  $('shiftDialog').close();
  toast('Saved.');
  if (formMode === 'mine') { st = r.data; drawClock(); loadMine(); } else { loadPayroll(); loadStatus(); }
});
$('sfRemove').addEventListener('click', async function () {
  if (!editing || !confirm('Remove these hours for ' + who(editing.user_id) + '?\n\n' + niceDay(editing.work_date) + ', ' + span(editing) + '\n\nThey are told.')) return;
  var r = await sb.rpc('clock_fix', { p_id: editing.id, p_user: null, p_date: null, p_in: null, p_out: null, p_tips: null, p_remove: true });
  if (r.error) return fail(r);
  $('shiftDialog').close();
  toast('Removed.');
  loadPayroll(); loadStatus();
});

// ---------- Which pay period ----------
function drawPeriod() {
  var label = shortDay(iso(period)) + ' to ' + shortDay(iso(addDays(period, 13)));
  var current = iso(period) === periodOf(today());
  document.querySelectorAll('.periodLabel').forEach(function (el) { el.textContent = label; });
  document.querySelectorAll('.thisPeriod').forEach(function (el) { el.classList.toggle('hidden', current); });
}
function setPeriod(d) { period = d; showTab(); }
document.querySelectorAll('.prevPeriod').forEach(function (b) { b.addEventListener('click', function () { setPeriod(addDays(period, -14)); }); });
document.querySelectorAll('.nextPeriod').forEach(function (b) { b.addEventListener('click', function () { setPeriod(addDays(period, 14)); }); });
document.querySelectorAll('.thisPeriod').forEach(function (b) { b.addEventListener('click', function () { setPeriod(fromIso(periodOf(today()))); }); });

// ---------- My hours ----------
async function loadMine() {
  var r = await sb.from('time_punches').select('*').eq('user_id', me.id).eq('removed', false)
    .gte('work_date', iso(period)).lte('work_date', iso(addDays(period, 13))).order('clock_in');
  if (r.error) { $('myList').innerHTML = '<p class="quiet" style="margin-top:18px">The time clock isn’t switched on yet.</p>'; return; }
  myPunches = r.data || [];
  drawMine();
}
function punchRow(p, mgr) {
  var open = !p.clock_out, stale = open && Date.now() - new Date(p.clock_in) > FORGOT_MS;
  var s = shiftOf[p.shift_id];
  var right;
  if (open) right = stale ? '<span class="tag need">No clock-out</span>' : 'On the clock';
  else {
    var tips = p.tips != null ? money(p.tips) : '';
    if (!mgr && !p.tips_run) tips = '<button class="btn-link" style="padding:0" onclick="openTips(' + p.id + ')">' + (tips || 'Add tips') + '</button>';
    else if (!tips) tips = 'No tips yet';
    right = '<div>' + hrs(hoursOf(p)) + '<small>' + tips + '</small></div>';
  }
  if (mgr) right += '<button class="sh-edit" onclick="openShift(\'fix\', ' + p.id + ')" aria-label="Change these hours" title="Change these hours">✎</button>';
  return '<div class="row"><div><b>' + niceDay(p.work_date) + '</b>' + tags(p) +
    '<small>' + span(p) + (open && !stale ? ' to now' : '') + (mgr && s ? ' · scheduled ' + sched(s) : '') + (p.note ? ' · ' + escapeHtml(p.note) : '') + '</small></div>' +
    '<div class="row-r">' + right + '</div></div>';
}
function drawMine() {
  var done = myPunches.filter(function (p) { return p.clock_out; });
  var h = done.reduce(function (a, p) { return a + hoursOf(p); }, 0);
  var t = done.reduce(function (a, p) { return a + Number(p.tips || 0); }, 0);
  $('myTotal').classList.toggle('hidden', !done.length);
  $('myTotal').textContent = done.length + ' shift' + (done.length === 1 ? '' : 's') + ' · ' + hrs(h) + ' · ' + money(t) + ' in credit tips';
  $('myList').innerHTML = myPunches.length
    ? '<div class="list" style="margin-top:14px">' + myPunches.slice().reverse().map(function (p) { return punchRow(p, false); }).join('') + '</div>'
    : '<p class="quiet" style="margin-top:18px">No shifts clocked in this pay period.</p>';
}

// ---------- Payroll (managers) ----------
async function loadPayroll() {
  if (!isMgr) return;
  var start = iso(period), thru = iso(addDays(period, 13)), from = iso(addDays(period, -42));
  var rr = await sb.from('payroll_runs').select('*').order('id', { ascending: false }).limit(80);
  if (rr.error) { $('payStatus').textContent = 'The time clock isn’t switched on yet.'; $('payList').innerHTML = ''; return; }
  var runs = (rr.data || []).filter(function (x) { return !x.undone_at; });
  latestRun = runs[0] || null;
  run = runs.filter(function (x) { return x.through === thru; })[0] || null;
  var got = await Promise.all([
    sb.rpc('clock_payroll', run ? { p_through: null, p_run: run.id } : { p_through: thru, p_run: null }),
    sb.from('time_punches').select('*').eq('removed', false).gte('work_date', from).lte('work_date', thru).order('clock_in'),
    sb.from('shifts').select('id,work_date,start_time,end_time,position').gte('work_date', from).lte('work_date', thru)
  ]);
  if (got[0].error) { fail(got[0], 'Couldn’t load payroll.'); return; }
  payRows = got[0].data || [];
  shiftOf = {};
  (got[2].data || []).forEach(function (s) { shiftOf[s.id] = s; });
  // What this payroll is made of: this period's shifts, plus anything older
  // that is in it (a submitted payroll) or still unpaid (one not submitted).
  allPunches = (got[1].data || []).filter(function (p) {
    if (p.work_date >= start) return true;
    return run ? (p.hours_run === run.id || p.tips_run === run.id)
               : ((p.clock_out && !p.hours_run) || (p.tips != null && !p.tips_run));
  });
  drawPayroll(start, thru);
}
function drawPayroll(start, thru) {
  var over = thru < today();
  $('payStatus').textContent = run ? 'Submitted ' + new Date(run.submitted_at).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: TZ }) +
      (run.submitted_by ? ' by ' + first(run.submitted_by) : '') + '. This is what was in it.'
    : over ? 'Not submitted yet. These are the hours and credit tips to type into ADP.'
    : 'This pay period runs through ' + niceDay(thru) + '. So far:';
  var totH = 0, totT = 0, warn = [];
  var rows = payRows.map(function (r) {
    totH += Number(r.hours); totT += Number(r.tips);
    var flags = [];
    if (Number(r.week1) > 40 || Number(r.week2) > 40) flags.push('Over 40 hours in a week (' + hrs(Math.max(r.week1, r.week2)) + ')');
    if (r.written_in) flags.push(r.written_in + ' typed in by hand');
    if (r.no_tips) flags.push(r.no_tips + ' shift' + (r.no_tips > 1 ? 's' : '') + ' without tips');
    if (r.no_clock_out) flags.push(r.no_clock_out + ' without a clock-out');
    if (Number(r.earlier_hours) > 0) flags.push('Includes ' + hrs(r.earlier_hours) + ' from before ' + shortDay(start));
    if (!r.shifts && Number(r.tips) > 0) flags.push('Tips typed in late, for hours already paid');
    if (r.no_tips || r.no_clock_out) warn.push(first(r.name));
    return '<div class="prow"><b>' + escapeHtml(lastFirst(r.name)) + '</b><span class="num">' + Number(r.hours).toFixed(2) + '</span><span class="num">' + money(r.tips) + '</span>' +
      (flags.length ? '<div class="flags">' + flags.join(' · ') + '</div>' : '') + '</div>';
  });
  $('payList').innerHTML = rows.length
    ? '<div class="prow head"><span>Last name first</span><span>Hours</span><span>Credit tips</span></div>' + rows.join('') +
      '<div class="prow total"><span>Everyone</span><span>' + totH.toFixed(2) + '</span><span>' + money(totT) + '</span></div>'
    : '<div class="quiet">' + (run ? 'Nothing was in this payroll.' : 'Nobody has clocked in this pay period yet.') + '</div>';
  $('payWarn').classList.toggle('hidden', !warn.length || !!run);
  $('payWarn').textContent = 'Still missing something: ' + warn.join(', ') + '. Anything typed in after you submit goes into the next payroll.';
  $('submitBtn').classList.toggle('hidden', !(isOwner && !run && over && rows.length));
  $('undoBtn').classList.toggle('hidden', !(isOwner && run && latestRun && run.id === latestRun.id));

  // Who is on the clock right now (only when looking at the current pay period).
  var now = iso(period) === periodOf(today()) ? allPunches.filter(function (p) { return !p.clock_out && Date.now() - new Date(p.clock_in) < FORGOT_MS; }) : [];
  $('nowSection').classList.toggle('hidden', !now.length);
  $('nowList').innerHTML = now.map(function (p) {
    return '<div class="row"><div><b>' + escapeHtml(who(p.user_id)) + '</b><small>Since ' + timeOf(p.clock_in) + (shiftOf[p.shift_id] ? ' · scheduled ' + sched(shiftOf[p.shift_id]) : '') + '</small></div>' +
      '<div class="row-r">' + elapsed(p.clock_in) + '</div></div>';
  }).join('');

  // Tips by night: what everyone typed for a night, added up, to hold against GoTab's tip report.
  var nights = {};
  allPunches.forEach(function (p) {
    if (!p.clock_out) return;
    var n = nights[p.work_date] = nights[p.work_date] || { sum: 0, with: 0, without: 0 };
    if (p.tips != null) { n.sum += Number(p.tips); n.with++; } else n.without++;
  });
  var days = Object.keys(nights).sort();
  $('nightFold').classList.toggle('hidden', !days.length);
  $('nightList').innerHTML = days.map(function (d) {
    var n = nights[d];
    var bits = [];
    if (n.with) bits.push(n.with + ' ' + (n.with === 1 ? 'person' : 'people'));
    if (n.without) bits.push(n.without + (n.without === 1 ? ' hasn’t' : ' haven’t') + ' typed tips');
    return '<div class="row"><div><b>' + niceDay(d) + '</b><small>' + bits.join(' · ') + '</small></div><div class="row-r">' + money(n.sum) + '</div></div>';
  }).join('');

  // Every shift, person by person, each with a pencil.
  var by = {};
  allPunches.forEach(function (p) { (by[p.user_id] = by[p.user_id] || []).push(p); });
  var ids = Object.keys(by).sort(function (a, b) { return lastName(who(a)) < lastName(who(b)) ? -1 : 1; });
  $('shiftFold').classList.toggle('hidden', !ids.length);
  $('shiftList').innerHTML = ids.map(function (id) {
    return '<div class="pname">' + escapeHtml(who(id)) + '</div><div class="list">' + by[id].map(function (p) { return punchRow(p, true); }).join('') + '</div>';
  }).join('');
}
$('submitBtn').addEventListener('click', async function () {
  var thru = iso(addDays(period, 13));
  if (!confirm('Mark payroll for ' + shortDay(iso(period)) + ' to ' + shortDay(thru) + ' as submitted?\n\nDo this after it’s in ADP. Everything in the list is stamped as paid, and the next payroll starts clean.')) return;
  var r = await sb.rpc('clock_payroll_submit', { p_through: thru });
  if (r.error) return fail(r);
  toast('Marked as submitted.');
  loadPayroll();
});
$('undoBtn').addEventListener('click', async function () {
  if (!run || !confirm('Take this payroll back?\n\nIts shifts and tips go back to “not paid yet”.')) return;
  var r = await sb.rpc('clock_payroll_undo', { p_run: run.id });
  if (r.error) return fail(r);
  toast('Taken back.');
  loadPayroll();
});

// ---------- Managers: the club wifi ----------
// The big button only works on the club wifi. The database knows the club's
// network because a manager, standing in the club on the wifi, taps "This is
// the club wifi" once. Until then the rule is off.
function drawWifi(w) {
  var s = w && w.state;
  $('wifiState').textContent = s === 'on' ? '✓ The rule is on, and this phone is on the club wifi.'
    : s === 'off' ? 'The rule is on. This phone is not on the club wifi right now.'
    : 'The rule is off: nobody has set the club wifi yet, so the button works from anywhere.';
  $('wifiState').classList.toggle('good', s === 'on');
  $('wifiOff').classList.toggle('hidden', !s || s === 'unset');
}
$('wifiFold').addEventListener('toggle', async function () {
  if (!this.open) return;
  var r = await sb.rpc('clock_wifi');
  if (r.error) return fail(r);
  drawWifi(r.data);
});
$('wifiHere').addEventListener('click', async function () {
  if (!confirm('Only do this in the club, with this phone on the club wifi.\n\nFrom then on the Clock in button only works on this network. The tag works anywhere.')) return;
  var r = await sb.rpc('clock_wifi_here');
  if (r.error) return fail(r);
  drawWifi(r.data);
  toast('Saved. This is the club wifi.');
  loadStatus();
});
$('wifiOff').addEventListener('click', async function () {
  if (!confirm('Switch the wifi rule off?\n\nThe Clock in button will work from anywhere until someone sets the club wifi again.')) return;
  var r = await sb.rpc('clock_wifi_off');
  if (r.error) return fail(r);
  drawWifi(r.data);
  toast('The wifi rule is off.');
  loadStatus();
});

// The sticker link is only fetched when a manager opens that fold.
$('stickerFold').addEventListener('toggle', async function () {
  if (!this.open || $('stickerLink').value) return;
  var r = await sb.rpc('clock_bar_code');
  if (r.error) return fail(r);
  $('stickerLink').value = location.origin + '/clock/?at=' + r.data;
});
$('stickerCopy').addEventListener('click', async function () {
  try { await navigator.clipboard.writeText($('stickerLink').value); toast('Copied.'); }
  catch (e) { $('stickerLink').select(); toast('Press and hold the link to copy it.'); }
});
