// The gift card page. See index.html for what it is and who uses it.
// Who may do what, and every balance, is the database's call
// (supabase/migrations/20261118000000_gift_cards.sql); this file only shows
// and asks.

var TZ = 'America/Chicago';
var UNDO_MS = 2 * 60 * 1000;          // the database lets you undo your own change for two minutes
var code = null;                      // the card's code, from the link on the card (?c=...)
var role = null;                      // null = nobody signed in (a guest)
var card = null;                      // what the database said about this card
var lastMove = null, lastMoveAt = 0, undoTimer = null;
var mode = 'spend', busy = false, offNumber = null, cards = [];

(function () {
  try { code = (new URLSearchParams(location.search).get('c') || '').trim().toLowerCase() || null; } catch (e) {}
})();

function money(n) {
  var v = Number(n || 0);
  return (v < 0 ? '−$' : '$') + Math.abs(v).toFixed(2).replace(/\.00$/, '');
}
function money2(n) { return '$' + Math.abs(Number(n || 0)).toFixed(2); }
function when(ts) {
  var d = new Date(ts);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: TZ }) + ', ' +
         d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ });
}
function isStaff() { return !!role && roleAtLeast(role, 'staff'); }
function isMgr() { return !!role && roleAtLeast(role, 'manager'); }
function show(id, on) { $(id).classList.toggle('hidden', !on); }
function errText(r) {
  var m = (r && r.error && r.error.message) || 'Something went wrong.';
  if (/fetch|network/i.test(m)) return 'Could not reach the server. Check the wifi.';
  return m;
}

// ---------- Start ----------
async function start() {
  role = null;
  try {
    var s = await sb.auth.getSession();
    if (s.data && s.data.session) { var r = await sb.rpc('my_role'); role = r.data || 'door'; }
  } catch (e) {}
  show('loading', false);
  if (code) {
    if (isStaff()) $('homeLink').href = '/gift/';
    await loadCard();
  } else if (isStaff()) {
    $('homeLink').href = '/staff/';
    show('homeView', true);
    if (isMgr()) { show('mgrPart', true); loadCards(); loadReport(); }
  } else {
    // Opened with no card and nobody signed in: this is the staff side.
    show('lock', true);
    show('lockClose', false);
  }
  show('staffLink', !!code && !isStaff());
}

// ---------- The card ----------
async function loadCard() {
  var r = await sb.rpc('gift_card_look', { p_code: code });
  if (r.error) { show('cardView', false); toast(errText(r), true); return; }
  card = r.data;
  if (!card.found) { show('notFound', true); show('cardView', false); return; }
  show('cardView', true);
  drawCard();
}

function drawCard() {
  $('cardNo').textContent = '#' + card.number;
  $('bal').textContent = money(card.balance);
  $('gcard').classList.toggle('off', !card.active);
  if (!card.active) {
    $('balSub').textContent = 'Switched off';
    $('guestNote').textContent = 'This card was switched off. Ask at the bar.';
  } else if (!card.loaded) {
    $('balSub').textContent = 'Not loaded yet';
    $('guestNote').innerHTML = 'Buy it at the bar and it’s ready to go.';
  } else {
    $('balSub').textContent = Number(card.balance) > 0 ? 'left on this card' : 'Nothing left. Top it up at the bar.';
    $('guestNote').innerHTML = 'Spend it on beer, food or a show at the bar.<br>Hand the card to your bartender.';
  }
  var staff = !!card.staff;
  show('guestNote', !staff);
  show('staffActs', staff);
  if (!staff) return;
  show('spendBtn', card.active);
  show('loadBtn', card.active && card.can_load);
  $('spendBtn').disabled = Number(card.balance) <= 0;
  if (!card.active) {
    $('offNote').textContent = 'This card was switched off' + (card.off_reason ? ' (' + card.off_reason + ')' : '') +
      (card.moved_to ? '. Its money went to card #' + card.moved_to + '.' : '.');
  }
  show('offNote', !card.active);
  drawMoves();
}

var KIND = { load: 'Put on', spend: 'Taken off', undo: 'Undone', move_in: 'Moved here', move_out: 'Moved away' };
function drawMoves() {
  var m = card.moves || [];
  if (!m.length) { $('moves').innerHTML = '<div class="quiet">Nothing yet.</div>'; return; }
  $('moves').innerHTML = m.map(function (x) {
    var plus = Number(x.amount) > 0;
    return '<div class="mv' + (x.undone ? ' undone' : '') + '"><div class="what"><b>' + KIND[x.kind] + '</b>' +
      (x.note ? ' · ' + escapeHtml(x.note) : '') +
      '<span class="when">' + when(x.at) + (x.by ? ' · ' + escapeHtml(x.by) : '') + '</span></div>' +
      '<div class="amt' + (plus ? ' plus' : '') + '"><span>' + (plus ? '+' : '−') + money2(x.amount) + '</span>' +
      '<small>' + money(x.balance_after) + ' left</small></div></div>';
  }).join('');
}

