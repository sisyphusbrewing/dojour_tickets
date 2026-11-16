// The staff schedule page. See index.html for what it is and who uses it.
// Everything here only shows the schedule and asks the database for changes;
// who may do what is enforced in the database, not here.

// Taproom hours by day of week (0 = Sunday), from the website's Visit page.
// Monday is closed. Used for a new shift's default times and to turn "until
// close" into hours when adding up someone's week.
var OPEN = { 0: ['13:00', '18:00'], 2: ['16:00', '21:00'], 3: ['16:00', '21:00'], 4: ['16:00', '23:00'], 5: ['13:00', '23:00'], 6: ['13:00', '23:00'] };
var DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
var DAY_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
// Texts need a texting service signed up for first. Until then anyone who picks
// "Text" gets the same notice by email, and the page says so.
var TEXTS_ON = false;

var role = 'door', me = null, isMgr = false, myRow = null;
var people = [], nameOf = {};
var weekStart = null;                 // the Monday of the week on screen, as a Date at noon
var shifts = [], timeOff = [], avail = [], showsByDay = {};
var view = 'all', showPast = false, editing = null;

// ---------- Small helpers ----------
function iso(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
function fromIso(s) { var p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2], 12); }
function addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
function mondayOf(d) { var x = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12); return addDays(x, -((x.getDay() + 6) % 7)); }
function todayIso() { return iso(new Date()); }
function clock(t) {
  if (!t) return 'close';
  var p = t.split(':'), h = +p[0], m = p[1];
  return ((h + 11) % 12 + 1) + (m === '00' ? '' : ':' + m) + (h < 12 ? ' AM' : ' PM');
}
// "1 to 6 PM", "11 AM to 3 PM", "5 PM to close": AM or PM is said once when both ends share it.
function span(s) {
  var a = clock(s.start_time), b = clock(s.end_time);
  if (s.end_time && a.slice(-2) === b.slice(-2)) a = a.slice(0, -3);
  return a + ' to ' + b;
}
function niceDay(s) { return fromIso(s).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }); }
function niceRange(a, b) { return a === b ? niceDay(a) : niceDay(a) + ' to ' + niceDay(b); }
function mins(t) { var p = t.split(':'); return +p[0] * 60 + +p[1]; }
// How long a shift is, in hours. "Until close" counts to that day's closing time.
function hoursOf(s) {
  var start = mins(s.start_time);
  var close = OPEN[fromIso(s.work_date).getDay()];
  var end = s.end_time ? mins(s.end_time) : (close ? mins(close[1]) : start + 360);
  if (end <= start) end += 24 * 60;      // runs past midnight
  return (end - start) / 60;
}
function hoursWord(h) { return (Math.round(h * 10) / 10) + ' h'; }
function first(name) { return String(name || '').split(' ')[0]; }
function who(id) { return nameOf[id] || 'Someone'; }
// Send the waiting notices now instead of at the next 15-minute run. Best
// effort: if it can't be started, the timer picks them up anyway.
var nudgeTimer = null;
function nudge() {
  clearTimeout(nudgeTimer);
  nudgeTimer = setTimeout(function () { runWorkflow('schedule_notify.yml', {}); }, 4000);
}
function fail(r, what) { toast((r.error && r.error.message) || what || 'That didn’t save. Try again.', true); }

// ---------- Start ----------
setupSignIn(async function (r) {
  role = r; isMgr = roleAtLeast(role, 'manager');
  try { localStorage.setItem('staffRoleSeen', role); } catch (e) {}
  if (!roleAtLeast(role, 'staff')) {
    $('page').classList.remove('hidden');
    showNoAccess('staff', ['tab-week', 'tab-timeoff', 'tab-settings']);
    return;
  }
  me = (await sb.auth.getUser()).data.user;
  try { view = localStorage.getItem('schedView') || 'all'; } catch (e) {}
  if (view === 'grabs') view = 'all';
  weekStart = mondayOf(new Date());
  showTab();
  $('page').classList.remove('hidden');
  $('tabs').classList.remove('hidden');
  await loadPeople();
  await Promise.all([loadWeek(), loadShows(), loadSide(), loadNotices()]);
  drawWeek();
});

