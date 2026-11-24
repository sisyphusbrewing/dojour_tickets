// Help: the staff helper, Tell Sam, and Sam's list. See the comment at the
// top of index.html. Everything here goes through database functions
// (help_*) or the Edge Function staff-help; nothing is kept on the phone.

var ROLE = null;
var chatTurns = [];          // [{q, a, needs, qid, sent}] this visit only
var tellKind = null;
var KIND = {
  idea:   { ico: '💡', label: 'Idea', prompt: 'Your idea or suggestion' },
  need:   { ico: '🙋', label: 'Needs Sam', prompt: 'What do you need from Sam?' },
  broken: { ico: '🔧', label: 'Something’s broken', prompt: 'What’s broken, and where?' },
  fyi:    { ico: '📌', label: 'Just so you know', prompt: 'What should Sam know?' },
  help:   { ico: '🤖', label: 'From the helper', prompt: '' }
};

function errText(res) {
  var e = res && res.error;
  return (e && (e.message || e.details)) || 'Something went wrong. Try again.';
}
async function fnError(error) {
  try { var b = await error.context.json(); if (b && b.error) return b.error; } catch (e) {}
  return 'The helper didn’t answer. Try again in a minute.';
}
function when(ts) {
  var d = new Date(ts);
  return d.toLocaleString('en-US', { timeZone: 'America/Chicago', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
function day(d) {
  return new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}
// Plain text with line breaks; web addresses become links.
function textHtml(s) {
  return escapeHtml(s || '')
    .replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)]|\bstaff\.sisyphusbrewing\.com\/[^\s<]*[^\s<.,;:!?)]|\bstaff\.sisyphusbrewing\.com\b)/g, function (m) {
      var href = /^https?:/.test(m) ? m : 'https://' + m;
      return '<a href="' + href + '" target="_blank" rel="noopener">' + m + '</a>';
    })
    .replace(/\n/g, '<br>');
}

