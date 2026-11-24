// Tuesday open mic story and feed art (Sam, Nov 24 2026: "make the Tuesday graphic
// for the mic eye catching and on brand"). The logo's own tilted band is the hill,
// and the little man from Sam's business card pushes the boulder up it.
// Usage: node story.js <outdir> [variant ...]
const fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const kit = JSON.parse(fs.readFileSync(path.join(__dirname, 'kit.json'), 'utf8'));
const BRAND = { K: '#393637', B: '#4b6c86', G: '#918f90', W: '#ffffff' };
const DEG = Math.PI / 180, A = 8.046 * DEG, TAN = Math.tan(A);   // the logo band's own slope
const FONTS = `<link href="https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,500;0,600;0,700;0,800;0,900;1,600&family=Barlow+Condensed:wght@100;200&family=Playfair+Display:ital,wght@0,600;1,500;1,600&display=swap" rel="stylesheet">`;
const MONT = `font-family="Montserrat, sans-serif"`;

function pieces(lockup, names, map = {}) {
  const m = Object.assign({}, BRAND, map);
  let bb = [1e9, 1e9, -1e9, -1e9], out = '';
  for (const n of names) {
    const p = kit[lockup][n];
    bb = [Math.min(bb[0], p.bb[0]), Math.min(bb[1], p.bb[1]), Math.max(bb[2], p.bb[2]), Math.max(bb[3], p.bb[3])];
    for (const line of p.paths) {
      const col = (line.match(/@(\w)@/) || [])[1];
      if (m[col] === null) continue;
      out += line.replace(/@(\w)@/g, (_, c) => m[c]);
    }
  }
  return { svg: out, bb, w: bb[2] - bb[0], h: bb[3] - bb[1], cx: (bb[0] + bb[2]) / 2, cy: (bb[1] + bb[3]) / 2 };
}
function place(p, x, y, opt = {}) {
  const s = opt.scale || (opt.width ? opt.width / p.w : opt.height / p.h);
  return `<g transform="translate(${x},${y}) ${opt.rotate ? `rotate(${opt.rotate}) ` : ''}scale(${s}) translate(${-p.cx},${-p.cy})">${p.svg}</g>`;
}

