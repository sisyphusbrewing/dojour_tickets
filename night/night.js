// "Your night": the guest's page. What it is and the three ways in are at the
// top of index.html. This file asks the database what is going on
// (night_look), reads the tap list (the same feed the TV board uses), and
// draws the page for this moment of the night. It redraws every 20 seconds so
// "doors open in 12 min" stays true and a check-in at the door shows up on
// the guest's phone without them doing anything.

var SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co";
// The public key every page on this site uses. It opens nothing by itself:
// the database decides what a guest's phone may see.
var SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ";
var MENU_FEED = 'https://sisyphusmenu.stharriman.workers.dev/';
var ZONE = 'America/Chicago';

// A guest is never signed in, and this page must not touch a staff login
// saved on the same phone.
var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY,
  { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });

function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

var qs = new URLSearchParams(location.search);
var PREVIEW = qs.has('preview');
var KEY_STORE = 'sisyphus_night_key';

var key = null;        // this guest's private key, from their link or "Find my tickets"
var look = null;       // what the database last told us
var taps = null;       // the tap list, or null when it didn't load
var flatTaps = [];     // the same drinks in one list, so a tap on a row knows which drink it is
var skew = 0;          // the server's clock minus this phone's (a phone's clock can be wrong)
var picking = false;   // is the "pick a beer" list open
var busy = false;

// ---------- The guest's key ----------
(function () {
  var k = qs.get('k');
  if (k && /^[a-f0-9]{32}$/.test(k)) {
    key = k;
    try { localStorage.setItem(KEY_STORE, k); } catch (e) {}
  } else {
    try { key = localStorage.getItem(KEY_STORE); } catch (e) {}
    if (key && !/^[a-f0-9]{32}$/.test(key)) key = null;
  }
})();

// ---------- Preview (?preview=1): a made-up guest at any moment of the night ----------
// "min" is minutes from showtime. Nothing in preview is saved anywhere.
var MOMENTS = [
  { id: 'days',  label: 'Days before',  min: -3 * 24 * 60 },
  { id: 'today', label: 'Show day',     min: -200 },
  { id: 'doors', label: 'Doors open',   min: -22 },
  { id: 'in',    label: 'Checked in',   min: -18, here: true },
  { id: 'got',   label: 'Beer in hand', min: -12, here: true, poured: true },
  { id: 'show',  label: 'Show’s on',    min: 25,  here: true, poured: true },
  { id: 'after', label: 'After',        min: 230, here: true, poured: true },
  { id: 'tag',   label: 'No tickets yet (the tag by the door)', min: -22, stranger: true }
];
var moment = MOMENTS[0];
var previewShow = null, previewPicks = [], previewId = 1;

function previewLook() {
  var guest = moment.stranger ? null
    : { first: 'Sam', tickets: 2, reserved: false, checked_in: !!moment.here };
  return {
    found: !!guest, show: previewShow, guest: guest, also: [],
    picks: guest ? previewPicks.map(function (p) { return { id: p.id, item: p.item, price: p.price, poured: !!moment.poured }; }) : []
  };
}

