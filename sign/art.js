// Draws sign art (32 rows of 32 characters, "." off, 1-9 A-F = palette[0..14])
// onto a canvas as round LED dots, the way it looks on the sign, with the
// caption beside it in amber. Used by /sign/ and /sign/review.html.
(function () {
  'use strict';
  var CODES = '.123456789ABCDEF';
  var AMBER = '#E09000';

  // A 3x5 pixel font close to what the board's small font looks like.
  var GLYPHS = {
    A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110', E: '111100110100111',
    F: '111100110100100', G: '011100101101011', H: '101101111101101', I: '111010010010111', J: '001001001101010',
    K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010',
    P: '110101110100100', Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010',
    U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101', Y: '101101010010010',
    Z: '111001010100111', 0: '010101101101010', 1: '010110010010111', 2: '110001010100111', 3: '110001010001110',
    4: '101101111001001', 5: '111100110001110', 6: '011100110101010', 7: '111001010010010', 8: '010101010101010',
    9: '010101011001110', '!': '010010010000010', '?': '110001010000010', "'": '010010000000000', '.': '000000000000010',
    ',': '000000000010100', '-': '000000111000000', '&': '010101010101011', ':': '000010000010000', '/': '001001010100100'
  };

  // Same layout as the board (sign/led/code.py): its letters sit in 6x10
  // pixel cells, so a caption beside the picture fits 3 lines of 5 letters.
  // Anything longer scrolls across in one line, sliding under the picture.
  function lines(text, width) {
    var out = [], cur = '', words = String(text || '').split(' ').filter(Boolean);
    for (var i = 0; i < words.length; i++) {
      var w = words[i];
      if (w.length > width) return null;
      if (!cur) cur = w; else if ((cur + ' ' + w).length <= width) cur += ' ' + w; else { out.push(cur); cur = w; }
    }
    if (cur) out.push(cur);
    return out;
  }

  var timers = new WeakMap();

  // panelWidth 64: picture + caption on one panel; 128: two panels side by side.
  window.drawSignArt = function (canvas, art, panelWidth) {
    var W = panelWidth || 64, H = 32, LEFT = 34, SCROLL = 20;
    if (timers.has(canvas)) { clearInterval(timers.get(canvas)); timers.delete(canvas); }
    var dot = Math.max(3, Math.floor(canvas.clientWidth / W) || 6);
    canvas.width = W * dot; canvas.height = H * dot;
    var g = canvas.getContext('2d');
    var pic = [];
    for (var y = 0; y < H; y++) { pic.push([]); for (var x = 0; x < 32; x++) pic[y].push(null); }
    var pal = (art && art.palette) || [];
    ((art && art.rows) || []).forEach(function (row, y) {
      for (var x = 0; x < row.length && x < 32; x++) {
        var i = CODES.indexOf(row[x]);
        if (i > 0 && pal[i - 1]) pic[y][x] = '#' + pal[i - 1];
      }
    });
    var text = String((art && art.caption) || '');
    var ls = lines(text, Math.floor((W - LEFT) / 6));
    var still = ls && ls.length <= 3;

    function frame(scrollX) {
      var px = [];
      for (var y = 0; y < H; y++) { px.push([]); for (var x = 0; x < W; x++) px[y].push(null); }
      function letters(line, left, mid) {
        for (var c = 0; c < line.length; c++) {
          var gl = GLYPHS[line[c]]; if (!gl) continue;
          for (var k = 0; k < 15; k++) {
            var xx = left + c * 6 + 1 + (k % 3), yy = mid - 2 + Math.floor(k / 3);
            if (gl[k] === '1' && xx >= 0 && xx < W && yy >= 0 && yy < H) px[yy][xx] = AMBER;
          }
        }
      }
      if (still) ls.forEach(function (line, n) {
        letters(line, LEFT + Math.floor(((W - LEFT) - 6 * line.length) / 2), 16 - (ls.length - 1) * 5 + n * 10);
      });
      else letters(text, scrollX, 16);
      for (y = 0; y < H; y++) for (x = 0; x < 32; x++) px[y][x] = pic[y][x];  // the picture sits on top
      g.fillStyle = '#050505'; g.fillRect(0, 0, canvas.width, canvas.height);
      for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
        g.beginPath();
        g.arc(x * dot + dot / 2, y * dot + dot / 2, dot * 0.42, 0, Math.PI * 2);
        g.fillStyle = px[y][x] || '#141313';
        g.fill();
      }
    }

    if (still) { frame(0); return; }
    var start = Date.now();
    function step() {
      var x = W - Math.floor((Date.now() - start) / 1000 * SCROLL);
      if (x < LEFT - 6 * text.length) { start = Date.now(); x = W; }
      frame(x);
    }
    step();
    timers.set(canvas, setInterval(step, 50));
  };
})();