// The business card's little man, pushing. Laid out on the card's 14 degree hill
// (business-card/source/card.py), then set down on whatever slope we give him.
function pusher(P0, slope, k, col, gait) {
  const S = 14 * DEG, R = 12.5, g = x => 50 - Math.tan(S) * x, c0 = [72, g(72)];
  const uc = [Math.cos(S), -Math.sin(S)], nc = [-Math.sin(S), -Math.cos(S)];
  const u = [Math.cos(slope), -Math.sin(slope)], n = [-Math.sin(slope), -Math.cos(slope)];
  const M = p => { const d = [p[0] - c0[0], p[1] - c0[1]], s = d[0] * uc[0] + d[1] * uc[1], h = d[0] * nc[0] + d[1] * nc[1]; return [P0[0] + k * (s * u[0] + h * n[0]), P0[1] + k * (s * u[1] + h * n[1])]; };
  const ik = (a, b, l1, l2, bend) => { const dx = b[0] - a[0], dy = b[1] - a[1], d = Math.min(Math.hypot(dx, dy), l1 + l2 - 1e-6), ang = Math.atan2(dy, dx), c = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), t = ang + bend * Math.acos(Math.max(-1, Math.min(1, c))); return [a[0] + l1 * Math.cos(t), a[1] + l1 * Math.sin(t)]; };
  const joint = (a, b, l1, l2, pick) => pick(ik(a, b, l1, l2, 1), ik(a, b, l1, l2, -1));
  const limb = (a0, ra, b0, rb, c) => {
    const a = M(a0), b = M(b0); ra *= k; rb *= k;
    const dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy), nx = -dy / d, ny = dx / d;
    const pts = [[a[0] + nx * ra, a[1] + ny * ra], [b[0] + nx * rb, b[1] + ny * rb], [b[0] - nx * rb, b[1] - ny * rb], [a[0] - nx * ra, a[1] - ny * ra]];
    return `<polygon points="${pts.map(p => p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ')}" fill="${c}"/><circle cx="${a[0].toFixed(2)}" cy="${a[1].toFixed(2)}" r="${ra.toFixed(2)}" fill="${c}"/><circle cx="${b[0].toFixed(2)}" cy="${b[1].toFixed(2)}" r="${rb.toFixed(2)}" fill="${c}"/>`;
  };
  const C = [72 - R * Math.sin(S), g(72) - R * Math.cos(S)];
  const onRock = deg => [C[0] + (R + 0.55) * Math.cos(deg * DEG), C[1] - (R + 0.55) * Math.sin(deg * DEG)];
  const fwd = (a, b) => a[0] > b[0] ? a : b, low = (a, b) => a[1] > b[1] ? a : b;
  const foot = (heel, c, tilt = 0) => limb(heel, 0.75, [heel[0] + 2.7 * Math.cos(-S + tilt * DEG), heel[1] + 2.7 * Math.sin(-S + tilt * DEG)], 0.55, c);
  // Walking, for the moving version: each foot is planted while the body passes
  // over it, then lifts and swings forward. phase runs 0 to 1 per full stride.
  const sfp = (s, lift) => [c0[0] + s * uc[0] + (0.75 + lift) * nc[0], c0[1] + s * uc[1] + (0.75 + lift) * nc[1]];
  const STANCE = 0.62, SF = -27.0, STRIDE = 16.5;
  const footAt = phi => {
    phi = ((phi % 1) + 1) % 1;
    if (phi < STANCE) return { p: sfp(SF - (phi / STANCE) * STRIDE, 0), tilt: 0 };
    const q = (phi - STANCE) / (1 - STANCE), e = q * q * (3 - 2 * q);
    return { p: sfp(SF - STRIDE + STRIDE * e, Math.sin(Math.PI * q) * 1.7), tilt: Math.sin(Math.PI * q) * 24 * (1 - q * 0.5) };
  };
  const bob = gait ? 1.3 + 1.5 * Math.cos(4 * Math.PI * (gait.phase - 0.31)) : 0;  // the hips rise as each leg swings through
  const hip = [40.2 + bob * nc[0], 31.2 + bob * nc[1]], sh = [40.2 + 9.6 * Math.cos(30 * DEG) + bob * 0.25 * nc[0], 31.2 - 9.6 * Math.sin(30 * DEG) + bob * 0.25 * nc[1]];
  const hand = onRock(186), hand2 = onRock(199);
  const fa = gait ? footAt(gait.phase) : { p: [29.8, g(29.8) - 0.75], tilt: 0 }, fb = gait ? footAt(gait.phase + 0.5) : { p: [44.6, g(44.6) - 0.75], tilt: 0 };
  const back = fa.p, front = fb.p;
  let o = '';
  const k2 = joint(hip, front, 8, 8, fwd);
  o += limb(hip, 1.55, k2, 1.15, col.far) + limb(k2, 1.15, front, 0.75, col.far) + foot(front, col.far, fb.tilt);
  const e2 = joint(sh, hand2, 4.7, 4.5, low);
  o += limb(sh, 1.05, e2, 0.8, col.far) + limb(e2, 0.8, hand2, 0.6, col.far);
  const k1 = joint(hip, back, 8, 8, fwd);
  o += limb(hip, 1.65, k1, 1.2, col.man) + limb(k1, 1.2, back, 0.75, col.man) + foot(back, col.man, fa.tilt);
  o += limb(hip, 1.7, sh, 2.45, col.man);
  const head = [sh[0] + 3.4 * Math.cos(12 * DEG), sh[1] + 3.4 * Math.sin(12 * DEG)];
  o += limb(sh, 1.0, head, 0.9, col.man);
  const hc = M(head);
  o += `<circle cx="${hc[0].toFixed(2)}" cy="${hc[1].toFixed(2)}" r="${(2.05 * k).toFixed(2)}" fill="${col.man}"/>`;
  const e1 = joint(sh, hand, 4.7, 4.5, low);
  o += limb(sh, 1.15, e1, 0.85, col.man) + limb(e1, 0.85, hand, 0.65, col.man);
  const bc = M(C);
  return { svg: o, rock: { cx: bc[0], cy: bc[1], r: R * k }, backX: M(back)[0] };
}