// ---------- Take off / Put on ----------
function openAmount(which) {
  mode = which;
  var spend = which === 'spend';
  $('amtTitle').textContent = spend ? 'Take off card #' + card.number : 'Put on card #' + card.number;
  $('amtHelp').textContent = spend
    ? money(card.balance) + ' on the card. Take off the tab total, or all of it if the tab is more.'
    : 'Ring the gift card in GoTab first, then put the same amount on here.';
  $('amtGo').textContent = spend ? 'Take off' : 'Put on';
  $('amt').value = '';
  $('amtNote').value = '';
  show('amtErr', false);
  var q = spend ? [{ t: 'All of it (' + money(card.balance) + ')', v: Number(card.balance) }]
                : [25, 50, 75, 100].map(function (v) { return { t: '$' + v, v: v }; });
  $('quick').innerHTML = q.map(function (x) {
    return '<button type="button" class="chip" data-v="' + x.v + '">' + x.t + '</button>';
  }).join('');
  $('amtSheet').showModal();
  setTimeout(function () { $('amt').focus(); }, 50);
}
$('quick').addEventListener('click', function (e) {
  var b = e.target.closest('.chip'); if (!b) return;
  $('amt').value = Number(b.dataset.v).toFixed(2);
});
$('spendBtn').addEventListener('click', function () { openAmount('spend'); });
$('loadBtn').addEventListener('click', function () { openAmount('load'); });
$('amtCancel').addEventListener('click', function () { $('amtSheet').close(); });

$('amtForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  if (busy) return;
  var v = Number(String($('amt').value).replace(/[$,\s]/g, ''));
  if (!(v > 0)) { $('amtErr').textContent = 'Type an amount.'; show('amtErr', true); return; }
  busy = true; $('amtGo').disabled = true;
  var fn = mode === 'spend' ? 'gift_card_spend' : 'gift_card_load';
  var r = await sb.rpc(fn, { p_code: code, p_amount: Math.round(v * 100) / 100, p_note: $('amtNote').value || null });
  busy = false; $('amtGo').disabled = false;
  if (r.error) { $('amtErr').textContent = errText(r); show('amtErr', true); return; }
  $('amtSheet').close();
  chime(true);
  lastMove = r.data.move; lastMoveAt = Date.now();
  $('doneText').textContent = (mode === 'spend' ? 'Took ' + money2(v) + ' off. ' : 'Put ' + money2(v) + ' on. ') +
    money(r.data.balance) + ' left.';
  showDone(true);
  await loadCard();
});

function showDone(canUndo) {
  show('done', true);
  show('undoBtn', canUndo);
  clearTimeout(undoTimer);
  if (canUndo) undoTimer = setTimeout(function () { show('undoBtn', false); }, UNDO_MS - 5000);
}
$('undoBtn').addEventListener('click', async function () {
  if (busy || !lastMove) return;
  busy = true;
  var r = await sb.rpc('gift_card_undo', { p_move: lastMove });
  busy = false;
  if (r.error) { toast(errText(r), true); return; }
  lastMove = null;
  $('doneText').textContent = 'Undone. ' + money(r.data.balance) + ' on the card.';
  showDone(false);
  await loadCard();
});

// ---------- Staff, no card: open one by its number ----------
$('findForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var n = parseInt($('findNo').value, 10);
  if (!n) return;
  var r = await sb.rpc('gift_card_find', { p_number: n });
  if (r.error) { toast(errText(r), true); return; }
  location.href = '/gift/?c=' + encodeURIComponent(r.data);
});

