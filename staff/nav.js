// The thin bar across the top of every staff tool: "Staff home" on the left
// and "All tools" on the right, so nobody has to use the back button or
// remember a web address to get from one tool to another.
//
// Use: add ONE line to a staff page, anywhere in it:
//   <script src="/staff/nav.js"></script>
// The list of tools comes from staff/tools.js (this file loads it), narrowed
// to what the signed-in login can open. It adds nothing when the page is
// shown inside the website (the Shopify pages embed a few of these).
(function () {
  if (window.top !== window.self) return;                 // embedded in sisyphusbrewing.com: no staff bar
  var here = document.currentScript ? document.currentScript.src : '/staff/nav.js';
  var base = here.replace(/staff\/nav\.js.*$/, '');       // the top of the site, wherever it is served from

  var css =
    '.snav{background:#211f1f;border-bottom:1px solid #4a4646;font-family:Assistant,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.2;position:relative;z-index:40;padding-top:env(safe-area-inset-top)}' +
    '.snav *{box-sizing:border-box}' +
    '.snav-in{max-width:var(--snav-w,1120px);margin:0 auto;padding:0 16px;display:flex;justify-content:space-between;align-items:center;min-height:40px;gap:12px}' +
    '.snav a.snav-home,.snav button.snav-all{color:#a9c3d8;font-weight:700;text-decoration:none;background:none;border:0;padding:10px 0;cursor:pointer;font:inherit;font-weight:700;white-space:nowrap}' +
    '.snav a.snav-home:hover,.snav button.snav-all:hover{color:#fff}' +
    '.snav-panel{position:absolute;right:max(8px,calc((100% - var(--snav-w,1120px))/2 + 8px));top:100%;width:min(340px,calc(100vw - 16px));max-height:min(74vh,560px);overflow:auto;background:#393636;border:1px solid #4a4646;border-radius:12px;box-shadow:0 14px 36px rgba(0,0,0,.5);padding:10px;color:#fff}' +
    '.snav-panel[hidden]{display:none}' +
    '.snav-find{width:100%;min-height:42px;border-radius:9px;border:1px solid #4a4646;background:#2b2929;color:#fff;padding:8px 12px;font:inherit;font-size:16px;outline:none}' +
    '.snav-find:focus{border-color:#a9c3d8}' +
    '.snav-grp{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#a9c3d8;margin:12px 4px 4px}' +
    '.snav-tool{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:8px;color:#fff;text-decoration:none;font-weight:600;font-size:15px}' +
    '.snav-tool:hover,.snav-tool:focus-visible{background:#4a4646;outline:none}' +
    '.snav-tool.here{background:#4a6c86}' +
    '.snav-tool i{font-style:normal;width:22px;text-align:center}' +
    '.snav-none{color:#918f90;margin:10px 4px 4px}' +
    '@media print{.snav{display:none}}';

  function build() {
    if (document.querySelector('.snav') || !document.body) return;
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    var nav = document.createElement('nav');
    nav.className = 'snav';
    nav.setAttribute('aria-label', 'Staff tools');
    nav.innerHTML = '<div class="snav-in"><a class="snav-home" href="' + base + 'staff/">‹ Staff home</a>' +
      '<button class="snav-all" type="button" aria-expanded="false">All tools ▾</button></div>' +
      '<div class="snav-panel" hidden><input class="snav-find" type="search" placeholder="Find a tool" aria-label="Find a tool" autocomplete="off">' +
      '<div class="snav-list"></div></div>';
    document.body.insertBefore(nav, document.body.firstChild);
    // Line the bar up with the page under it, however wide that page is.
    var wrap = document.querySelector('.wrap');
    var wide = wrap ? parseInt(getComputedStyle(wrap).maxWidth, 10) : 0;
    if (wide) nav.style.setProperty('--snav-w', wide + 'px');

    var btn = nav.querySelector('.snav-all'), panel = nav.querySelector('.snav-panel');
    var find = nav.querySelector('.snav-find'), list = nav.querySelector('.snav-list');
    // What this login can open: the staff home page remembers it on each
    // device; a page that has the database connection loaded asks afresh.
    var role = 'door', voice = false;
    try { role = localStorage.getItem('staffRoleSeen') || 'door'; voice = !!localStorage.getItem('staffVoiceSeen'); } catch (e) {}

    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
    function href(t) { return t.href.charAt(0) === '/' ? base + t.href.slice(1) : t.href; }
    function isHere(t) {
      if (t.href.charAt(0) !== '/') return false;
      var a = new URL(href(t), location.href).pathname.replace(/index\.html$/, '');
      return a === location.pathname.replace(/index\.html$/, '');
    }
    function draw() {
      var q = find.value.trim().toLowerCase();
      var tools = staffToolsFor(role, voice).filter(function (t) {
        var hay = (t.title + ' ' + t.desc + ' ' + (t.find || '')).toLowerCase();
        return !q || q.split(/\s+/).every(function (w) { return hay.indexOf(w) !== -1; });
      });
      list.innerHTML = STAFF_GROUPS.map(function (g) {
        var mine = tools.filter(function (t) { return t.group === g.id; });
        return mine.length ? '<div class="snav-grp">' + esc(g.title) + '</div>' + mine.map(function (t) {
          return '<a class="snav-tool' + (isHere(t) ? ' here' : '') + '" data-id="' + t.id + '" href="' + esc(href(t)) + '"' +
            (t.out ? ' target="_blank" rel="noopener"' : '') + '><i>' + t.ico + '</i>' + esc(t.title) + '</a>';
        }).join('') : '';
      }).join('') || '<p class="snav-none">Nothing by that name.</p>';
    }
    function open(yes) {
      panel.hidden = !yes;
      btn.setAttribute('aria-expanded', yes ? 'true' : 'false');
      if (yes) { find.value = ''; draw(); if (window.matchMedia('(min-width: 700px)').matches) find.focus(); }
    }
    btn.addEventListener('click', function (e) { e.stopPropagation(); open(panel.hidden); });
    find.addEventListener('input', draw);
    find.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { var first = list.querySelector('.snav-tool'); if (first) first.click(); }
    });
    list.addEventListener('click', function (e) {
      var a = e.target.closest('.snav-tool');
      if (a && window.staffToolUsed) staffToolUsed(a.dataset.id);
    });
    document.addEventListener('click', function (e) { if (!nav.contains(e.target)) open(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') open(false); });

    var db = window.sb || window.supabaseClient;
    if (db && db.rpc) {
      Promise.resolve(db.rpc('my_role')).then(function (r) {
        if (r && r.data) { role = r.data; try { localStorage.setItem('staffRoleSeen', role); } catch (e) {} }
      }).catch(function () {});
    }
  }

  function start() {
    if (window.STAFF_TOOLS) { build(); return; }
    var s = document.createElement('script');
    s.src = base + 'staff/tools.js';
    s.onload = build;
    document.head.appendChild(s);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