// Lettering in the manner of the logo's SISYPHUS: solid letters with a thin line
// down the middle of every stroke. A hairline face is drawn fat, then the same
// hairline is drawn again on top in the band's colour.
function inlineWord(txt, x, y, size, o) {
  const st = `font-family="'Barlow Condensed', sans-serif" font-weight="100" font-size="${size}" letter-spacing="${(o.track || 0.07) * size}" text-anchor="middle"`;
  const fat = size * (o.fat || 0.118), line = size * (o.line || 0.006);
  return `<g transform="translate(${x},${y}) skewY(-8.046)">
    <text ${st} fill="${o.fill}" stroke="${o.fill}" stroke-width="${fat}" stroke-linejoin="round" stroke-linecap="round">${txt}</text>
    <text ${st} fill="${o.inline}" stroke="${o.inline}" stroke-width="${line}">${txt}</text></g>`;
}
const bandY = (cx, cy) => x => cy - (x - cx) * TAN;
function strip(W, y, top, bottom, fill, x0 = -20, x1 = W + 20) {
  return `<polygon points="${x0},${y(x0) + top} ${x1},${y(x1) + top} ${x1},${y(x1) + bottom} ${x0},${y(x0) + bottom}" fill="${fill}"/>`;
}
// A microphone on a straight stand, standing on the slope at x.
function micStand(x, gy, h, c) {
  const top = gy - h, w = h * 0.02;
  return `<g>
    <ellipse cx="${x}" cy="${gy - h * 0.012}" rx="${h * 0.15}" ry="${h * 0.028}" fill="${c}"/>
    <rect x="${x - w / 2}" y="${top}" width="${w}" height="${h}" fill="${c}"/>
    <rect x="${x - w * 1.1}" y="${top + h * 0.42}" width="${w * 2.2}" height="${h * 0.05}" rx="${w * 0.5}" fill="${c}"/>
    <g transform="translate(${x},${top}) rotate(32)">
      <rect x="${-h * 0.03}" y="${-h * 0.035}" width="${h * 0.2}" height="${h * 0.07}" rx="${h * 0.012}" fill="${c}"/>
      <rect x="${-h * 0.16}" y="${-h * 0.03}" width="${h * 0.16}" height="${h * 0.06}" fill="${c}"/>
      <circle cx="${-h * 0.2}" cy="0" r="${h * 0.06}" fill="${c}"/>
    </g></g>`;
}

const THEMES = {
  dark: { bg: '#2b2929', band: BRAND.B, rule: '#8f9194', word: '#ffffff', inline: BRAND.K, man: '#f4f4f2', far: '#bfc6cd', rock: '#5a5c60', rockLit: '#707276', head: '#ffffff', sub: '#c9d6e1', dim: '#9fa4a9', accent: '#a9c3d8', stand: '#f4f4f2' },
  light: { bg: '#ffffff', band: BRAND.B, rule: BRAND.K, word: '#ffffff', inline: BRAND.K, man: BRAND.K, far: '#8a8889', rock: '#9b9a9b', rockLit: '#b1b0b1', head: BRAND.K, sub: BRAND.K, dim: '#6f6d6e', accent: BRAND.B, stand: BRAND.K },
  slate: { bg: BRAND.B, band: '#2b2929', rule: '#ffffff', word: '#ffffff', inline: '#a9c3d8', man: '#ffffff', far: '#c4d3df', rock: '#2b3a47', rockLit: '#34485a', head: '#ffffff', sub: '#ffffff', dim: '#d5e0e9', accent: '#ffffff', stand: '#ffffff' },
};

