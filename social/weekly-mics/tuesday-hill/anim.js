// The moving Tuesday story: he pushes the boulder up to the mic, it rolls back
// down with him, "FOREVER." lands, and he starts again. 10 seconds, 30 a second.
// Usage: node anim.js <theme> <outdir> [probe] [sticker] [variant=ad-feed]
//   variant=<name> uses one of story.js's VARIANTS (size and words), e.g. the ad versions.
const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const S = require('./story');
const theme = process.argv[2] || 'slate', out = process.argv[3] || 'frames', probe = process.argv[4] === 'probe';
// 'sticker' as the last word leaves the web address off, so Instagram's link sticker can go in its place.
const sticker = process.argv.includes('sticker');
const vname = (process.argv.find(a => a.startsWith('variant=')) || '').slice(8);
const V = vname ? S.VARIANTS[vname] : { theme, w: 1080, h: 1920, spots: true, sticker };
const W = V.w, H = V.h, FPS = 30, DUR = 10, K = S.scaleFor(H);
const TOP = 752, START = -175, D = TOP - START;         // where the boulder touches the hill, in px across
const CYCLE = 16.5 / 0.62 * K * Math.cos(S.A);        // px across per full stride
const up = u => u * (1.3 - 0.3 * u);                      // slows a little near the top
const FIRST = 330;                                         // the video opens with him already in the picture
const T1 = 1.9, T2 = 2.8, T3 = 4.3, T4 = 4.8, T5 = 8.6;
function state(t) {
  let x; const forever = t >= T2 + 0.3;
  if (t < T1) x = FIRST + (TOP - FIRST) * up(t / T1);
  else if (t < T2) x = TOP + Math.sin((t - T1) * 44) * 1.8 * (1 - (t - T1) / (T2 - T1));   // straining at the top
  else if (t < T3) x = TOP - D * 1.06 * Math.pow((t - T2) / (T3 - T2), 2.1);               // back down, faster and faster
  else if (t < T4) x = START - D * 0.06;
  else if (t < T5) x = START + D * up((t - T4) / (T5 - T4));
  else x = TOP;
  return { x0: x, rot: (x - TOP) / Math.cos(S.A) / (12.5 * K) * 180 / Math.PI, gait: { phase: 0.57 + (x - TOP) / CYCLE }, forever };
}
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 1, viewport: { width: W, height: H } });
  await p.setContent(`<!doctype html><html><head><meta charset="utf-8">${S.FONTS}<style>*{margin:0}body{width:${W}px;height:${H}px;overflow:hidden}</style></head><body><svg id="s" xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${S.hill(V)}</svg></body></html>`, { waitUntil: 'networkidle' });
  await p.evaluate(() => document.fonts.ready);
  const times = probe ? [0.5, 1.3, 2.2, 3.0, 3.7, 4.3, 5.0, 5.4, 5.8, 6.4, 8.0, 11.9] : Array.from({ length: FPS * DUR }, (_, i) => i / FPS);
  let i = 0;
  for (const t of times) {
    await p.evaluate(h => { document.getElementById('s').innerHTML = h; }, S.hill(Object.assign({}, V, { state: state(t) })));
    await p.screenshot({ path: path.join(out, (probe ? 'p' : 'f') + String(i++).padStart(4, '0') + '.png') });
  }
  await b.close();
})();