// ---------- Managers: every card, totals, this week ----------
async function loadCards() {
  var r = await sb.rpc('gift_cards_list');
  if (r.error) { $('cardList').innerHTML = '<div class="quiet">' + escapeHtml(errText(r)) + '</div>'; return; }
  cards = r.data.cards || [];
  var out = cards.filter(function (c) { return c.active && c.loaded; }).length;
  var blank = cards.filter(function (c) { return c.active && !c.loaded; }).length;
  $('totals').innerHTML =
    '<div><b>' + money(r.data.outstanding) + '</b><span>still on cards</span></div>' +
    '<div><b>' + out + '</b><span>cards in use</span></div>' +
    '<div><b>' + blank + '</b><span>blank cards</span></div>';
  if (!cards.length) { $('cardList').innerHTML = '<div class="quiet">No cards yet. Make one above.</div>'; return; }
  $('cardList').innerHTML = cards.map(function (c, i) {
    var sub = !c.active ? 'Switched off' : !c.loaded ? 'Blank: write its link, then put money on'
            : money(c.balance) + ' left' + (c.last ? ' · last used ' + when(c.last) : '');
    return '<div class="crow' + (c.active ? '' : ' off') + '"><div class="what"><b>Card #' + c.number + '</b><span>' + sub + '</span></div>' +
      '<div class="acts">' +
      (c.active ? '<button class="btn btn-sm" data-copy="' + i + '">Copy link</button>' : '') +
      '<a class="btn btn-sm" href="/gift/?c=' + c.code + '">Open</a>' +
      (c.active ? '<button class="btn btn-sm btn-ghost" data-off="' + i + '" aria-label="Switch off card #' + c.number + '">⋯</button>' : '') +
      '</div></div>';
  }).join('');
}
$('cardList').addEventListener('click', async function (e) {
  var b = e.target.closest('button'); if (!b) return;
  if (b.dataset.copy != null) {
    var c = cards[+b.dataset.copy];
    var link = location.origin + '/gift/?c=' + c.code;
    try { await navigator.clipboard.writeText(link); toast('Link for card #' + c.number + ' copied. Paste it into NFC Tools.'); }
    catch (ex) { window.prompt('Copy this link', link); }
  }
  if (b.dataset.off != null) openOff(cards[+b.dataset.off]);
});
async function make(n) {
  if (busy) return;
  busy = true;
  var r = await sb.rpc('gift_cards_make', { p_count: n });
  busy = false;
  if (r.error) { toast(errText(r), true); return; }
  toast(n === 1 ? 'Card made.' : n + ' cards made.');
  loadCards();
}
$('make1').addEventListener('click', function () { make(1); });
$('make10').addEventListener('click', function () { make(10); });

// Monday to today, Minneapolis.
async function loadReport() {
  var t = new Date().toLocaleDateString('en-CA', { timeZone: TZ });
  var d = new Date(t + 'T12:00:00');
  var back = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - back);
  var from = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  var r = await sb.rpc('gift_card_report', { p_from: from, p_to: t });
  if (r.error) { $('repSum').textContent = errText(r); return; }
  $('repSum').textContent = 'Since Monday: ' + money(r.data.sold) + ' sold, ' + money(r.data.spent) + ' spent. These should match the gift card lines in GoTab.';
  var m = r.data.moves || [];
  $('repList').innerHTML = m.length ? m.slice(0, 50).map(function (x) {
    var plus = Number(x.amount) > 0;
    return '<div class="mv"><div class="what"><b>#' + x.number + ' ' + KIND[x.kind] + '</b>' + (x.note ? ' · ' + escapeHtml(x.note) : '') +
      '<span class="when">' + when(x.at) + (x.by ? ' · ' + escapeHtml(x.by) : '') + '</span></div>' +
      '<div class="amt' + (plus ? ' plus' : '') + '"><span>' + (plus ? '+' : '−') + money2(x.amount) + '</span></div></div>';
  }).join('') : '<div class="quiet">Nothing yet this week.</div>';
}

// ---------- Switch off a lost card ----------
function openOff(c) {
  offNumber = c.number;
  $('offTitle').textContent = 'Switch off card #' + c.number;
  $('offTo').value = '';
  $('offWhy').value = '';
  show('offToBox', Number(c.balance) > 0);
  show('offErr', false);
  $('offSheet').showModal();
}
$('offCancel').addEventListener('click', function () { $('offSheet').close(); });
$('offForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  if (busy) return;
  var to = parseInt($('offTo').value, 10) || null;
  busy = true;
  var r = await sb.rpc('gift_card_switch_off', { p_number: offNumber, p_to_number: to, p_reason: $('offWhy').value || null });
  busy = false;
  if (r.error) { $('offErr').textContent = errText(r); show('offErr', true); return; }
  $('offSheet').close();
  toast('Card #' + offNumber + ' switched off' + (r.data.to ? ', ' + money(r.data.moved) + ' moved to #' + r.data.to : '') + '.');
  loadCards(); loadReport();
});

// ---------- Sign in (staff) ----------
$('signInLink').addEventListener('click', function (e) { e.preventDefault(); show('lock', true); $('login').focus(); });
$('lockClose').addEventListener('click', function () { show('lock', false); });
$('signOutLink').addEventListener('click', function (e) { e.preventDefault(); signOut(); });
$('loginForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var btn = $('loginBtn'), err = $('loginError');
  show('loginError', false);
  btn.disabled = true; btn.textContent = 'Signing in…';
  try {
    var res = await sb.auth.signInWithPassword({ email: loginToEmail($('login').value), password: $('password').value });
    if (res.error) {
      err.textContent = /invalid/i.test(res.error.message) ? 'That username and password don’t match.' : res.error.message;
      show('loginError', true);
      return;
    }
    $('password').value = '';
    location.reload();
  } catch (ex) {
    err.textContent = 'Could not reach the server. Check the wifi.';
    show('loginError', true);
  } finally {
    btn.disabled = false; btn.textContent = 'Sign in';
  }
});

// Back to the page after a while (the next guest's tap opens a new page anyway).
document.addEventListener('visibilitychange', function () {
  if (!document.hidden && code && card && card.found && !document.querySelector('dialog[open]')) loadCard();
});

start();
