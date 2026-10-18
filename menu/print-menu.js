/* Printable taproom menu (one US Letter page), live from the GoTab feed behind the Drink Menu page and TV board.
   The Shopify page /pages/print-menu is just:
     <div id="pm-root"></div><script src="https://sisyphusbrewing.github.io/dojour_tickets/menu/print-menu.js"></script>
   so changes here go live when merged. Standalone copy for testing: menu/print.html. */
(function () {
  var style = document.createElement('style');
  style.textContent = `@import url("https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@600;700&family=Assistant:wght@500;600;700&family=Special+Elite&display=swap");
  /* Printable taproom menu: one US Letter page, live from the same GoTab feed as the Drink Menu page and TV board.
     White paper, charcoal ink, slate-blue tilted bands from the logo. Open the page, press Print. */
  :root { --ink: #393636; --soft: #5f5b5c; --rule: #cfcccc; --slate: #4a6c86; --k: 1;
          --display: 'Josefin Sans', 'Century Gothic', Futura, sans-serif; --body: 'Assistant', system-ui, sans-serif; }
  .shopify-section-group-header-group, .shopify-section-group-footer-group, #shopify-section-announcement-bar,
  .announcement-bar-section, .skip-to-content-link, .main-page-title, .page-width--narrow > h1 { display: none !important; }
  .scroll-trigger { transform: none !important; opacity: 1 !important; animation: none !important; }
  body { background: #e9e7e7 !important; }

  .pm-bar { max-width: 8.5in; margin: 24px auto 14px; display: flex; gap: 12px; align-items: center; justify-content: space-between; font-family: var(--body); }
  .pm-bar p { margin: 0; font-size: 15px; color: #393636 !important; }
  .pm-bar button { font: 700 15px var(--body); letter-spacing: .1em; text-transform: uppercase; background: #4a6c86; color: #fff !important;
                   border: 0; border-radius: 6px; padding: 12px 26px; cursor: pointer; }

  #pm { width: 8.5in; height: 11in; margin: 0 auto 40px; box-sizing: border-box; padding: .5in .55in .45in; background: #fff; color: var(--ink);
        position: relative; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 6px 30px rgba(0,0,0,.18);
        font-family: var(--body); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  #pm::before { content: ""; position: absolute; inset: .22in; border: 3px solid var(--ink); border-radius: 6px; pointer-events: none; }
  #pm::after { content: ""; position: absolute; inset: .3in; border: 1px solid var(--ink); opacity: .35; border-radius: 3px; pointer-events: none; }
  #pm * { box-sizing: border-box; }

  #pm header { display: grid; grid-template-columns: auto 1fr; gap: 0 .28in; align-items: center; padding: 0 .05in .08in; }
  #pm header img { width: 1.3in; height: auto; display: block; }
  #pm h1 { margin: 0; font: 700 calc(46pt * var(--k)) / .95 var(--display) !important; letter-spacing: .1em; text-transform: uppercase; color: var(--ink) !important; }
  #pm .motto { margin: 8px 0 0; padding: 1px 0 1px 12px; border-left: 3px solid var(--slate); }
  #pm .motto q { display: block; quotes: none; font: 400 calc(15pt * var(--k)) / 1.15 'Special Elite', 'Courier New', monospace !important; color: var(--ink) !important; }
  #pm .motto cite { display: block; margin-top: 4px; font: 700 calc(7.5pt * var(--k)) var(--body) !important; letter-spacing: .16em; text-transform: uppercase; color: var(--soft) !important; }
  #pm .motto cite span { margin: 0 .5em; color: inherit !important; }

  #pm h2 { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin: calc(14pt * var(--k)) 3px calc(12pt * var(--k));
           background: var(--slate); padding: 6px 14px 3px; transform: rotate(-1.5deg);
           font: 700 calc(17pt * var(--k)) / 1.1 var(--display) !important; letter-spacing: .14em; text-transform: uppercase; color: #fff !important;
           box-shadow: 0 -4px 0 -1px #fff, 0 -6px 0 -1px var(--slate), 0 4px 0 -1px #fff, 0 6px 0 -1px var(--slate); }
  #pm h2 span { font: 700 calc(11pt * var(--k)) var(--body) !important; letter-spacing: .04em; text-transform: none; white-space: nowrap; color: #fff !important; }

  #pm .beer { display: grid; grid-template-columns: 1fr 1fr; gap: 0 .35in; }
  #pm .it { break-inside: avoid; padding: calc(5pt * var(--k)) 0; border-bottom: 1px solid var(--rule); }
  #pm .row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  #pm .nm { font: 700 calc(13pt * var(--k)) / 1.1 var(--display) !important; letter-spacing: .02em; text-transform: uppercase; color: var(--ink) !important; }
  #pm .fig { font: 700 calc(9.5pt * var(--k)) var(--body) !important; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--slate) !important; }
  #pm .st { display: block; margin-top: 1px; font: 700 calc(9.5pt * var(--k)) / 1.2 var(--body) !important; color: var(--soft) !important; }
  #pm .bl { display: block; margin-top: 2px; font: italic 500 calc(9pt * var(--k)) / 1.3 var(--body) !important; color: var(--soft) !important; }

  #pm .more { display: grid; grid-template-columns: repeat(var(--n, 2), 1fr); gap: 0 .35in; }
  #pm .more h2 { font-size: calc(12pt * var(--k)) !important; letter-spacing: .05em; gap: 8px; padding-left: 10px; padding-right: 10px; }
  #pm .more h2 span { font-size: calc(10pt * var(--k)) !important; }
  #pm .more .nm { font-size: calc(11pt * var(--k)) !important; }
  #pm .msg { margin: 1in 0; text-align: center; font: 700 20pt var(--display) !important; color: var(--soft) !important; }
  #pm footer { margin-top: auto; padding-top: 10px; display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
               font: 600 calc(9pt * var(--k)) var(--body) !important; color: var(--soft) !important; background: transparent !important; }
  #pm footer b { font-family: var(--display) !important; letter-spacing: .08em; color: var(--slate) !important; }
  #pm footer span { color: inherit !important; }

  @page { size: letter; margin: 0; }
  @media print {
    html, body { background: #fff !important; margin: 0 !important; padding: 0 !important; }
    body * { visibility: hidden !important; }
    #pm, #pm * { visibility: visible !important; }
    #pm { position: absolute; left: 0; top: 0; margin: 0; box-shadow: none; }
    .pm-bar { display: none !important; }
  }
  @media screen and (max-width: 860px) { #pm { zoom: .45; } .pm-bar { padding: 0 16px; } }
`;
  document.head.appendChild(style);
  var root = document.getElementById('pm-root') || document.body.appendChild(document.createElement('div'));
  root.innerHTML = `
<div class="pm-bar"><p>Today's taps, straight from GoTab. One Letter page.</p><button type="button" onclick="window.print()">Print menu</button></div>
<div id="pm">
  <header>
    <img src="https://cdn.shopify.com/s/files/1/0310/0669/files/sisyphus-badge-full-color.png?v=1792206826&width=400" alt="Sisyphus">
    <div>
      <h1>On Tap</h1>
      <div class="motto"><q lang="fr">«&nbsp;Il faut imaginer Sisyphe heureux.&nbsp;»</q><cite>One must imagine Sisyphus happy <span>·</span> Albert&nbsp;Camus</cite></div>
    </div>
  </header>
  <main id="pm-menu"><div class="msg">Loading today's taps…</div></main>
  <footer><b>SISYPHUSBREWING.COM</b><span>House seltzers are gluten-free · Outside food welcome</span><span id="pm-date"></span></footer>
</div>`;

  // Same feed and style map as the Drink Menu page and TV board. Add new beers to SB_STYLES there and here.
  var ENDPOINT = 'https://sisyphusmenu.stharriman.workers.dev/';
  var SB_STYLES = {
    samms: 'Light American Lager',
    kentuckycommon: 'Historical Amber Lager',
    cometchameleon: 'Hazy IPA',
    sisyfest: 'Oktoberfest',
    thefirstbeerwenamed: 'American IPA'
  };
  // Pour sizes for beers whose GoTab description has no "16oz" line: 16 oz, or 13 oz at 6.5% ABV and up.
  // List a beer here only when its pour breaks that rule, e.g. somebeer: '10 oz'.
  var SB_SIZES = {
    neverlastinggobstopper: '13 oz'
  };
  // ?blurbs=0 drops the one-line beer descriptions for a tighter menu.
  var BLURBS = !/[?&]blurbs=0/.test(location.search);
  var box = document.getElementById('pm-menu'), sheet = document.getElementById('pm');

  function esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function money(p) { var n = parseFloat(p); return isNaN(n) ? '' : '$' + (n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)); }

  // Description lines look like "16oz Lager" / "4.7% ABV 15 IBU" / "Blurb sentence. 5% ABV".
  // Unlike the TV parser, ABV/IBU are lifted out of a line and the rest kept, so long blurbs survive.
  function parse(item) {
    var o = { name: item.name || '', price: money(item.price), abv: '', size: '', style: '', blurb: '' }, rest = [];
    String(item.description || '').split('\n').forEach(function (raw) {
      var l = raw.trim();
      var abv = l.match(/(\d+(?:\.\d+)?)\s*%\s*ABV/i);
      if (abv) o.abv = abv[1] + '%';
      l = l.replace(/(\d+(?:\.\d+)?)\s*%\s*ABV/ig, '').replace(/\d+\s*IBU/ig, '').replace(/^[\s\-–·,]+|[\s\-–·,]+$/g, '').trim();
      var size = l.match(/^(\d+(?:\.\d+)?)\s*oz\b\s*(.*)$/i);
      if (size) { o.size = size[1] + ' oz'; l = size[2].trim(); }
      if (!l) return;
      if (!o.style && l.length <= 40 && !/[.!?]$/.test(l)) o.style = l; else rest.push(l);
    });
    var key = o.name.toLowerCase().replace(/[^a-z0-9]/g, '');
    for (var k in SB_STYLES) if (key.indexOf(k) === 0) { o.style = SB_STYLES[k]; break; }
    if (!o.size && o.abv) {
      for (var z in SB_SIZES) if (key.indexOf(z) === 0) o.size = SB_SIZES[z];
      if (!o.size) o.size = parseFloat(o.abv) >= 6.5 ? '13 oz' : '16 oz';
    }
    // First sentence of the blurb, capped at a word so every beer stays about one line.
    var b = rest.join(' ').replace(/\s+/g, ' ').trim(), m = b.match(/^.+?[.!?](?=\s|$)/);
    b = m ? m[0] : b;
    if (b.length > 120) b = b.slice(0, 118).replace(/\s+\S*$/, '') + '…';
    o.blurb = b;
    return o;
  }

  function sections(data) {
    return (data.sections || []).filter(function (s) { return s.items && s.items.length; }).map(function (s) {
      var items = s.items.map(parse);
      var same = function (k) { return items.every(function (i) { return i[k] && i[k] === items[0][k]; }) ? items[0][k] : ''; };
      var price = same('price'), size = same('size');
      return { title: s.category, isBeer: /beer|tap|draft/i.test(s.category) && !/n\/?a|non/i.test(s.category),
               price: price, size: size, items: items, note: [price, size].filter(Boolean).join(' · ') };
    });
  }

  function head(s) { return '<h2>' + esc(s.title) + (s.note ? '<span>' + esc(s.note) + '</span>' : '') + '</h2>'; }
  function row(name, fig, sub, blurb) {
    return '<div class="it"><div class="row"><span class="nm">' + esc(name) + '</span>' + (fig ? '<span class="fig">' + esc(fig) + '</span>' : '') + '</div>' +
      (sub ? '<span class="st">' + esc(sub) + '</span>' : '') + (blurb ? '<span class="bl">' + esc(blurb) + '</span>' : '') + '</div>';
  }

  function render(data) {
    var secs = sections(data), beer = secs.filter(function (s) { return s.isBeer; }), more = secs.filter(function (s) { return !s.isBeer; });
    if (!secs.length) throw new Error('No menu sections');
    var html = beer.map(function (s) {
      var cells = s.items.map(function (i) {
        var fig = [s.size ? '' : i.size, i.abv ? i.abv + ' ABV' : '', s.price ? '' : i.price].filter(Boolean).join(' · ');
        return row(i.name, fig, i.style, BLURBS ? i.blurb : '');
      });
      var half = Math.ceil(cells.length / 2);
      return head(s) + '<div class="beer"><div>' + cells.slice(0, half).join('') + '</div><div>' + cells.slice(half).join('') + '</div></div>';
    }).join('');
    // Everything else in two columns along the bottom: seltzers and the like on the left, N/A drinks and snacks on the right.
    var cols = ['', ''];
    more.forEach(function (s) {
      cols[/n\/?a\b|non[- ]?alc|snack|food/i.test(s.title) ? 1 : 0] += head(s) +
        s.items.map(function (i) { return row(i.name, s.price ? '' : i.price, s.size ? '' : i.size, ''); }).join('');
    });
    cols = cols.filter(Boolean);
    html += '<div class="more" style="--n:' + Math.max(cols.length, 1) + '">' + cols.map(function (c) { return '<section>' + c + '</section>'; }).join('') + '</div>';
    box.innerHTML = html;
    var d = new Date();
    document.getElementById('pm-date').textContent = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    fit();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
    setTimeout(fit, 1200);
    sheet.setAttribute('data-ready', '1');
  }

  // One type scale for the whole sheet: start large so a short list fills the page, step down until it fits on one Letter page.
  function fit() {
    var r = document.documentElement.style, k = 1.35;
    r.setProperty('--k', k);
    while (sheet.scrollHeight > sheet.clientHeight + 1 && k > 0.5) { k = Math.round((k - 0.02) * 100) / 100; r.setProperty('--k', k); }
  }
  window.addEventListener('beforeprint', fit);

  fetch(ENDPOINT + '?t=' + Date.now())
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(render)
    .catch(function () { box.innerHTML = '<div class="msg">Couldn\'t load the menu. Refresh the page.</div>'; });
})();