// ---------- Time, always in Minneapolis time ----------
function nowMs() {
  if (PREVIEW && previewShow) return Date.parse(previewShow.starts_at) + moment.min * 60000;
  return Date.now() + skew;
}
function clock(ms) {       // "6:30 PM"
  return new Intl.DateTimeFormat('en-US', { timeZone: ZONE, hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
}
// The night a moment belongs to. A night runs past midnight, so the day
// turns over at 5 AM, the same as the door list.
function nightOf(ms) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms - 5 * 3600000));
}
function nightsUntil(startMs, now) {
  return Math.round((Date.parse(nightOf(startMs) + 'T00:00:00Z') - Date.parse(nightOf(now) + 'T00:00:00Z')) / 86400000);
}
function dayLabel(startMs, now) {   // Tonight, Tomorrow, Thursday, Sat, Feb 27
  var n = nightsUntil(startMs, now);
  if (n <= 0) {
    var hour = parseInt(new Intl.DateTimeFormat('en-US', { timeZone: ZONE, hour: 'numeric', hour12: false }).format(new Date(startMs)), 10);
    return hour >= 17 ? 'Tonight' : 'Today';
  }
  if (n === 1) return 'Tomorrow';
  if (n < 7) return new Intl.DateTimeFormat('en-US', { timeZone: ZONE, weekday: 'long' }).format(new Date(startMs));
  return new Intl.DateTimeFormat('en-US', { timeZone: ZONE, weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(startMs));
}
function span(ms) {        // "18 min", "2 hr 10 min"
  var m = Math.max(1, Math.round(ms / 60000));
  if (m < 60) return m + ' min';
  var h = Math.floor(m / 60), r = m % 60;
  return h + ' hr' + (r ? ' ' + r + ' min' : '');
}
function countWord(n, word) { return n + ' ' + word + (n === 1 ? '' : 's'); }
function listOf(names) {   // "Lager", "Lager and IPA", "Lager, IPA and Cider"
  if (names.length < 2) return names.join('');
  return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
}

// When the showroom doors open. Half an hour before the show (the website's
// FAQ says so). The second show of a night has no set time: its doors open
// when the early show lets out, "closer to showtime", so the page never
// promises a time for it and only treats the last 15 minutes as "open".
function doorsMs(show) {
  var start = Date.parse(show.starts_at);
  return start - (show.late ? 15 : 30) * 60000;
}

// Which part of the night it is:
//   days   the show is on a later night
//   today  tonight, before doors
//   doors  doors are open, the show hasn't started
//   show   the show is on (for three hours from its start)
//   after  it's over
//   unknown  the show isn't on the calendar, so we have no clock for it
function stageOf(now, show) {
  if (!show || !show.starts_at) return 'unknown';
  var start = Date.parse(show.starts_at);
  if (now >= start + 3 * 3600000) return 'after';
  if (now >= start) return 'show';
  if (!show.free && now >= doorsMs(show)) return 'doors';
  return nightsUntil(start, now) <= 0 ? 'today' : 'days';
}

// ---------- The blue box: what is happening right now ----------
function nowCard(c) {
  var name = c.G && c.G.first ? ', ' + esc(c.G.first) : '';
  var tix = c.G ? countWord(c.G.tickets, 'ticket') : '';
  var waiting = c.P.filter(function (p) { return !p.poured; });
  var toShow = c.start ? span(c.start - c.now) : '';

  if (c.st === 'unknown') {
    return { live: 'Sisyphus', head: c.G ? 'You’re on the list' + name + '.' : 'See you at the show.',
             body: c.G ? tix + ' under your name. Nothing to print, nothing to scan.' : '' };
  }
  if (c.st === 'after') {
    return { live: 'Good night', head: 'That was the show.', body: 'Thanks for coming' + name + '. Get home safe.' };
  }
  if (c.S.free) {
    if (c.st === 'show') return { live: 'On now', on: true, head: 'It’s on. Come in.', body: 'No ticket and no list. Get a beer and find a seat.' };
    return { live: c.st === 'today' ? 'Starts in ' + toShow : dayLabel(c.start, c.now),
             head: 'Free. Just walk in.', body: 'No ticket and no list. Get a beer and find a seat.' };
  }
  // The door has checked them in.
  if (c.G && c.G.checked_in) {
    var body;
    if (waiting.length) {
      body = 'Head to the bar. Your ' + esc(listOf(waiting.map(function (p) { return p.item; }))) +
             (waiting.length > 1 ? ' are' : ' is') + ' being poured.';
    } else if (c.P.length) {
      body = c.st === 'show' ? 'Enjoy the show.' : 'Beer in hand. Go find a seat.';
    } else {
      body = c.st === 'show' ? 'Find a seat and settle in.' : 'Get a beer at the bar, then find a seat.';
    }
    return { live: c.st === 'show' ? 'The show is on' : 'Show starts in ' + toShow, on: true, head: 'You’re in' + name + '.', body: body };
  }
  if (c.st === 'days') {
    var n = nightsUntil(c.start, c.now);
    return { live: n === 1 ? 'Tomorrow' : 'In ' + n + ' days',
             head: c.G ? 'You’re on the list' + name + '.' : 'See you ' + (n === 1 ? 'tomorrow' : dayLabel(c.start, c.now)) + '.',
             body: c.G ? tix + ' under your name. Nothing to print, nothing to scan.' : 'Give your name at the door. Nothing to print, nothing to scan.' };
  }
  if (c.st === 'today') {
    return { live: c.S.late ? 'Tonight' : 'Doors open in ' + span(c.doors - c.now),
             head: c.G ? 'You’re on the list' + name + '.' : (c.S.late ? 'Doors open close to showtime.' : 'Doors open at ' + clock(c.doors) + '.'),
             body: (c.G ? tix + ' under your name. ' : '') + 'Early? The taproom’s open. Come get a beer first.' };
  }
  if (c.st === 'doors') {
    return { live: 'Doors are open', on: true, head: 'Come on in' + name + '.',
             body: 'The show starts in ' + toShow + '.' +
                   (waiting.length ? ' Your ' + esc(listOf(waiting.map(function (p) { return p.item; }))) +
                                     (waiting.length > 1 ? ' get' : ' gets') + ' poured when you check in.' : '') };
  }
  return { live: 'The show is on', on: true, head: 'The show’s on.', body: 'Just getting here? Give your name at the door.' };
}

// ---------- The steps of the night ----------
// Each step: its name, what to say, and (for the first two) a shorter line
// once it's behind you. "here" is the step this guest is at right now.
function buildSteps(c) {
  var known = !!c.G, free = c.S.free, steps = [], here = -1;

  steps.push({ id: 'get', title: 'Getting here',
    html: '<p>712 Ontario Ave W, Minneapolis. The door is around the corner, on Aldrich.</p>' +
          '<p class="small">Parking is free: on the street, or in our lot behind the building.</p>' +
          '<div class="btn-row">' +
            '<a class="btn" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=Sisyphus+Brewing%2C+712+Ontario+Ave+W%2C+Minneapolis%2C+MN">Directions</a>' +
            '<a class="btn" target="_blank" rel="noopener" href="https://sisyphusbrewing.com/pages/parking">Parking map</a>' +
          '</div>',
    done: '<p>712 Ontario Ave W. The door is on Aldrich.</p>' });

  if (!free) {
    steps.push({ id: 'door', title: 'At the door',
      html: '<p>Give your name. That’s the whole ticket: nothing to print, nothing to scan.</p>' +
            (c.st === 'days' || c.st === 'today' || c.st === 'unknown'
              ? '<p class="small">Early? The taproom is open. Get a beer and hang out until the showroom doors open.</p>' : ''),
      done: '<p>You’re checked in.</p>' });
  }

  steps.push({ id: 'beer', title: 'Your first beer',
    html: known && !free && c.st !== 'after' ? roundHtml(c)
        : '<p>Order at the bar on your way in. What’s pouring is below.</p>' +
          (!known && !free && c.st !== 'after'
            ? '<p class="small">Have tickets? Find them and your first beer can be waiting for you.</p>' +
              '<div class="btn-row"><button class="btn btn-white" type="button" id="findBtn">Find my tickets</button></div>' : '') });

  steps.push({ id: 'seat', title: 'Find a seat',
    html: free ? '<p>Sit anywhere. Your beer comes with you.</p>'
        : known && c.G.reserved ? '<p>Your seats are reserved. Look for the table with your name on it. Your beer comes in with you.</p>'
        : '<p>Seats are first come, so take any open one. Your beer comes in with you.</p>' });

  steps.push({ id: 'show', title: 'The show',
    html: free ? '<p>Want another? The bar’s right there.</p>'
        : '<p>Want another one? The card on your table orders from your phone, and we bring it to you.</p>' });

  // Where they are.
  function at(id) { for (var i = 0; i < steps.length; i++) if (steps[i].id === id) return i; return -1; }
  var waiting = c.P.some(function (p) { return !p.poured; });
  if (c.st === 'after') here = steps.length;                          // all behind them
  else if (c.st === 'unknown') here = -1;                             // no clock: mark nothing
  else if (free) here = c.st === 'show' ? at('show') : at('get');
  else if (known && c.G.checked_in) here = (waiting || (!c.P.length && c.st !== 'show')) ? at('beer') : (c.st === 'show' ? at('show') : at('seat'));
  else if (c.st === 'doors') here = at('door');
  else if (c.st === 'show') here = known ? at('door') : at('show');
  else here = at('get');

  return { steps: steps, here: here };
}

// "Your first beer", for a guest we know.
function roundHtml(c) {
  var P = c.P, max = c.G.tickets, html = '';
  if (!P.length) html += '<p>Pick it now and we pour it when you check in. You pay at the bar when you pick it up.</p>';
  if (P.length) {
    html += '<div class="round"><div class="round-top">Your first round</div>' + P.map(function (p) {
      var right = p.poured ? '<span class="state">Handed over</span>'
                : c.G.checked_in ? '<span class="state">Being poured</span>'
                : '<button type="button" data-unpick="' + esc(p.id) + '">Take off</button>';
      return '<div class="round-row"><b>' + esc(p.item) + '</b>' + right + '</div>';
    }).join('') + '</div>';
    if (P.some(function (p) { return !p.poured; })) {
      html += '<p class="small">' + (c.G.checked_in ? 'It’s at the bar. You pay when you pick it up.'
                                                    : 'We pour when you check in. You pay at the bar when you pick it up.') + '</p>';
    }
  }
  if (P.length < max) {
    if (picking) html += pickListHtml();
    else html += '<div class="btn-row"><button class="btn btn-white" type="button" id="pickOpen">' +
                 (P.length ? 'Pick one more' : 'Pick my first beer') + '</button></div>';
  }
  return html;
}

function pickListHtml() {
  if (!taps) return '<p class="small">The tap list isn’t loading right now. Order at the bar when you get here.</p>';
  var i = 0;
  return '<div class="taps pick-list">' + taps.map(function (g) {
    return '<div class="grp">' + esc(g.group) + '</div>' + g.items.map(function (d) {
      return '<button class="tap" type="button" data-pick="' + (i++) + '"><span class="what"><b>' + esc(d.name) + '</b>' +
             (d.sub ? '<small>' + esc(d.sub) + '</small>' : '') + '</span><span class="plus" aria-hidden="true">+</span></button>';
    }).join('');
  }).join('') + '</div><div class="btn-row"><button class="btn btn-ghost" type="button" id="pickClose">Not now</button></div>';
}

// ---------- Draw the page ----------
function render() {
  var L = PREVIEW ? previewLook() : look;
  $('loading').classList.add('hidden');
  if (!L || !L.show) {
    $('page').classList.add('hidden');
    $('noShow').classList.remove('hidden');
    return;
  }
  $('noShow').classList.add('hidden');
  $('page').classList.remove('hidden');

  var S = L.show, now = nowMs();
  var c = { S: S, G: L.found ? L.guest : null, P: L.picks || [], now: now,
            start: S.starts_at ? Date.parse(S.starts_at) : null, doors: S.starts_at ? doorsMs(S) : null, st: stageOf(now, S) };

  $('eyebrow').textContent = (c.start ? dayLabel(c.start, now) : 'Coming up') + ' at Sisyphus';
  $('showTitle').textContent = S.title;
  $('times').textContent = !c.start ? (S.when || '')
    : S.free ? clock(c.start) + ' · Free, no ticket needed'
    : S.late ? 'Show ' + clock(c.start) + ' · Doors open close to showtime'
    : 'Doors ' + clock(c.doors) + ' · Show ' + clock(c.start);

  var card = nowCard(c);
  $('nowLive').textContent = card.live;
  $('nowDot').className = 'dot' + (card.on ? ' on' : '');
  $('nowHead').innerHTML = card.head;
  $('nowBody').innerHTML = card.body;
  $('nowBody').classList.toggle('hidden', !card.body);

  var also = (L.also || []).filter(function (a) { return a.starts_at; });
  $('also').classList.toggle('hidden', !also.length);
  if (also.length) {
    $('also').textContent = 'Also ' + dayLabel(Date.parse(also[0].starts_at), now).toLowerCase() + ': ' + also.map(function (a) {
      return a.title + ' at ' + clock(Date.parse(a.starts_at)) + (a.free ? ' (free)' : '');
    }).join(', ') + '.';
  }

  var built = buildSteps(c);
  $('path').innerHTML = built.steps.map(function (s, i) {
    var done = i < built.here, here = i === built.here;
    return '<li class="stop' + (done ? ' done' : '') + (here ? ' here' : '') + '">' +
           '<span class="num" aria-hidden="true">' + (done ? '✓' : (i + 1)) + '</span>' +
           '<h3>' + esc(s.title) + (here ? '<span class="here-tag">You are here</span>' : '') + '</h3>' +
           (done && s.done ? s.done : s.html) + '</li>';
  }).join('');

  // The tap list at the bottom.
  $('tapBox').classList.toggle('hidden', !taps);
  if (taps) {
    $('tapBand').textContent = c.st === 'days' ? 'On tap right now' : 'On tap tonight';
    $('taps').innerHTML = taps.map(function (g) {
      return '<div class="grp">' + esc(g.group) + '</div>' + g.items.map(function (d) {
        return '<div class="tap"><span class="what"><b>' + esc(d.name) + '</b>' + (d.sub ? '<small>' + esc(d.sub) + '</small>' : '') +
               '</span><span class="price">' + esc(d.priceText) + '</span></div>';
      }).join('');
    }).join('');
  }

  $('notYou').classList.toggle('hidden', PREVIEW || !c.G);
}

// ---------- The tap list ----------
// The feed's descriptions look like "Rice Lager\n4.5% ABV 8 IBU\nA long
// story about the beer". We keep the short first line and the ABV.
function drinkFrom(item) {
  var style = '', abv = '';
  String(item.description || '').split('\n').forEach(function (raw) {
    var l = raw.trim();
    var m = l.match(/(\d+(?:\.\d+)?)\s*%\s*ABV/i);
    if (m) { if (!abv) abv = m[1] + '%'; return; }
    l = l.replace(/^\d+(?:\.\d+)?\s*oz\b\s*/i, '');
    if (!style && l && l.length <= 40 && !/[.!?]$/.test(l)) style = l;
  });
  var price = parseFloat(item.price);
  return { name: String(item.name || '').trim(), sub: [style, abv].filter(Boolean).join(' · '),
           price: isNaN(price) ? null : price,
           priceText: isNaN(price) ? '' : '$' + (price % 1 === 0 ? price.toFixed(0) : price.toFixed(2)) };
}
async function loadTaps() {
  try {
    var res = await fetch(MENU_FEED);
    var data = await res.json();
    var groups = (data.sections || []).filter(function (s) { return !/snack|food|merch/i.test(s.category || ''); }).map(function (s) {
      var cat = String(s.category || '').trim();
      if (cat === cat.toUpperCase()) cat = cat.charAt(0) + cat.slice(1).toLowerCase();   // "BEER ON TAP" -> "Beer on tap"
      return { group: cat, items: (s.items || []).map(drinkFrom).filter(function (d) { return d.name; }) };
    }).filter(function (g) { return g.items.length; });
    if (!groups.length) return;
    taps = groups;
    flatTaps = [];
    groups.forEach(function (g) { g.items.forEach(function (d) { flatTaps.push(d); }); });
    render();
  } catch (e) { /* no tap list: the page says to order at the bar */ }
}

// ---------- Asking the database ----------
function plain(error) {   // what to tell a guest when something goes wrong
  var m = error && error.message ? String(error.message) : '';
  if (!m || /fetch|network|load failed/i.test(m)) return 'Couldn’t reach us. Check your signal and try again.';
  return m;
}
async function load() {
  if (PREVIEW) { render(); return; }
  var r;
  try { r = await sb.rpc('night_look', { p_key: key }); } catch (e) { r = { error: e }; }
  if (r.error || !r.data) {
    if (!look) $('loading').textContent = 'This page isn’t loading right now. Give your name at the door and you’re all set.';
    return;
  }
  look = r.data;
  if (look.now) skew = Date.parse(look.now) - Date.now();
  render();
}

async function pick(i) {
  var d = flatTaps[i];
  if (!d || busy) return;
  if (PREVIEW) {
    previewPicks.push({ id: previewId++, item: d.name, price: d.price });
    if (previewPicks.length >= 2) picking = false;
    render(); toast(d.name + '. Got it.');
    return;
  }
  busy = true;
  var r;
  try { r = await sb.rpc('night_pick', { p_key: key, p_item: d.name, p_price: d.price }); } catch (e) { r = { error: e }; }
  busy = false;
  if (r.error) { toast(plain(r.error)); return; }
  look = r.data;
  if (look.guest && (look.picks || []).length >= look.guest.tickets) picking = false;
  render(); toast(d.name + '. Got it.');
}
async function unpick(id) {
  if (busy) return;
  if (PREVIEW) {
    previewPicks = previewPicks.filter(function (p) { return String(p.id) !== String(id); });
    render();
    return;
  }
  busy = true;
  var r;
  try { r = await sb.rpc('night_unpick', { p_key: key, p_pick: parseInt(id, 10) }); } catch (e) { r = { error: e }; }
  busy = false;
  if (r.error) { toast(plain(r.error)); return; }
  look = r.data;
  render();
}

var toastTimer = null;
function toast(msg) {
  var el = $('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.classList.add('hidden'); }, 3200);
}

// ---------- Taps and clicks ----------
$('path').addEventListener('click', function (e) {
  var t = e.target.closest('button');
  if (!t) return;
  if (t.id === 'pickOpen') { picking = true; render(); }
  else if (t.id === 'pickClose') { picking = false; render(); }
  else if (t.id === 'findBtn') {
    if (PREVIEW) { toast('In the real page this asks for their email and last name.'); return; }
    $('findErr').classList.add('hidden');
    $('findSheet').showModal();
  }
  else if (t.dataset.pick != null) pick(parseInt(t.dataset.pick, 10));
  else if (t.dataset.unpick != null) unpick(t.dataset.unpick);
});

$('findCancel').addEventListener('click', function () { $('findSheet').close(); });
$('findForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var btn = $('findGo'), err = $('findErr');
  err.classList.add('hidden');
  btn.disabled = true; btn.textContent = 'Looking…';
  var r;
  try { r = await sb.rpc('night_find', { p_email: $('findEmail').value, p_last: $('findLast').value }); } catch (ex) { r = { error: ex }; }
  btn.disabled = false; btn.textContent = 'Find them';
  if (r.error) { err.textContent = plain(r.error); err.classList.remove('hidden'); return; }
  if (!r.data) {
    err.textContent = 'We couldn’t match that. Check the email on your order. Either way, your name is on the list at the door.';
    err.classList.remove('hidden');
    return;
  }
  key = r.data;
  try { localStorage.setItem(KEY_STORE, key); } catch (ex) {}
  $('findSheet').close();
  await load();
  toast('Found you.');
});

$('forget').addEventListener('click', function (e) {
  e.preventDefault();
  try { localStorage.removeItem(KEY_STORE); } catch (ex) {}
  location.href = location.pathname;
});

// ---------- Start ----------
async function startPreview() {
  document.body.classList.add('previewing');
  $('preview').classList.remove('hidden');
  // Use a real upcoming show so the names and times on screen are real. A
  // ticketed one if there is one (a free night has no door list to preview).
  try {
    var r = await sb.rpc('night_look', { p_key: null });
    var shows = r.data && r.data.show ? [r.data.show].concat(r.data.also || []) : [];
    previewShow = shows.filter(function (s) { return !s.free && s.starts_at; })[0] || shows[0] || null;
  } catch (e) {}
  if (!previewShow) {
    // The calendar didn't answer: a stand-in show at 7 PM Minneapolis time.
    var hourNow = parseInt(new Intl.DateTimeFormat('en-US', { timeZone: ZONE, hour: 'numeric', hour12: false }).format(new Date()), 10) % 24;
    var seven = new Date(Date.now() + (19 - hourNow) * 3600000); seven.setMinutes(0, 0, 0);
    previewShow = { title: 'Tonight’s Headliner', when: '', starts_at: seven.toISOString(), free: false, late: false };
  }
  previewShow = { title: previewShow.title, when: previewShow.when, starts_at: previewShow.starts_at, free: false, late: false };
  var want = qs.get('at');
  MOMENTS.forEach(function (m) { if (m.id === want) moment = m; });
  $('previewRow').innerHTML = MOMENTS.map(function (m) {
    return '<button type="button" data-moment="' + m.id + '">' + esc(m.label) + '</button>';
  }).join('');
  function mark() {
    Array.prototype.forEach.call($('previewRow').children, function (b) { b.classList.toggle('on', b.dataset.moment === moment.id); });
  }
  $('previewRow').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    MOMENTS.forEach(function (m) { if (m.id === b.dataset.moment) moment = m; });
    picking = false;
    mark(); render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  mark(); render();
}

if (PREVIEW) startPreview(); else load();
loadTaps();

// Keep the clock honest, and on a show night ask the database again so a
// check-in at the door or a beer handed over shows up by itself.
setInterval(function () {
  if (document.hidden || PREVIEW || !look || picking || $('findSheet').open) return;
  var st = stageOf(nowMs(), look.show);
  if (st === 'today' || st === 'doors' || st === 'show') load(); else render();
}, 20000);
document.addEventListener('visibilitychange', function () { if (!document.hidden && !PREVIEW) load(); });