// ---------- Tabs ----------
function showTab(name) {
  if (name === 'sam' && ROLE !== 'owner') name = 'ask';
  ['ask', 'tell', 'sam'].forEach(function (t) {
    $('view-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('#tabs a').forEach(function (a) { a.classList.toggle('on', a.dataset.tab === name); });
  if (name === 'tell') loadMine();
  if (name === 'sam') loadInbox();
}
document.querySelectorAll('#tabs a').forEach(function (a) {
  a.addEventListener('click', function (e) { e.preventDefault(); history.replaceState(null, '', '#' + a.dataset.tab); showTab(a.dataset.tab); });
});

// ---------- Ask ----------
function drawChat() {
  $('chat').innerHTML = chatTurns.map(function (t, i) {
    var a = t.pending
      ? '<div class="bubble a pending">Looking it up…</div>'
      : t.error
        ? '<div class="bubble a bad">' + escapeHtml(t.error) + '</div>'
        : '<div class="bubble a">' + textHtml(t.a) + '</div>' +
          (t.sent
            ? '<div class="sent">✓ Sent to Sam. You’ll see his answer under Tell Sam.</div>'
            : t.needs
              ? '<div class="escalate"><div>Want Sam to take a look?</div><button class="btn btn-primary btn-sm" data-send="' + i + '" type="button">Send this to Sam</button></div>'
              : '<button class="btn-link small" data-send="' + i + '" type="button">Didn’t help? Send it to Sam</button>');
    return '<div class="turn"><div class="bubble q">' + escapeHtml(t.q) + '</div>' + a + '</div>';
  }).join('');
  $('starters').classList.toggle('hidden', chatTurns.length > 0);
  $('newChat').classList.toggle('hidden', chatTurns.length === 0);
}

$('chat').addEventListener('click', async function (e) {
  var b = e.target.closest('[data-send]');
  if (!b) return;
  var t = chatTurns[+b.dataset.send];
  b.disabled = true;
  var body = 'I asked the helper: ' + t.q + '\n\nIt said: ' + t.a;
  var res = await sb.rpc('help_note_send', { p_kind: 'help', p_body: body.slice(0, 6000), p_need_by: null, p_anonymous: false, p_question_id: t.qid || null });
  if (res.error) { b.disabled = false; toast(errText(res), true); return; }
  t.sent = true;
  drawChat();
  toast('Sent to Sam');
});

async function ask(question) {
  question = (question || '').trim();
  if (!question) return;
  var turn = { q: question, pending: true };
  chatTurns.push(turn);
  drawChat();
  $('q').value = '';
  $('askBtn').disabled = true;
  var earlier = chatTurns.filter(function (t) { return t !== turn && t.a; }).slice(-6).map(function (t) { return { q: t.q, a: t.a }; });
  try {
    var res = await sb.functions.invoke('staff-help', { body: { question: question, earlier: earlier } });
    turn.pending = false;
    if (res.error) turn.error = await fnError(res.error);
    else { turn.a = res.data.answer; turn.needs = !!res.data.needs_sam; turn.qid = res.data.question_id; }
  } catch (err) {
    turn.pending = false;
    turn.error = 'Couldn’t reach the internet. Check the wifi and try again.';
  }
  $('askBtn').disabled = false;
  drawChat();
  var last = $('chat').lastElementChild;
  if (last) last.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
$('askForm').addEventListener('submit', function (e) { e.preventDefault(); ask($('q').value); });
$('q').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) { e.preventDefault(); ask($('q').value); }
});
$('starters').addEventListener('click', function (e) { var b = e.target.closest('.chip'); if (b) ask(b.textContent); });
$('newChat').addEventListener('click', function () { chatTurns = []; drawChat(); $('q').focus(); });

async function loadKnows() {
  var res = await sb.rpc('help_contents');
  var rows = res.data || [];
  $('knows').innerHTML = rows.map(function (r) { return '<li>' + escapeHtml(r.title) + '</li>'; }).join('');
  $('knowsFold').classList.toggle('hidden', !rows.length);
}

// ---------- Tell Sam ----------
function pickKind(k) {
  tellKind = k;
  document.querySelectorAll('#kinds .chip').forEach(function (c) {
    var on = c.dataset.kind === k;
    c.classList.toggle('on', on);
    c.setAttribute('aria-checked', on ? 'true' : 'false');
  });
  $('tellLabel').textContent = KIND[k].prompt;
  $('needByRow').classList.toggle('hidden', k !== 'need');
  var canAnon = k === 'idea' || k === 'fyi';
  $('anonRow').classList.toggle('hidden', !canAnon);
  if (!canAnon) $('anon').checked = false;
  $('anonNote').classList.toggle('hidden', !$('anon').checked);
}
$('kinds').addEventListener('click', function (e) { var c = e.target.closest('.chip'); if (c) pickKind(c.dataset.kind); });
$('anon').addEventListener('change', function () { $('anonNote').classList.toggle('hidden', !this.checked); });

$('tellForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var err = $('tellErr');
  err.classList.add('hidden');
  if (!tellKind) { err.textContent = 'Pick what it is first.'; err.classList.remove('hidden'); return; }
  var body = $('tellBody').value.trim();
  if (!body) { err.textContent = 'Write something first.'; err.classList.remove('hidden'); return; }
  var btn = $('tellBtn');
  btn.disabled = true; btn.textContent = 'Sending…';
  var res = await sb.rpc('help_note_send', {
    p_kind: tellKind, p_body: body,
    p_need_by: tellKind === 'need' && $('needBy').value ? $('needBy').value : null,
    p_anonymous: $('anon').checked, p_question_id: null
  });
  btn.disabled = false; btn.textContent = 'Send to Sam';
  if (res.error) { err.textContent = errText(res); err.classList.remove('hidden'); return; }
  $('tellBody').value = ''; $('needBy').value = ''; $('anon').checked = false;
  pickKind(tellKind);
  toast('Sent to Sam');
  loadMine();
});

function statusTag(n) {
  if (n.answer) return '<span class="tag ok">Sam answered</span>';
  if (n.status === 'done') return '<span class="tag ok">Done</span>';
  if (n.status === 'seen') return '<span class="tag">Sam saw it</span>';
  return '<span class="tag dim">Sent</span>';
}
async function loadMine() {
  var res = await sb.rpc('help_my_notes');
  var rows = res.data || [];
  $('mine').innerHTML = rows.length ? rows.map(function (n) {
    return '<div class="item">' +
      '<div class="item-top"><b>' + KIND[n.kind].ico + ' ' + escapeHtml(KIND[n.kind].label) + '</b>' + statusTag(n) + '</div>' +
      '<div class="quiet small">' + when(n.created_at) + (n.need_by ? ' · needed by ' + day(n.need_by) : '') + '</div>' +
      '<div class="body">' + textHtml(n.body) + '</div>' +
      (n.answer ? '<div class="answer"><div class="lbl">Sam</div>' + textHtml(n.answer) + '</div>' : '') +
    '</div>';
  }).join('') : '<div class="quiet">Nothing yet. Notes you send without your name don’t show here.</div>';
}