// ---------- Tabs ----------
// Week, Time off and My settings are three parts of this one page. The part
// on screen is in the web address (#timeoff), so the back button and links
// from other pages work. "#grabs" is the Week tab showing only the shifts
// that need someone (the staff home page links to it).
var TABS = ['week', 'timeoff', 'settings'];
function showTab() {
  var h = location.hash.replace('#', '');
  if (h === 'grabs') { view = 'grabs'; h = 'week'; }
  if (TABS.indexOf(h) === -1) h = 'week';
  TABS.forEach(function (t) { $('tab-' + t).classList.toggle('hidden', t !== h); });
  document.querySelectorAll('#tabs a').forEach(function (a) {
    a.classList.toggle('on', a.dataset.tab === h);
    if (a.dataset.tab === h) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
}
window.addEventListener('hashchange', function () {
  if (!me) return;
  showTab(); window.scrollTo(0, 0);
  if (shifts) drawWeek();
});

// Come back to the page after a while and it's fresh.
document.addEventListener('visibilitychange', function () {
  if (!document.hidden && me && !$('shiftDialog').open) { loadWeek().then(drawWeek); loadNotices(); }
});

async function loadPeople() {
  var r = await sb.rpc('schedule_people');
  people = r.data || [];
  nameOf = {};
  people.forEach(function (p) { nameOf[p.user_id] = p.name; });
  var m = await sb.rpc('schedule_me');
  myRow = (m.data && m.data[0]) || null;
  if (myRow && !nameOf[me.id]) nameOf[me.id] = myRow.name;
  drawReach();
  drawPeople();
}

async function loadWeek() {
  var r = await sb.from('shifts').select('*').gte('work_date', iso(weekStart)).lte('work_date', iso(addDays(weekStart, 6)))
    .order('work_date').order('start_time');
  if (r.error) { shifts = null; return; }
  shifts = r.data || [];
}

// Shows on each day, so whoever builds the week can see a two-show Friday coming.
async function loadShows() {
  var r = await sb.rpc('staff_show_counts');
  showsByDay = {};
  (r.data || []).forEach(function (s) {
    var ts = parseShowDateToMillis(s.show_date);
    if (!ts || /^\s*canceled/i.test(s.show_title)) return;
    var day = iso(new Date(ts));
    (showsByDay[day] = showsByDay[day] || []).push({ ts: ts, title: s.show_title, time: showTime(s.show_date), sold: Number(s.web) + Number(s.dojour) });
  });
  Object.keys(showsByDay).forEach(function (d) { showsByDay[d].sort(function (a, b) { return a.ts - b.ts; }); });
}

// ---------- The week ----------
function setWeek(d) { weekStart = mondayOf(d); loadWeek().then(drawWeek); }
$('prevWeek').addEventListener('click', function () { setWeek(addDays(weekStart, -7)); });
$('nextWeek').addEventListener('click', function () { setWeek(addDays(weekStart, 7)); });
$('thisWeek').addEventListener('click', function () { setWeek(new Date()); });
$('viewChips').addEventListener('click', function (e) {
  var c = e.target.closest('.chip');
  if (!c) return;
  view = c.dataset.view;
  try { localStorage.setItem('schedView', view); } catch (ex) {}
  drawWeek();
});
$('earlierBtn').addEventListener('click', function () { showPast = !showPast; drawWeek(); });

function offOn(day) {     // approved or pending time off covering a day
  return timeOff.filter(function (t) { return (t.status === 'approved' || t.status === 'pending') && t.start_date <= day && t.end_date >= day; });
}

// One shift: the time on the left, then who and what job. On a phone the
// shifts of a day are rows in one box; on a computer each is a small block in
// that day's column.
function shiftHtml(s, today) {
  var mine = s.user_id === me.id, open = !s.user_id, future = s.work_date >= today;
  var cls = 'shift' + (mine ? ' mine' : '') + (open ? ' open' : '') + (s.published ? '' : ' draft');
  var tags = '';
  if (mine) tags += ' <span class="you">You</span>';
  if (!s.published) tags += ' <span class="tag">Draft</span>';
  if (s.up_for_grabs) tags += ' <span class="tag need">Needs cover</span>';
  var acts = '';
  if (s.published && future) {
    if (mine && !s.up_for_grabs) acts += '<button class="btn btn-sm" onclick="offerShift(' + s.id + ', true)">I can’t work it</button>';
    if (mine && s.up_for_grabs) acts += '<button class="btn btn-sm" onclick="offerShift(' + s.id + ', false)">Never mind, I’ll work it</button>';
    if (!mine && (open || s.up_for_grabs) && myRow && myRow.on_schedule) acts += '<button class="btn btn-sm btn-primary" onclick="takeShift(' + s.id + ')">Take it</button>';
  }
  // Managers get a small pencil on every shift.
  var edit = isMgr ? '<button class="sh-edit" onclick="openShift(' + s.id + ')" aria-label="Change this shift" title="Change this shift">✎</button>' : '';
  return '<div class="' + cls + '"><div class="sh-time">' + span(s) + '</div>' +
    '<div class="sh-main"><div class="sh-who">' + (open ? 'Open shift' : escapeHtml(who(s.user_id))) + tags + '</div>' +
    '<div class="sh-pos">' + escapeHtml(s.position) + (s.note ? ' · ' + escapeHtml(s.note) : '') + '</div>' +
    (acts ? '<div class="sh-acts">' + acts + '</div>' : '') + '</div>' + edit + '</div>';
}

// The shows on a day, each name once: "The Dose · 7:00 PM, 78 sold · 9:30 PM, 40 sold".
function showsHtml(day) {
  var by = {}, order = [];
  (showsByDay[day] || []).forEach(function (x) {
    if (!by[x.title]) { by[x.title] = []; order.push(x.title); }
    by[x.title].push(escapeHtml(x.time) + ', ' + x.sold + ' sold');
  });
  return order.map(function (t) { return '<div class="dshow"><b>' + escapeHtml(t) + '</b> ' + by[t].join(' · ') + '</div>'; }).join('');
}

function drawWeek() {
  var today = todayIso(), end = addDays(weekStart, 6);
  $('weekLabel').textContent = weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' to ' +
    end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  $('weekNone').classList.add('hidden');
  $('thisWeek').classList.toggle('hidden', iso(weekStart) === iso(mondayOf(new Date())));
  if (shifts === null) {
    $('week').className = 'week off';
    $('week').innerHTML = '<div class="empty"><b>The schedule isn’t switched on yet</b>It will show up here as soon as it is.</div>';
    $('mgrBar').classList.add('hidden');
    return;
  }
  var grabs = shifts.filter(function (s) { return s.published && s.work_date >= today && s.user_id !== me.id && (!s.user_id || s.up_for_grabs); });
  $('grabsChip').classList.toggle('hidden', !grabs.length);
  $('grabsChip').textContent = 'Up for grabs (' + grabs.length + ')';
  if (view === 'grabs' && !grabs.length) view = 'all';
  document.querySelectorAll('#viewChips .chip').forEach(function (c) { c.classList.toggle('on', c.dataset.view === view); });

  var pastDays = 0, html = '', listed = 0;
  for (var i = 0; i < 7; i++) {
    var d = addDays(weekStart, i), day = iso(d), dow = d.getDay(), hrs = OPEN[dow];
    var list = shifts.filter(function (s) { return s.work_date === day; }).filter(function (s) {
      return view === 'mine' ? s.user_id === me.id : view === 'grabs' ? grabs.indexOf(s) !== -1 : true;
    });
    var past = day < today;
    if (past) pastDays++;
    listed += list.length;
    var off = offOn(day).map(function (t) {
      return '<div class="doff' + (t.status === 'pending' ? ' ask' : '') + '">' + (t.user_id === me.id ? 'You' : escapeHtml(first(who(t.user_id)))) +
        (t.status === 'pending' ? ' asked off' : ' off') + '</div>';
    }).join('');
    html += '<div class="day' + (day === today ? ' today' : '') + (past ? ' past' : '') + (hrs ? '' : ' closed') + (list.length ? '' : ' bare') + '">' +
      '<div class="day-h"><b>' + DAY_LONG[dow] + '</b><span>' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + '</span>' +
      (day === today ? '<em>Today</em>' : '') + (hrs ? '' : '<small>Closed</small>') + '</div>' +
      showsHtml(day) + off +
      (list.length ? '<div class="shifts">' + list.map(function (s) { return shiftHtml(s, today); }).join('') + '</div>'
                   : '<div class="none">' + (view === 'mine' ? 'Not working' : view === 'grabs' ? 'Nothing' : hrs ? 'Nobody yet' : '') + '</div>') +
      (isMgr ? '<button class="add" onclick="openShift(null, \'' + day + '\')">+ Add a shift</button>' : '') + '</div>';
  }
  // "Just me" and "Up for grabs" only list the days that have something (on a
  // phone), so a week with nothing says so in a sentence instead.
  $('week').className = 'week view-' + view + (showPast ? '' : ' hide-past');
  $('week').innerHTML = html;
  if (view !== 'all' && !listed) {
    $('weekNone').textContent = view === 'mine' ? 'You’re not on the schedule this week.' : 'Nothing is up for grabs this week.';
    $('weekNone').classList.remove('hidden');
  }
  $('earlierBtn').classList.toggle('hidden', !pastDays || pastDays === 7);
  $('earlierBtn').textContent = showPast ? 'Hide earlier days' : 'Show earlier this week';

  // My week, in a sentence.
  var mine = shifts.filter(function (s) { return s.user_id === me.id && s.published; });
  var total = mine.reduce(function (a, s) { return a + hoursOf(s); }, 0);
  $('myWeek').classList.toggle('hidden', !mine.length);
  $('myWeek').textContent = 'Your week: ' + mine.length + ' shift' + (mine.length > 1 ? 's' : '') + ', about ' + hoursWord(total) + '.';

  drawManagerBar();
}

function drawManagerBar() {
  $('mgrBar').classList.toggle('hidden', !isMgr);
  if (!isMgr) return;
  var drafts = shifts.filter(function (s) { return !s.published; }).length;
  var open = shifts.filter(function (s) { return !s.user_id; }).length;
  var bits = [];
  if (!shifts.length) bits.push('Nothing on this week yet. Add shifts with “+ Shift”, or copy last week and adjust.');
  else {
    bits.push(drafts ? '<b>' + drafts + ' draft shift' + (drafts > 1 ? 's' : '') + '</b> only managers can see.' : 'Everything on this week is posted.');
    if (open) bits.push(open + ' open shift' + (open > 1 ? 's' : '') + ' with nobody on ' + (open > 1 ? 'them' : 'it') + '.');
  }
  $('mgrStatus').innerHTML = bits.join(' ');
  $('postBtn').classList.toggle('hidden', !drafts);
  $('postBtn').textContent = 'Post ' + drafts + ' shift' + (drafts > 1 ? 's' : '');
  // Hours per person this week, drafts included, so nobody is over or under.
  var by = {};
  shifts.forEach(function (s) { if (s.user_id) by[s.user_id] = (by[s.user_id] || 0) + hoursOf(s); });
  var rows = people.filter(function (p) { return p.on_schedule; }).map(function (p) { return { name: p.name, h: by[p.user_id] || 0 }; })
    .sort(function (a, b) { return b.h - a.h; });
  $('hours').classList.toggle('hidden', !shifts.length);
  $('hours').innerHTML = '<span class="lbl">Hours this week</span>' + rows.map(function (r) {
    return '<span class="hr' + (r.h ? '' : ' zero') + '">' + escapeHtml(first(r.name)) + ' <b>' + hoursWord(r.h) + '</b></span>';
  }).join('');
}

// ---------- Staff: trade shifts ----------
async function offerShift(id, on) {
  var s = shifts.filter(function (x) { return x.id === id; })[0];
  if (on && !confirm('Offer up ' + niceDay(s.work_date) + ', ' + span(s) + '?\n\nEveryone on the schedule is told. It stays YOUR shift until someone takes it.')) return;
  var r = await sb.rpc('shift_offer', { p_shift: id, p_on: on });
  if (r.error) return fail(r);
  if (on) nudge();
  toast(on ? 'Offered. You’ll hear when someone takes it.' : 'Back on. It’s yours.');
  await loadWeek(); drawWeek();
}
async function takeShift(id) {
  var s = shifts.filter(function (x) { return x.id === id; })[0];
  var clash = shifts.filter(function (x) { return x.user_id === me.id && x.work_date === s.work_date; })[0];
  if (!confirm('Take ' + niceDay(s.work_date) + ', ' + span(s) + ' (' + s.position + ')?' +
      (clash ? '\n\nHeads up: you already work ' + span(clash) + ' that day.' : '') + '\n\nIt becomes your shift right away.')) return;
  var r = await sb.rpc('shift_take', { p_shift: id });
  if (r.error) { fail(r); await loadWeek(); drawWeek(); return; }
  nudge();
  toast('It’s yours. Thank you.');
  await loadWeek(); drawWeek();
}

// ---------- Managers: build the week ----------
function fillWho(selected) {
  var list = people.filter(function (p) { return p.on_schedule || p.user_id === selected; });
  $('sfWho').innerHTML = '<option value="">Open shift (anyone can take it)</option>' + list.map(function (p) {
    return '<option value="' + p.user_id + '"' + (p.user_id === selected ? ' selected' : '') + '>' + escapeHtml(p.name) + '</option>';
  }).join('');
}
function openShift(id, day) {
  editing = id ? shifts.filter(function (x) { return x.id === id; })[0] : null;
  var s = editing || {};
  var date = s.work_date || day, hrs = OPEN[fromIso(date).getDay()] || ['16:00', '21:00'];
  $('shiftTitle').textContent = editing ? 'Change a shift' : 'Add a shift';
  $('sfDate').value = date;
  $('sfStart').value = (s.start_time || hrs[0]).slice(0, 5);
  $('sfEnd').value = editing ? (s.end_time || '').slice(0, 5) : hrs[1];
  $('sfClose').checked = editing ? !s.end_time : false;
  $('sfEnd').disabled = $('sfClose').checked;
  $('sfPos').value = s.position || 'Bar';
  $('sfNote').value = s.note || '';
  fillWho(s.user_id || '');
  $('sfRemove').classList.toggle('hidden', !editing);
  $('sfAgain').classList.toggle('hidden', !!editing);
  $('sfLive').classList.toggle('hidden', !(editing && editing.published));
  $('sfLive').textContent = 'This shift is posted, so whoever it affects is told about the change.';
  drawWarn();
  $('shiftDialog').showModal();
}
$('sfClose').addEventListener('change', function () { $('sfEnd').disabled = this.checked; if (this.checked) $('sfEnd').value = ''; });
$('sfWho').addEventListener('change', drawWarn);
$('sfDate').addEventListener('change', drawWarn);
$('sfCancel').addEventListener('click', function () { $('shiftDialog').close(); });

// Things worth knowing before putting this person on this day. Warnings only:
// the manager can still save.
function drawWarn() {
  var uid = $('sfWho').value, day = $('sfDate').value, notes = [];
  if (uid && day) {
    var name = first(who(uid)), dow = fromIso(day).getDay();
    offOn(day).forEach(function (t) {
      if (t.user_id === uid) notes.push(name + (t.status === 'approved' ? ' has that day off.' : ' asked for that day off (not answered yet).'));
    });
    var a = avail.filter(function (x) { return x.user_id === uid; })[0];
    if (a && (a.off_days || []).indexOf(dow) !== -1) notes.push(name + ' can’t work ' + DAY_LONG[dow] + 's' + (a.note ? ' (' + a.note + ')' : '') + '.');
    (shifts || []).forEach(function (s) {
      if (s.user_id === uid && s.work_date === day && (!editing || s.id !== editing.id)) notes.push(name + ' already works that day: ' + span(s) + ' (' + s.position + ').');
    });
  }
  $('sfWarn').classList.toggle('hidden', !notes.length);
  $('sfWarn').innerHTML = notes.map(escapeHtml).join('<br>');
}

async function saveShift(again) {
  var row = {
    work_date: $('sfDate').value, start_time: $('sfStart').value,
    end_time: $('sfClose').checked || !$('sfEnd').value ? null : $('sfEnd').value,
    position: $('sfPos').value.trim() || 'Bar', user_id: $('sfWho').value || null, note: $('sfNote').value.trim()
  };
  if (!row.work_date || !row.start_time) return;
  $('sfSave').disabled = true;
  // Handing a shift to someone settles it, so it is no longer up for grabs.
  if (editing && row.user_id !== editing.user_id) row.up_for_grabs = false;
  var r = editing ? await sb.from('shifts').update(row).eq('id', editing.id) : await sb.from('shifts').insert(row);
  $('sfSave').disabled = false;
  if (r.error) return fail(r);
  if (editing && editing.published) nudge();
  var inWeek = row.work_date >= iso(weekStart) && row.work_date <= iso(addDays(weekStart, 6));
  if (!inWeek) weekStart = mondayOf(fromIso(row.work_date));
  await loadWeek(); drawWeek();
  if (again) { editing = null; fillWho(''); $('sfNote').value = ''; drawWarn(); toast('Added. Next one.'); return; }
  $('shiftDialog').close();
  toast(editing ? 'Saved.' : 'Added as a draft. Post it when the week is ready.');
}
$('shiftForm').addEventListener('submit', function (e) { e.preventDefault(); saveShift(false); });
$('sfAgain').addEventListener('click', function () { if ($('shiftForm').reportValidity()) saveShift(true); });
$('sfRemove').addEventListener('click', async function () {
  if (!editing || !confirm('Remove this shift?' + (editing.published && editing.user_id ? '\n\n' + first(who(editing.user_id)) + ' will be told.' : ''))) return;
  var r = await sb.from('shifts').delete().eq('id', editing.id);
  if (r.error) return fail(r);
  if (editing.published) nudge();
  $('shiftDialog').close();
  await loadWeek(); drawWeek();
  toast('Removed.');
});

$('postBtn').addEventListener('click', async function () {
  var drafts = shifts.filter(function (s) { return !s.published; }).length;
  if (!confirm('Post ' + drafts + ' shift' + (drafts > 1 ? 's' : '') + ' for ' + $('weekLabel').textContent + '?\n\nEveryone on the schedule is told their shifts.')) return;
  this.disabled = true;
  var r = await sb.rpc('schedule_publish', { p_from: iso(weekStart), p_to: iso(addDays(weekStart, 6)) });
  this.disabled = false;
  if (r.error) return fail(r);
  nudge();
  toast('Posted. Everyone has been told.');
  await loadWeek(); drawWeek();
});

// Last week's shifts, same people and times, as drafts on this week.
$('copyBtn').addEventListener('click', async function () {
  var from = addDays(weekStart, -7);
  var r = await sb.from('shifts').select('*').gte('work_date', iso(from)).lte('work_date', iso(addDays(from, 6)));
  if (r.error) return fail(r);
  if (!r.data.length) { toast('Last week has no shifts to copy.', true); return; }
  if (!confirm('Copy ' + r.data.length + ' shifts from last week onto this one as drafts?' +
      (shifts.length ? '\n\nThis week already has ' + shifts.length + ' shift' + (shifts.length > 1 ? 's' : '') + '; the copies are added on top.' : ''))) return;
  var rows = r.data.map(function (s) {
    return { work_date: iso(addDays(fromIso(s.work_date), 7)), start_time: s.start_time, end_time: s.end_time,
             position: s.position, user_id: s.user_id, note: s.note };
  });
  var ins = await sb.from('shifts').insert(rows);
  if (ins.error) return fail(ins);
  toast('Copied. Adjust, then post.');
  await loadWeek(); drawWeek();
});

// ---------- Time off, availability ----------
async function loadSide() {
  var since = iso(addDays(new Date(), -7));
  var t = await sb.from('time_off').select('*').gte('end_date', since).neq('status', 'cancelled').order('start_date');
  timeOff = t.data || [];
  var a = await sb.from('staff_availability').select('*');
  avail = a.data || [];
  drawOff(); drawAvail();
}

function drawOff() {
  var today = todayIso();
  // Managers: requests waiting on an answer come first, and the tab shows how many.
  var pending = isMgr ? timeOff.filter(function (t) { return t.status === 'pending' && t.user_id !== me.id; }) : [];
  $('offBadge').classList.toggle('hidden', !pending.length);
  $('offBadge').textContent = pending.length;
  $('offPending').innerHTML = !pending.length ? '' : '<h2 class="sub">Waiting on your answer</h2><div class="list asks">' + pending.map(function (t) {
    return '<div class="ask"><div><b>' + escapeHtml(who(t.user_id)) + '</b> asked for <b>' + niceRange(t.start_date, t.end_date) + '</b>' +
      (t.note ? '<div class="help">' + escapeHtml(t.note) + '</div>' : '') + '</div>' +
      '<div class="sh-acts"><button class="btn btn-sm btn-primary" onclick="decideOff(' + t.id + ', \'approved\')">Approve</button>' +
      '<button class="btn btn-sm" onclick="decideOff(' + t.id + ', \'denied\')">Decline</button></div></div>';
  }).join('') + '</div>';
  var list = timeOff.filter(function (t) { return t.end_date >= today && (t.user_id === me.id || t.status !== 'pending' || !isMgr); });
  $('offListLbl').textContent = isMgr ? 'Time off coming up' : 'Your requests';
  $('offList').innerHTML = !list.length ? '<p class="quiet">' + (isMgr ? 'Nobody has time off coming up.' : 'Nothing asked for.') + '</p>'
    : '<div class="list">' + list.map(function (t) {
    var mine = t.user_id === me.id;
    var word = { pending: 'Waiting', approved: 'Approved', denied: 'Declined' }[t.status];
    var act = mine && t.status !== 'denied' ? '<button class="btn-link" onclick="cancelOff(' + t.id + ')">Take it back</button>'
      : isMgr && t.status !== 'pending' ? '<button class="btn-link" onclick="decideOff(' + t.id + ', \'pending\')">Undo</button>' : '';
    return '<div class="row"><div><b>' + (mine ? '' : escapeHtml(who(t.user_id)) + ' · ') + niceRange(t.start_date, t.end_date) + '</b>' +
      (t.note ? '<div class="help">' + escapeHtml(t.note) + '</div>' : '') + '</div>' +
      '<div class="row-r"><span class="tag st-' + t.status + '">' + word + '</span>' + act + '</div></div>';
  }).join('') + '</div>';
}
$('offFrom').addEventListener('change', function () { if (!$('offTo').value || $('offTo').value < this.value) $('offTo').value = this.value; });
$('offForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  if ($('offTo').value < $('offFrom').value) { toast('The last day is before the first day.', true); return; }
  $('offBtn').disabled = true;
  var r = await sb.from('time_off').insert({ start_date: $('offFrom').value, end_date: $('offTo').value, note: $('offNote').value.trim() });
  $('offBtn').disabled = false;
  if (r.error) return fail(r);
  this.reset();
  nudge();
  toast('Asked. You’ll hear when a manager answers.');
  await loadSide(); drawWeek();
});
async function cancelOff(id) {
  if (!confirm('Take this request back?')) return;
  var r = await sb.from('time_off').update({ status: 'cancelled' }).eq('id', id);
  if (r.error) return fail(r);
  nudge();
  await loadSide(); drawWeek();
}
async function decideOff(id, status) {
  var r = await sb.from('time_off').update({
    status: status, decided_by: status === 'pending' ? null : first(who(me.id)), decided_at: status === 'pending' ? null : new Date().toISOString()
  }).eq('id', id);
  if (r.error) return fail(r);
  if (status !== 'pending') nudge();
  toast(status === 'approved' ? 'Approved. They’ve been told.' : status === 'denied' ? 'Declined. They’ve been told.' : 'Back to waiting.');
  await loadSide(); drawWeek();
}

function drawAvail() {
  var mine = avail.filter(function (a) { return a.user_id === me.id; })[0] || { off_days: [], note: '' };
  $('dayPick').innerHTML = [1, 2, 3, 4, 5, 6, 0].map(function (d) {
    return '<button type="button" class="chip' + (mine.off_days.indexOf(d) !== -1 ? ' on' : '') + '" data-d="' + d + '">' + DAY_SHORT[d] + '</button>';
  }).join('');
  $('availNote').value = mine.note || '';
  $('availAll').classList.toggle('hidden', !isMgr);
  var others = avail.filter(function (a) { return (a.off_days || []).length || a.note; });
  $('availAllList').innerHTML = !others.length ? '<p class="quiet">Nobody has marked any days.</p>' : '<div class="list">' + others.map(function (a) {
    var days = [1, 2, 3, 4, 5, 6, 0].filter(function (d) { return a.off_days.indexOf(d) !== -1; }).map(function (d) { return DAY_SHORT[d]; });
    return '<div class="row"><div><b>' + escapeHtml(who(a.user_id)) + '</b>' + (a.note ? '<div class="help">' + escapeHtml(a.note) + '</div>' : '') + '</div>' +
      '<div class="row-r">' + (days.length ? 'Can’t work ' + days.join(', ') : '') + '</div></div>';
  }).join('') + '</div>';
}
$('dayPick').addEventListener('click', function (e) { var c = e.target.closest('.chip'); if (c) c.classList.toggle('on'); });
$('availForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var days = [].map.call(document.querySelectorAll('#dayPick .chip.on'), function (c) { return +c.dataset.d; });
  $('availBtn').disabled = true;
  var r = await sb.from('staff_availability').upsert({ user_id: me.id, off_days: days, note: $('availNote').value.trim() }, { onConflict: 'user_id' });
  $('availBtn').disabled = false;
  if (r.error) return fail(r);
  toast('Saved. Managers see it when they build the week.');
  await loadSide();
});

