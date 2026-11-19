/* The walk-on song picker (Sam, Nov 19 2026: "Before a show we should let comics
 * pick a walk up song and we can integrate that into the deck").
 *
 * Used by the comic's walk-on page (walkon/index.html) and the "Walk-on song?"
 * stop of the advance trip (advance/trip.html). The comic types a song or an
 * artist, taps the right one in the list (with its cover and a 30-second
 * listen, so it is the version they mean, not a cover band's) and can say where
 * in the song to start. The search is Apple's free public song search; it
 * needs no key and keeps nothing. On show night the office PC finds the same
 * song on Spotify by its title and artist (av/walkon/walkon.py).
 *
 *   WalkonSong.mount(element, song, onChange)
 *
 * song is {title, artist, start_sec, apple_id, artwork} or null; onChange gets
 * the new one (or null) every time it changes. Nothing is saved here: the page
 * that mounts it saves.
 */
(function () {
  var css = '' +
    '.ws-row{display:flex;gap:8px}.ws-row .input{flex:1}' +
    '.ws-list{margin-top:10px;display:grid;gap:8px}' +
    '.ws-hit{display:flex;align-items:center;gap:12px;width:100%;padding:8px 10px;border-radius:12px;border:1px solid var(--line,#4a4646);background:var(--card,#393636);color:inherit;text-align:left;cursor:pointer;font:inherit}' +
    '.ws-hit:hover{border-color:var(--gray,#918f90)}' +
    '.ws-hit img,.ws-card img,.ws-noart{width:52px;height:52px;border-radius:8px;flex:0 0 52px;object-fit:cover;background:var(--bg2,#232121)}' +
    '.ws-t{font-weight:700;line-height:1.2}.ws-a{color:var(--gray,#918f90);font-size:15px;line-height:1.25}' +
    '.ws-hit .ws-txt,.ws-card .ws-txt{flex:1;min-width:0}' +
    '.ws-card{display:flex;align-items:center;gap:12px;padding:12px;border-radius:12px;border:1px solid var(--slate-light,#a9c3d8);background:var(--slate-dark,#3b586e)}' +
    '.ws-card .ws-a{color:var(--muted,#d9d6d6)}' +
    '.ws-play{flex:0 0 44px;width:44px;height:44px;border-radius:50%;border:1px solid var(--line,#4a4646);background:var(--bg2,#232121);color:inherit;cursor:pointer;font-size:16px}' +
    '.ws-start{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}' +
    '.ws-start .input{width:110px;flex:0 0 110px;text-align:center}' +
    '.ws-note{color:var(--gray,#918f90);font-size:14px;margin-top:8px}' +
    '.ws-link{background:none;border:0;color:var(--slate-light,#a9c3d8);cursor:pointer;font:inherit;font-weight:600;padding:8px 0;min-height:44px;text-decoration:underline}';
  var style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  // "2:10" -> 130, "45" -> 45, "" -> 0, nonsense -> null
  function parseStart(t) {
    t = String(t || '').trim(); if (!t) return 0;
    var m = t.match(/^(\d{1,2}):([0-5]\d)$/); if (m) return +m[1] * 60 + +m[2];
    if (/^\d{1,3}$/.test(t)) return +t;
    return null;
  }
  function fmtStart(s) { s = Number(s) || 0; return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

  var n = 0, audio = null;
  function stopAudio() { if (audio) { audio.pause(); audio = null; } }
  // Apple's search answers JSONP, which works from any page.
  function search(term, done) {
    var name = 'wsCb' + (++n), s = document.createElement('script'), over = false;
    var timer = setTimeout(function () { over = true; cleanup(); done(null); }, 7000);
    function cleanup() { try { delete window[name]; } catch (e) { window[name] = undefined; } s.remove(); }
    window[name] = function (data) { if (over) return; clearTimeout(timer); cleanup(); done((data && data.results) || []); };
    s.onerror = function () { if (over) return; over = true; clearTimeout(timer); cleanup(); done(null); };
    s.src = 'https://itunes.apple.com/search?media=music&entity=song&limit=8&country=US&term=' + encodeURIComponent(term) + '&callback=' + name;
    document.head.appendChild(s);
  }

  function mount(el, song, onChange) {
    var hits = [], typed = '';
    function set(v) { song = v; stopAudio(); draw(); onChange(v); }
    function play(btn, url) {
      if (audio && audio.src === url) { stopAudio(); btn.textContent = '▶'; return; }
      stopAudio(); Array.prototype.forEach.call(el.querySelectorAll('.ws-play'), function (b) { b.textContent = '▶'; });
      audio = new Audio(url); audio.play().catch(function () {}); btn.textContent = '■';
      audio.onended = function () { btn.textContent = '▶'; };
    }
    function art(u) { return u ? '<img src="' + esc(u) + '" alt="">' : '<span class="ws-noart"></span>'; }

    function draw() {
      if (song && song.title) {
        el.innerHTML = '<div class="ws-card">' + art(song.artwork) +
          '<div class="ws-txt"><div class="ws-t">' + esc(song.title) + '</div><div class="ws-a">' + esc(song.artist || '') + '</div></div>' +
          (song.preview ? '<button type="button" class="ws-play" aria-label="Listen">▶</button>' : '') + '</div>' +
          '<div class="ws-start"><label for="wsStart" style="margin:0">Start at</label>' +
          '<input class="input" id="wsStart" inputmode="numeric" placeholder="0:00" value="' + (song.start_sec ? fmtStart(song.start_sec) : '') + '">' +
          '<span class="ws-note" style="margin:0">minutes:seconds</span></div>' +
          '<div class="ws-note" id="wsStartNote">Leave it blank to start at the top. Or skip to the part that hits.</div>' +
          '<button type="button" class="ws-link" id="wsChange">Pick a different song</button>';
        var p = el.querySelector('.ws-play'); if (p) p.onclick = function () { play(p, song.preview); };
        var st = el.querySelector('#wsStart');
        st.onchange = st.oninput = function () {
          var v = parseStart(st.value), note = el.querySelector('#wsStartNote');
          if (v == null || v > 900) { note.textContent = 'Try it like 1:30.'; return; }
          note.textContent = v ? 'Starts ' + fmtStart(v) + ' in.' : 'Starts at the top.';
          if (v !== (song.start_sec || 0)) { song = Object.assign({}, song, { start_sec: v }); onChange(song); }
        };
        el.querySelector('#wsChange').onclick = function () { set(null); setTimeout(function () { var i = el.querySelector('#wsQ'); if (i) i.focus(); }, 0); };
        return;
      }
      el.innerHTML = '<div class="ws-row"><input class="input" id="wsQ" type="search" enterkeyhint="search" autocomplete="off" placeholder="Song or artist" value="' + esc(typed) + '">' +
        '</div><div class="ws-list" id="wsList"></div><div class="ws-note" id="wsMsg"></div>';
      var q = el.querySelector('#wsQ'), list = el.querySelector('#wsList'), msg = el.querySelector('#wsMsg'), wait = null, ask = 0;
      function useTyped() {
        var t = typed.trim(); if (!t) return '';
        return '<button type="button" class="ws-link" id="wsAsIs">Not in the list? Use “' + esc(t) + '” as typed</button>';
      }
      function show() {
        list.innerHTML = hits.map(function (h, i) {
          return '<div style="display:flex;gap:8px;align-items:center"><button type="button" class="ws-hit" data-i="' + i + '">' + art(h.artworkUrl100) +
            '<span class="ws-txt"><span class="ws-t" style="display:block">' + esc(h.trackName) + '</span><span class="ws-a" style="display:block">' + esc(h.artistName) + '</span></span></button>' +
            (h.previewUrl ? '<button type="button" class="ws-play" data-p="' + i + '" aria-label="Listen to ' + esc(h.trackName) + '">▶</button>' : '') + '</div>';
        }).join('');
        Array.prototype.forEach.call(list.querySelectorAll('.ws-hit'), function (b) {
          b.onclick = function () {
            var h = hits[+b.getAttribute('data-i')];
            set({ title: h.trackName, artist: h.artistName, start_sec: 0, apple_id: String(h.trackId || ''), artwork: h.artworkUrl100 || '', preview: h.previewUrl || '' });
          };
        });
        Array.prototype.forEach.call(list.querySelectorAll('[data-p]'), function (b) { b.onclick = function () { play(b, hits[+b.getAttribute('data-p')].previewUrl); }; });
        var asIs = msg.querySelector('#wsAsIs');
        if (asIs) asIs.onclick = function () {
          var t = typed.trim(), parts = t.split(/\s+(?:-|–|—|by)\s+/i);
          set({ title: parts[0], artist: parts.slice(1).join(' '), start_sec: 0, apple_id: '', artwork: '' });
        };
      }
      q.oninput = function () {
        typed = q.value; clearTimeout(wait);
        if (typed.trim().length < 2) { hits = []; msg.innerHTML = ''; show(); return; }
        wait = setTimeout(function () {
          var mine = ++ask; msg.textContent = 'Looking…';
          search(typed.trim(), function (r) {
            if (mine !== ask) return;
            if (r === null) { hits = []; msg.innerHTML = 'The song search isn\'t answering. ' + useTyped(); }
            else { hits = r.filter(function (h) { return h.trackName; }); msg.innerHTML = (hits.length ? '' : 'Nothing by that name. ') + useTyped(); }
            show();
          });
        }, 350);
      };
      if (typed.trim().length >= 2) q.oninput();
    }
    draw();
    return { get: function () { return song; } };
  }

  // One line for people to read: "Thunderstruck - AC/DC (start 0:12)"
  function text(s) {
    if (!s || !s.title) return '';
    return s.title + (s.artist ? ' - ' + s.artist : '') + (s.start_sec ? ' (start ' + fmtStart(s.start_sec) + ')' : '');
  }

  window.WalkonSong = { mount: mount, text: text, parseStart: parseStart, fmtStart: fmtStart };
})();