// ---------- Sam's list (owner) ----------
async function loadInbox() {
  var res = await sb.rpc('help_inbox');
  if (res.error) { $('inbox').innerHTML = '<div class="quiet">' + escapeHtml(errText(res)) + '</div>'; return; }
  var rows = res.data || [];
  var open = rows.filter(function (n) { return n.status !== 'done'; }).length;
  $('samBadge').textContent = open; $('samBadge').classList.toggle('hidden', !open);
  $('inbox').innerHTML = rows.length ? rows.map(function (n) {
    var k = KIND[n.kind] || KIND.fyi;
    return '<div class="item' + (n.status === 'done' ? ' done' : '') + '" data-id="' + n.id + '">' +
      '<div class="item-top"><b>' + k.ico + ' ' + escapeHtml(k.label) + '</b>' +
        (n.status === 'new' ? '<span class="tag new">New</span>' : n.status === 'seen' ? '<span class="tag">Seen</span>' : '<span class="tag ok">Done</span>') + '</div>' +
      '<div class="quiet small">' + escapeHtml(n.from_name || 'No name') + ' · ' + when(n.created_at) +
        (n.need_by ? ' · <b class="due">needed by ' + day(n.need_by) + '</b>' : '') + '</div>' +
      '<div class="body">' + textHtml(n.body) + '</div>' +
      (n.answer ? '<div class="answer"><div class="lbl">You answered</div>' + textHtml(n.answer) + '</div>' : '') +
      (n.status !== 'done'
        ? '<div class="reply">' +
            (n.from_name ? '<textarea class="input" rows="2" placeholder="Answer ' + escapeHtml(n.from_name.split(' ')[0]) + ' (optional)"></textarea>' : '') +
            '<div class="acts"><button class="btn btn-primary btn-sm" data-act="done" type="button">' + (n.from_name ? 'Send and mark done' : 'Mark done') + '</button>' +
            (n.status === 'new' ? '<button class="btn btn-sm" data-act="seen" type="button">Seen</button>' : '') + '</div></div>'
        : '') +
    '</div>';
  }).join('') : '<div class="quiet">Nothing sent to you yet.</div>';
  loadQuestions();
}
$('inbox').addEventListener('click', async function (e) {
  var b = e.target.closest('[data-act]');
  if (!b) return;
  var item = b.closest('.item');
  var ta = item.querySelector('textarea');
  b.disabled = true;
  var res = await sb.rpc('help_note_answer', {
    p_id: +item.dataset.id,
    p_answer: b.dataset.act === 'done' && ta ? ta.value : null,
    p_status: b.dataset.act
  });
  if (res.error) { b.disabled = false; toast(errText(res), true); return; }
  toast(b.dataset.act === 'done' ? 'Done' : 'Marked seen');
  loadInbox();
});
async function loadQuestions() {
  var res = await sb.rpc('help_recent_questions');
  var rows = res.data || [];
  $('questions').innerHTML = rows.length ? rows.map(function (q) {
    return '<div class="item">' +
      '<div class="quiet small">' + escapeHtml(q.from_name || '') + ' · ' + when(q.created_at) + (q.needs_sam ? ' · <span class="due">couldn’t solve it</span>' : '') + '</div>' +
      '<div class="body"><b>' + escapeHtml(q.question) + '</b></div>' +
      '<div class="body quiet">' + textHtml(q.answer) + '</div></div>';
  }).join('') : '<div class="quiet">No questions yet.</div>';
}

// ---------- Start ----------
setupSignIn(function (role) {
  ROLE = role;
  if (!roleAtLeast(role, 'staff')) {
    showNoAccess('staff', ['tabs']);
    return;
  }
  $('tabs').classList.remove('hidden');
  if (role === 'owner') { $('samTab').classList.remove('hidden'); loadInbox(); }
  var start = (location.hash || '').slice(1) || (/[?&]tell\b/.test(location.search) ? 'tell' : 'ask');
  showTab(['ask', 'tell', 'sam'].indexOf(start) >= 0 ? start : 'ask');
  loadKnows();
  drawChat();
});