// ---------- How to reach me ----------
function drawReach() {
  $('reachForm').classList.toggle('hidden', !myRow);
  if (!myRow) return;
  pickReach(myRow.notify_by || 'email');
  $('reachEmail').value = myRow.notify_email || '';
  $('reachPhone').value = myRow.notify_phone ? myRow.notify_phone.replace(/^(\d{3})(\d{3})(\d{4})$/, '$1-$2-$3') : '';
}
function pickReach(by) {
  document.querySelectorAll('#reachPick .chip').forEach(function (c) { c.classList.toggle('on', c.dataset.by === by); });
  $('reachPick').dataset.by = by;
  $('textsNote').classList.toggle('hidden', TEXTS_ON || (by !== 'text' && by !== 'both'));
}
$('reachPick').addEventListener('click', function (e) { var c = e.target.closest('.chip'); if (c) pickReach(c.dataset.by); });
$('reachForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var by = $('reachPick').dataset.by;
  if (!TEXTS_ON && by === 'text' && !$('reachEmail').value.trim()) { toast('Add your email too. Texts aren’t switched on yet.', true); return; }
  $('reachBtn').disabled = true;
  var r = await sb.rpc('schedule_save_me', { p_notify_by: by, p_email: $('reachEmail').value, p_phone: $('reachPhone').value });
  $('reachBtn').disabled = false;
  if (r.error) return fail(r);
  toast('Saved.');
  await loadPeople();
});