// opt: {theme, w, h (1920 story, 1350 feed), under: the line under the band, sticker: leave the web address off,
//       seal: false to leave the barrel off, fy: where the sign-up line sits, state: where he is in the moving version}
const scaleFor = H => H > 1500 ? 13.6 : 11.0;   // how big the man and boulder are drawn
function hill(opt) {
  const T = THEMES[opt.theme], W = opt.w, H = opt.h, story = H > 1500;
  const cx = W / 2, cy = story ? 1085 : 800, t = story ? 350 : 290, gap = t * 0.045, rule = t * 0.05;
  const y = bandY(cx, cy), ground = x => y(x) - t / 2 - gap - rule;
  const k = scaleFor(H), x0 = 752;
  const st = opt.state || {}, mx = st.x0 === undefined ? x0 : st.x0;
  const man = pusher([mx, ground(mx)], A, k, T, st.gait);
  const rot = (st.rot || 0), spots = [[-0.42, -0.1, 0.2], [0.3, 0.38, 0.15], [0.22, -0.48, 0.11], [-0.2, 0.52, 0.09]];
  const sx = 1000, standH = story ? 300 : 255;
  // opt.top moves the kicker and headline down: the ad versions need it so the
  // words clear Instagram's covered strip (9:16) and a square crop (4:5).
  const top = opt.top || (story ? 278 : 92);
  const hs = story ? 92 : 84;
  const lines = opt.headline || ['EVERY TUESDAY.', 'FOREVER.'];
  const under = opt.under || 'TONIGHT · 7 PM · FREE';
  const uy = cy + t / 2 + gap + rule + (story ? 96 : 84);
  const fy = opt.fy || (story ? 1508 : 1190);
  const seal = pieces('barrelmark', ['arcTop', 'barrel', 'hopsL', 'hopsR'], { B: T.accent, W: T.bg, K: T.accent });
  return `<rect width="${W}" height="${H}" fill="${T.bg}"/>
  <text x="84" y="${top}" ${MONT} font-weight="800" font-size="${story ? 27 : 24}" letter-spacing="${story ? 7.5 : 6.5}" fill="${T.accent}">SISYPHUS COMEDY CLUB</text>
  ${lines.map((l, i) => (i === 1 && st.forever === false) ? '' : `<text x="80" y="${top + (story ? 122 : 104) + i * hs * 1.1}" ${MONT} font-weight="900" font-size="${hs}" letter-spacing="1" fill="${T.head}">${l}</text>`).join('')}
  ${opt.spot === false ? '' : `<defs><linearGradient id="sp" x1="1" y1="0" x2="0.55" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="${T.spot || 0.2}"/><stop offset="1" stop-color="#fff" stop-opacity="0.02"/></linearGradient></defs><polygon points="${W + 10},${top - 330} ${W + 10},${top - 60} ${sx + standH * 0.42},${ground(sx + standH * 0.42)} ${sx - standH * 0.75},${ground(sx - standH * 0.75)}" fill="url(#sp)"/>`}
  ${micStand(sx, ground(sx) + 2, standH, T.stand)}
  <clipPath id="rk"><circle cx="${man.rock.cx}" cy="${man.rock.cy}" r="${man.rock.r}"/></clipPath>
  <circle cx="${man.rock.cx}" cy="${man.rock.cy}" r="${man.rock.r}" fill="${T.rock}"/>
  <circle clip-path="url(#rk)" cx="${man.rock.cx + man.rock.r * 0.2}" cy="${man.rock.cy - man.rock.r * 0.2}" r="${man.rock.r * 0.92}" fill="${T.rockLit}"/>
  ${opt.spots ? `<g clip-path="url(#rk)"><g transform="rotate(${rot} ${man.rock.cx} ${man.rock.cy})">${spots.map(p => `<circle cx="${man.rock.cx + p[0] * man.rock.r}" cy="${man.rock.cy + p[1] * man.rock.r}" r="${p[2] * man.rock.r}" fill="${T.rock}" fill-opacity=".38"/>`).join('')}</g></g>` : ''}
  ${man.svg}
  ${strip(W, y, -t / 2 - gap - rule, -t / 2 - gap, T.rule)}
  ${strip(W, y, -t / 2, t / 2, T.band)}
  ${strip(W, y, t / 2 + gap, t / 2 + gap + rule, T.rule)}
  ${inlineWord('OPEN MIC', cx + t * 0.03, cy + t * 0.275, t * 0.75, { fill: T.word, inline: T.inline, track: 0.08 })}
  <text transform="translate(${cx},${uy}) skewY(-8.046)" text-anchor="middle" ${MONT} font-weight="900" font-size="${story ? 62 : 56}" letter-spacing="${story ? 7 : 6}" fill="${T.head}">${under}</text>
  <text x="${cx}" y="${fy}" text-anchor="middle" ${MONT} font-weight="800" font-size="${story ? 33 : 27}" letter-spacing="5" fill="${T.accent}">COMICS: SIGN UP BY 6:30 PM</text>
  ${opt.sticker ? '' : `<text x="${cx}" y="${fy + (story ? 52 : 50)}" text-anchor="middle" ${MONT} font-weight="700" font-size="${story ? 33 : 27}" letter-spacing="1.2" fill="${T.sub}">sisyphusbrewing.com/pages/open-mic</text>`}
  ${story && opt.seal !== false ? place(seal, cx, fy + (opt.sticker ? 205 : 150), { height: opt.sticker ? 104 : 118 }) : ''}`;
}

