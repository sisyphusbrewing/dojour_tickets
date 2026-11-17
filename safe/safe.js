// The "Say something" page (Sam, Nov 17 2026: "Let's make some thing for the
// Green Room where people can tap or go to a website if they need to report
// unsafe behavior"). index.html says who it is for. This file: take the
// report, save it, and start the email to whoever the reporter picked.

var SUPABASE_URL = 'https://idsdwkubqnavkazlteis.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ';
// Always the public key, never somebody's login: a report must not carry the
// name of whoever happens to be signed in to the staff site on this phone.
var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY,
  { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });

var $ = function (id) { return document.getElementById(id); };
var VIA = (function () {
  var v = new URLSearchParams(location.search).get('via');
  return v === 'tag' || v === 'qr' ? v : null;
})();
var READERS = { both: 'Sam and Grace', sam: 'Sam', grace: 'Grace' };

// "Tonight" is the night it is in Minneapolis; until 5 in the morning it is
// still last night, the same as on the door list.
function tonight() { return new Date(Date.now() - 5 * 3600 * 1000).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' }); }

// ---------- Pick-one buttons ----------
var when = null, place = null;
function pickOne(box, btn) {
  box.querySelectorAll('.chip').forEach(function (c) { c.classList.toggle('on', c === btn && !btn.classList.contains('on')); });
  return box.querySelector('.chip.on');
}
$('whenChips').addEventListener('click', function (e) {
  var b = e.target.closest('.chip'); if (!b) return;
  var on = pickOne(this, b);
  when = on ? on.dataset.when : null;
  $('dayBox').classList.toggle('hidden', when !== 'other');
  if (when === 'other' && !$('f_day').value) $('f_day').focus();
});
$('placeChips').addEventListener('click', function (e) {
  var b = e.target.closest('.chip'); if (!b) return;
  var on = pickOne(this, b);
  place = on ? on.textContent.trim() : null;
});
$('f_day').max = tonight();

$('safeForm').addEventListener('input', function () { $('formError').classList.add('hidden'); });

// ---------- Sending ----------
function clearForm() {
  $('safeForm').reset();
  when = place = null;
  document.querySelectorAll('.chip.on').forEach(function (c) { c.classList.remove('on'); });
  $('dayBox').classList.add('hidden');
}

$('safeForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  var err = $('formError'), btn = $('sendBtn');
  var fail = function (m) { err.textContent = m; err.classList.remove('hidden'); };
  err.classList.add('hidden');

  var what = $('f_what').value.trim();
  if (what.length < 3) { $('f_what').focus(); return fail('Tell us a little about what happened.'); }
  var day = when === 'tonight' ? tonight() : (when === 'other' ? $('f_day').value : '');
  var to = (document.querySelector('input[name=to]:checked') || {}).value || 'both';
  var name = $('f_name').value.trim().replace(/\s+/g, ' ');
  var contact = $('f_contact').value.trim();

  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    var res = await sb.rpc('safety_report', { p_data: {
      what: what, happened_on: day, place: place, who: $('f_who').value.trim(),
      name: name, contact: contact, send_to: to, via: VIA } });
    if (res.error) throw new Error(res.error.message);

    // Start the email. The report is saved either way; if the email can't
    // be started, say so, so nobody assumes it was read.
    var sent = false;
    try {
      var r = await sb.functions.invoke('job-applied', { body: { id: res.data, kind: 'safety' } });
      sent = !r.error;
    } catch (ex) { sent = false; }

    $('doneLine').textContent = sent ? READERS[to] + (to === 'both' ? ' have' : ' has') + ' it now.' : 'It\'s saved.';
    $('doneBack').textContent = name || contact
      ? (contact ? 'Thank you for leaving a way to reach you. We will be in touch.' : 'You left your name but no way to reach you. Find us any time if you want to talk.')
      : 'You sent it without your name, so we can\'t write back. If you want to talk, find ' +
        (to === 'grace' ? 'Grace' : to === 'sam' ? 'Sam' : 'Sam or Grace') + ' any time.';
    $('doneWarn').classList.toggle('hidden', sent);
    clearForm();
    $('viewForm').classList.add('hidden'); $('viewDone').classList.remove('hidden');
    window.scrollTo(0, 0);
  } catch (ex) {
    var m = (ex && ex.message) || '';
    fail(/a lot of reports|tell us a little|too long/i.test(m) ? m
      : 'That didn\'t send. Check your connection and try again, or tell whoever is behind the bar.');
  } finally {
    btn.disabled = false; btn.textContent = 'Send it';
  }
});

$('anotherBtn').addEventListener('click', function () {
  $('viewDone').classList.add('hidden'); $('viewForm').classList.remove('hidden');
  window.scrollTo(0, 0);
});