// ---------- Managers: who's on the schedule ----------
function drawPeople() {
  $('peopleSection').classList.toggle('hidden', !isMgr);
  if (!isMgr) return;
  $('peopleList').innerHTML = people.map(function (p) {
    return '<div class="row person"><input class="input" value="' + escapeHtml(p.name === p.username ? '' : p.name) + '" placeholder="Name for ' + escapeHtml(p.username) + '" aria-label="Name for ' + escapeHtml(p.username) + '">' +
      '<label class="check"><input type="checkbox"' + (p.on_schedule ? ' checked' : '') + '> On the schedule</label>' +
      '<span class="help">' + escapeHtml(p.username) + '</span>' +
      '<button class="btn btn-sm" onclick="savePerson(this, \'' + p.user_id + '\')">Save</button></div>';
  }).join('');
}
async function savePerson(btn, id) {
  var row = btn.closest('.row');
  var r = await sb.rpc('schedule_set_person', { p_user: id, p_name: row.querySelector('input.input').value, p_on: row.querySelector('input[type=checkbox]').checked });
  if (r.error) return fail(r);
  toast('Saved.');
  await loadPeople(); drawWeek();
}

// ---------- Notices ----------
async function loadNotices() {
  var r = await sb.from('schedule_outbox').select('id,kind,body,created_at').eq('user_id', me.id).is('seen_at', null)
    .order('created_at', { ascending: false }).limit(12);
  var rows = r.data || [];
  $('noticeSection').classList.toggle('hidden', !rows.length);
  $('notices').innerHTML = rows.map(function (n) {
    var when = new Date(n.created_at).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    return '<div class="notice"><div>' + escapeHtml(n.body) + '<small>' + when + '</small></div>' +
      '<button class="btn btn-sm" onclick="dismissNotice([' + n.id + '])">Got it</button></div>';
  }).join('');
  $('noticeClear').classList.toggle('hidden', rows.length < 2);
  $('noticeClear').onclick = function () { dismissNotice(rows.map(function (n) { return n.id; })); };
}
async function dismissNotice(ids) {
  var r = await sb.rpc('schedule_dismiss', { p_ids: ids });
  if (r.error) return fail(r);
  loadNotices();
}