const VARIANTS = {
  'hill-dark': { fn: hill, theme: 'dark', w: 1080, h: 1920 },
  'hill-light': { fn: hill, theme: 'light', w: 1080, h: 1920 },
  'hill-slate': { fn: hill, theme: 'slate', w: 1080, h: 1920 },
  // The every-week versions for the always-on ad: feed (4:5) and stories/reels (9:16, nothing important in the bottom fifth).
  'ad-feed': { fn: hill, theme: 'slate', w: 1080, h: 1350, under: 'TUESDAYS · 7 PM · FREE', top: 128, spots: true },
  'ad-story': { fn: hill, theme: 'slate', w: 1080, h: 1920, under: 'TUESDAYS · 7 PM · FREE', seal: false, top: 306, fy: 1482, spots: true },
  // The website listing: no web address (it is the website), and the bottom strip is left
  // clear because the home page's show card lays its date chip over that corner.
  'listing': { fn: hill, theme: 'slate', w: 1080, h: 1350, under: 'TUESDAYS · 7 PM · FREE', top: 128, fy: 1200, sticker: true, spots: true },
};
module.exports = { VARIANTS, hill, scaleFor, pusher, pieces, place, inlineWord, strip, bandY, micStand, THEMES, BRAND, FONTS, MONT, A, TAN, DEG };

if (require.main === module) (async () => {
  const out = process.argv[2], want = process.argv.slice(3);
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  for (const [name, v] of Object.entries(VARIANTS)) {
    if (want.length && !want.includes(name)) continue;
    const p = await b.newPage({ deviceScaleFactor: 1, viewport: { width: v.w, height: v.h } });
    await p.setContent(`<!doctype html><html><head><meta charset="utf-8">${FONTS}<style>*{margin:0}body{width:${v.w}px;height:${v.h}px;overflow:hidden}</style></head><body><svg xmlns="http://www.w3.org/2000/svg" width="${v.w}" height="${v.h}" viewBox="0 0 ${v.w} ${v.h}">${v.fn(v)}</svg></body></html>`, { waitUntil: 'networkidle' });
    await p.evaluate(() => document.fonts.ready);
    await p.screenshot({ path: path.join(out, name + '.png') });
    await p.close();
  }
  await b.close();
})();
