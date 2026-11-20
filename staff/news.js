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

  // ---------- How one update looks (Sam, Nov 19 2026: "We should also make
  // sure that the updates are visual and easy to understand as well -
  // comprehension is key") ----------
  // A small picture beside the headline says what it's about at a glance; a
  // screenshot shows the screen; numbered steps say what to do. The Clock's
  // "Before you clock in" box draws updates with the same code.
  var ICONS = {
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    door: '<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17M3 21h18"/><circle cx="15" cy="12" r="1"/>',
    deck: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h2M11 9h2M15 9h2M7 13h2M11 13h2M15 13h2"/>',
    phone: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
    safe: '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14c2.6 0 4.5 1.8 4.5 4.5"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
    money: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.01M18 12h.01"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>'
  };
  window.UPDATE_ICONS = ICONS;
  function iconSvg(name) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[name] || ICONS.star) + '</svg>';
  }
  window.updateIconSvg = iconSvg;
  // The inside of one update: picture beside the headline, the screenshot,
  // one short line, then the steps. opts.when is the date line (or '').
  // Lines in the text that start with "1." "2." ... are steps too, so an
  // update typed anywhere as a numbered list gets the numbered circles.
  function splitSteps(n) {
    var lines = String(n.body || '').split('\n'), text = [], steps = [];
    lines.forEach(function (l) {
      var m = l.match(/^\s*\d+[.)]\s+(.*)$/);
      if (m) steps.push(m[1]); else text.push(l);
    });
    return { body: text.join('\n').trim(), steps: steps.filter(function (x) { return x && String(x).trim(); }) };
  }
  // With no picture picked, the page the update points to picks one.
  function guessIcon(n) {
    var t = (n.link || '') + ' ' + n.title;
    var rules = [[/clock|tips/i, 'clock'], [/door/i, 'door'], [/schedul|shift/i, 'calendar'], [/stream.?deck|deck/i, 'deck'], [/safe|unsafe/i, 'safe'],
      [/suppl|order/i, 'box'], [/mic/i, 'mic'], [/pay|venmo|money/i, 'money'], [/sign.?in|phone|log.?in/i, 'phone'], [/group|people|party/i, 'people']];
    for (var i = 0; i < rules.length; i++) if (rules[i][0].test(t)) return rules[i][1];
    return 'star';
  }
  window.updateHtml = function (n, opts) {
    opts = opts || {};
    var sp = splitSteps(n), steps = sp.steps;
    n = Object.assign({}, n, { body: sp.body, icon: n.icon || guessIcon(n) });
    return '<div class="up-head"><span class="up-ico">' + iconSvg(n.icon) + '</span>' +
        '<div class="up-titles"><h3>' + escapeHtml(n.title) + '</h3>' +
        (opts.when ? '<div class="when">' + escapeHtml(opts.when) + '</div>' : '') + '</div></div>' +
      (n.picture ? '<a class="up-pic" target="_blank" rel="noopener"><img alt="Picture for this update" data-pic="' + escapeHtml(n.picture) + '"></a>' : '') +
      (n.body ? '<p class="up-body">' + escapeHtml(n.body) + '</p>' : '') +
      (steps.length ? '<ol class="up-steps">' + steps.map(function (x, i) {
        return '<li><span class="up-num">' + (i + 1) + '</span><span>' + escapeHtml(x) + '</span></li>';
      }).join('') + '</ol>' : '');
  };
  // A picture is either a file on this site ("/staff/updates/clock-tap.png",
  // screenshots with made-up names only, since this repo is public) or a
  // photo a manager added, kept in a private storage folder: for those, ask
  // for short-lived links all at once. A picture that can't load just goes away.
  function onSite(p) { return /^(\/|https:)/.test(p); }
  window.fillUpdatePictures = async function (el) {
    var imgs = Array.prototype.slice.call((el || document).querySelectorAll('img[data-pic]:not([src])'));
    if (!imgs.length) return;
    var paths = imgs.map(function (i) { return i.getAttribute('data-pic'); }).filter(function (p) { return !onSite(p); });
    var urls = {};
    imgs.forEach(function (i) { var p = i.getAttribute('data-pic'); if (onSite(p)) urls[p] = p; });
    if (paths.length) try {
      var r = await sb.storage.from('staff-updates').createSignedUrls(paths.filter(function (p, i) { return paths.indexOf(p) === i; }), 3600);
      (r.data || []).forEach(function (x) { if (x.signedUrl) urls[x.path] = x.signedUrl; });
    } catch (e) {}
    imgs.forEach(function (img) {
      var u = urls[img.getAttribute('data-pic')], a = img.parentNode;
      if (!u) { a.parentNode && a.parentNode.removeChild(a); return; }
      img.onerror = function () { a.parentNode && a.parentNode.removeChild(a); };
      img.src = u; a.href = u;
    });
  };

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
    return '<article class="note up' + (read ? ' read' : '') + '" id="note' + n.id + '">' +
      updateHtml(n, { when: fmtWhen(n.created_at) + (n.posted_by ? ' · ' + n.posted_by : '') }) +
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
    // Lets a page lay out "nothing new" differently (the staff home page moves
    // the whole section down the page once everything is read).
    $('news').classList.toggle('caught', !unread.length);
    $('newsSection').classList.toggle('caught', !unread.length);
    $('older').innerHTML = read.map(function (n) { return noteHtml(n, true); }).join('');
    $('olderToggle').classList.toggle('hidden', !read.length);
    $('olderToggle').textContent = 'Earlier updates (' + read.length + ')';
    fillUpdatePictures($('news'));
    $('olderToggle').onclick = function () { fillUpdatePictures($('older')); };
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
      '<div class="field"><label>Pick a picture for it</label><div class="up-icons" id="upIcons"></div></div>' +
      '<div class="field"><label for="upBody">What changed, in one short line</label><textarea class="input" id="upBody" required rows="2" placeholder="The Stream Deck has a new ALARM key."></textarea></div>' +
      '<div class="field"><label for="upSteps">What to do, one step per line (up to 6)</label><textarea class="input" id="upSteps" rows="4" placeholder="Tap ALARM on the BAR page\nPick ARM AWAY when you close"></textarea></div>' +
      '<div class="field"><label for="upPic">Screenshot or photo (optional)</label><input class="input" id="upPic" type="file" accept="image/*"></div>' +
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
      var pickedIcon = 'star';
      $('upIcons').innerHTML = Object.keys(ICONS).map(function (k) {
        return '<button type="button" class="up-ico' + (k === pickedIcon ? ' on' : '') + '" data-icon="' + k + '" aria-label="' + k + '">' + iconSvg(k) + '</button>';
      }).join('');
      $('upIcons').addEventListener('click', function (e) {
        var b = e.target.closest('[data-icon]');
        if (!b) return;
        pickedIcon = b.getAttribute('data-icon');
        Array.prototype.forEach.call($('upIcons').children, function (x) { x.classList.toggle('on', x === b); });
      });
      $('postForm').addEventListener('submit', async function (e) {
        e.preventDefault();
        var steps = $('upSteps').value.split('\n').map(function (x) { return x.replace(/^\s*\d+[.)]\s*/, '').trim(); }).filter(Boolean);
        if (steps.length > 6) { toast('Up to 6 steps, please. Keep it short.', true); return; }
        $('postBtn').disabled = true;
        var picture = null, file = $('upPic').files[0];
        if (file) {
          var ext = (file.name.split('.').pop() || 'jpg').toLowerCase().replace(/[^a-z0-9]/g, '') || 'jpg';
          picture = Date.now() + '-' + Math.random().toString(36).slice(2, 8) + '.' + ext;
          var up = await sb.storage.from('staff-updates').upload(picture, file, { contentType: file.type || undefined });
          if (up.error) { $('postBtn').disabled = false; toast('Could not add the picture: ' + up.error.message, true); return; }
        }
        // The steps go in the text as a numbered list, which every version
        // of the page reads.
        var row = {
          title: $('upTitle').value.trim(),
          body: $('upBody').value.trim() + (steps.length ? '\n' + steps.map(function (x, i) { return (i + 1) + '. ' + x; }).join('\n') : ''),
          icon: pickedIcon, picture: picture,
          link: $('upLink').value.trim() || null, min_role: $('upRole').value,
          posted_by: user.email.replace('@' + LOGIN_DOMAIN, '')
        };
        var r = await sb.from('staff_updates').insert(row);
        // A database without the picture columns yet still takes the words.
        if (r.error && /icon|picture|column/i.test(r.error.message || '') && !picture) {
          delete row.icon; delete row.picture;
          r = await sb.from('staff_updates').insert(row);
        }
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
