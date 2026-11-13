// "What's new" feed, shared by the staff page (/staff/) and the Manager page
// (/manager/). Unread updates sit on top until this login taps "Got it"; read
// ones fold under "Earlier updates". Managers can post, remove, and see who
// has read each one. (Sam, Nov 13 2026: Grace signs in on the Manager page,
// so the feed has to be there too, not only on /staff/.)
//
// Use: put <section id="newsSection"></section> on the page, load staff.js and
// this file, then call startNews(role, user) once the sign-in is confirmed.
(function () {
  var newsRole, newsUser;

  // Links in updates were written relative to /staff/ ("stream-deck.html",
  // "../exchange/"), so resolve them from there whichever page shows them.
  function linkHref(link) {
    try { return new URL(link, location.origin + '/staff/').href; } catch (e) { return link; }
  }
  function fmtWhen(ts) {
    return new Date(ts).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/Chicago' });
  }
  function isMgr() { return roleAtLeast(newsRole, 'manager'); }

  function noteHtml(n, read) {
    var link = n.link ? '<a class="btn btn-sm" href="' + escapeHtml(linkHref(n.link)) + '">Show me</a>' : '';
    var got = read ? '' : '<button class="btn btn-sm btn-primary" onclick="newsGotIt(' + n.id + ', this)">Got it</button>';
    var mgr = isMgr()
      ? '<span class="seen" id="seen' + n.id + '"></span><button class="btn-link" onclick="newsRemove(' + n.id + ')">Remove</button>' : '';
    return '<article class="note' + (read ? ' read' : '') + '" id="note' + n.id + '"><h3>' + escapeHtml(n.title) + '</h3>' +
      '<div class="when">' + fmtWhen(n.created_at) + (n.posted_by ? ' · ' + escapeHtml(n.posted_by) : '') + '</div>' +
      (n.body ? '<p>' + escapeHtml(n.body) + '</p>' : '') +
      '<div class="acts">' + got + link + mgr + '</div></article>';
  }

  async function loadNews() {
    var ups = await sb.from('staff_updates').select('*').order('created_at', { ascending: false }).limit(60);
    var reads = await sb.from('staff_update_reads').select('update_id').eq('user_id', newsUser.id);
    if (ups.error) { $('news').innerHTML = '<p class="all-caught">Could not load updates.</p>'; return; }
    var seen = {};
    (reads.data || []).forEach(function (r) { seen[r.update_id] = true; });
    var unread = ups.data.filter(function (n) { return !seen[n.id]; });
    var read = ups.data.filter(function (n) { return seen[n.id]; });
    $('news').innerHTML = unread.length ? unread.map(function (n) { return noteHtml(n, false); }).join('')
      : '<p class="all-caught">You’re all caught up.</p>';
    $('older').innerHTML = read.map(function (n) { return noteHtml(n, true); }).join('');
    $('olderToggle').classList.toggle('hidden', !read.length);
    $('olderToggle').textContent = 'Earlier updates (' + read.length + ')';
    if (isMgr()) ups.data.forEach(function (n) { loadSeen(n.id); });
  }
  async function loadSeen(id) {
    var r = await sb.rpc('staff_update_readers', { p_update: id });
    var el = $('seen' + id);
    if (!el || r.error) return;
    var names = (r.data || []).map(function (x) { return x.username; });
    el.textContent = names.length ? 'Seen by ' + names.join(', ') : 'Nobody has seen it yet';
  }
  window.newsGotIt = async function (id, btn) {
    btn.disabled = true;
    var r = await sb.from('staff_update_reads').insert({ update_id: id });
    if (r.error && r.error.code !== '23505') { btn.disabled = false; toast('Could not save that. Try again.', true); return; }
    loadNews();
  };
  window.newsRemove = async function (id) {
    if (!confirm('Take this update down for everyone?')) return;
    var r = await sb.from('staff_updates').delete().eq('id', id);
    if (r.error) { toast('Could not remove it.', true); return; }
    loadNews();
  };

  var SECTION_HTML =
    '<div class="band-row"><span class="band">What\'s new</span>' +
      '<span><button class="btn-link hidden" id="postToggle">+ Post an update</button></span></div>' +
    '<form id="postForm" class="card stack hidden">' +
      '<div class="field"><label for="upTitle">Headline</label><input class="input" id="upTitle" required maxlength="120" placeholder="New button on the Stream Deck"></div>' +
      '<div class="field"><label for="upBody">What changed and what to do</label><textarea class="input" id="upBody" required></textarea></div>' +
      '<div class="field"><label for="upLink">Link (optional)</label><input class="input" id="upLink" placeholder="stream-deck.html or https://…"></div>' +
      '<div class="field"><label for="upRole">Who sees it</label>' +
        '<select class="input" id="upRole"><option value="door">Everyone</option><option value="staff">Staff and up</option><option value="manager">Managers only</option></select></div>' +
      '<div class="acts" style="display:flex;gap:8px"><button class="btn btn-primary" type="submit" id="postBtn">Post it</button><button class="btn btn-ghost" type="button" id="postCancel">Cancel</button></div>' +
    '</form>' +
    '<div class="news" id="news"><p class="all-caught">Loading…</p></div>' +
    '<p style="margin:8px 0 0"><button class="btn-link hidden" id="olderToggle">Earlier updates</button></p>' +
    '<div class="news hidden" id="older"></div>';

  window.startNews = function (role, user) {
    newsRole = role; newsUser = user;
    $('newsSection').innerHTML = SECTION_HTML;
    $('olderToggle').addEventListener('click', function () { $('older').classList.toggle('hidden'); });
    if (isMgr()) {
      $('postToggle').classList.remove('hidden');
      $('postToggle').addEventListener('click', function () { $('postForm').classList.toggle('hidden'); });
      $('postCancel').addEventListener('click', function () { $('postForm').classList.add('hidden'); });
      $('postForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        $('postBtn').disabled = true;
        var r = await sb.from('staff_updates').insert({
          title: $('upTitle').value.trim(), body: $('upBody').value.trim(),
          link: $('upLink').value.trim() || null, min_role: $('upRole').value,
          posted_by: user.email.replace('@' + LOGIN_DOMAIN, '')
        });
        $('postBtn').disabled = false;
        if (r.error) { toast('Could not post it.', true); return; }
        $('postForm').reset(); $('postForm').classList.add('hidden');
        toast('Posted. Everyone sees it next time they sign in.');
        loadNews();
      });
    }
    loadNews();
  };
})();
