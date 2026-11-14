#!/usr/bin/env python3
"""Front bar chalkboard on a Raspberry Pi.

The square 128x128 LED sign at the front bar (four Adafruit 64x64 panels in a
2x2 grid) runs from a Raspberry Pi instead of the Matrix Portal board. Sam chose
this on Nov 11 2026 after live tests showed the Matrix Portal's panel driver
can't refresh four panels without visible flashing (Sam, Nov 11 2026). The Pi
drives the panels with the rpi-rgb-led-matrix library, which keeps a processor
core just for refreshing, so Wi-Fi and drawing never disturb it.

What it shows (the mock-up Sam approved, Nov 12 2026): every beer and slushie
on tap from the GoTab menu, 12 seconds each, with a little animated cartoon,
its name, style, ABV and price. After every 3rd beer comes a picture Claude
drew from a guest's suggestion (Supabase rpc sign_next), and at the end of a
lap, at most once every 10 minutes, "DRAW ON THIS SIGN AT SISYPHUSBREWING.COM/DRAW". Each frame is drawn
off-screen and swapped in whole.

It keeps itself up to date: every 5 minutes it compares itself with
https://staff.sisyphusbrewing.com/sign/pi/sign.py and, if that changed, saves
the new version and exits; the system service starts it again straight away.

Settings live in /etc/sisyphus-sign.env (see install.sh):
  SIGN_WIRING  "regular" when the panel cable is wired straight to the Pi's
               pins (default), "adafruit-hat" with Adafruit's Matrix Bonnet/HAT.
  SIGN_SLOWDOWN  how much to slow the Pi's pins for the panels (left out:
               2 on a Pi 3, 4 on a Pi 4).
  SIGN_PWM_BITS  colour depth, 1-11 (default 8). Lower refreshes faster.
  SIGN_PANELS    which part of the picture each panel in the cable chain shows,
               seen from the front: four of TL TR BL BR, panel 1 (the one the
               Pi plugs into) first. Default "TR TL BR BL".
  SIGN_PANEL_TURN  how far each of those panels is turned in the frame: four
               numbers out of 0 90 180 270, or one for all. Default "180".
  SIGN_ROTATE    turns the whole picture after that: 0 (default), 90, 180, 270.
  SIGN_SHOW      seconds per beer or picture, overriding the setting managers
               change on /sign/review.html (which is checked once a minute).
  SIGN_SHOW_REFRESH  set to 1 to print the refresh rate, for tuning.
  SIGN_PREVIEW   set to a file name like /tmp/sign.png to draw one lap to
               PNGs (sign-00.png, sign-01.png, ...) and stop, for checking the
               layout on a computer without panels. SIGN_PREVIEW_T picks the
               moment of each animation, in seconds (default 2.2).
"""

import colorsys
import math
import os
import re
import sys
import time
import unicodedata

import requests
from PIL import BdfFontFile, Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/sign_next"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
MENU = "https://sisyphusmenu.stharriman.workers.dev/"  # GoTab, for ABV and price
BRIGHT = int(os.getenv("SIGN_BRIGHTNESS") or 50)  # percent; managers change it on /sign/review.html
SITE = "https://staff.sisyphusbrewing.com/sign/pi/"
SHOW = float(os.getenv("SIGN_SHOW") or 12)  # seconds per beer or picture, as in the mock-up
FPS = 20  # frames a second while something moves
MENU_EVERY = 600
UPDATE_EVERY = 300
PLUG_GAP = 600  # "draw on this sign" at most once every 10 minutes (Sam, Nov 12 2026)
SCROLL = 20  # pixels a second for captions too long to sit still
AMBER = (224, 144, 0)
WHITE = (180, 180, 180)  # warm gray: pure white glares
CODES = ".123456789ABCDEF"
SIZE = 128
# Pictures are 32x32, drawn three times the size: a 96x96 square at the top,
# with the words in the 31 rows under it. (Was twice the size until Sam saw it
# on the panels in the black frame: too much black, Nov 12 2026.)
ART = 96
ART_X, ART_Y = 16, 0
TEXT_Y = ART_Y + ART
# One 5V 10A supply runs all four panels. A panel can pull 4 A with every LED
# full white, so pictures that would pull more than this are dimmed.
POWER_MA = 8000
MA_PER_LED = 0.98  # full white; 4 A over 4096 LEDs


# ---- fonts: the classic X11 bitmap fonts, crisp on LEDs ----
def bitmap_font(name):
    """Load fonts/<name>.bdf as a PIL bitmap font (converted once, then cached)."""
    pil = os.path.join(HERE, "fonts", name + ".pil")
    if not os.path.exists(pil):
        with open(os.path.join(HERE, "fonts", name + ".bdf"), "rb") as f:
            BdfFontFile.BdfFontFile(f).save(pil)
    return ImageFont.load(pil)


BIG = bitmap_font("9x18B")  # 9 pixels a letter: 14 letters across
SMALL = bitmap_font("6x10")  # 6 pixels a letter: 21 letters across
BIG_W, SMALL_W = 9, 6
BIG_FIT, SMALL_FIT = SIZE // BIG_W - 1, SIZE // SMALL_W


def wrap_words(text, width):
    lines, cur = [], ""
    for word in text.split():
        if len(word) > width:
            return None  # a word too long to sit still: scroll instead
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---- what's on screen ----
class Screen:
    """One screenful: a still background, plus any moving layers (a cartoon,
    scrolling words) drawn fresh for each frame. t is seconds since it came up."""

    def __init__(self):
        self.base = Image.new("RGB", (SIZE, SIZE))
        self.layers = []

    @property
    def moving(self):
        return bool(self.layers)

    def text(self, line, y, font, w, color=AMBER):
        """One still line, centered across the sign. y is the top of the letters."""
        ImageDraw.Draw(self.base).text(((SIZE - w * len(line)) // 2, y), line, font=font, fill=color)

    def frame(self, t):
        if not self.layers:
            return self.base
        img = self.base.copy()
        for layer in self.layers:
            layer(img, t)
        return img


def scroll_layer(line, font, w, y, color=AMBER):
    travel = SIZE + w * len(line)

    def draw(img, t):
        ImageDraw.Draw(img).text((SIZE - int(t * SCROLL) % travel, y), line, font=font, fill=color)
    return draw


def words_screen(text, small=""):
    s = Screen()
    lines = wrap_words(text, BIG_FIT)
    if lines is None or len(lines) > 3:
        s.layers.append(scroll_layer(text, BIG, BIG_W, 55))
        return s
    smalls = wrap_words(small, SMALL_FIT) or []
    height = len(lines) * 22 + len(smalls) * 12
    top = (SIZE - height) // 2
    for n, line in enumerate(lines):
        s.text(line, top + n * 22, BIG, BIG_W)
    for n, line in enumerate(smalls):
        s.text(line, top + len(lines) * 22 + n * 12, SMALL, SMALL_W, WHITE)
    return s


def quadrant_screen():
    """1 2 / 3 4 in the four panels at start-up, so a photo shows whether the
    panels are cabled the way the program expects."""
    s = Screen()
    for n, (x, y) in enumerate(((32, 32), (96, 32), (32, 96), (96, 96))):
        ImageDraw.Draw(s.base).text((x - 4, y - 9), str(n + 1), font=BIG, fill=AMBER)
    return s


# ---- the beer list, as Sam approved it in the mock-up (Nov 12 2026) ----
# Each beer on tap gets a little animated cartoon, 32x32 drawn twice the size,
# with its name, style, ABV and price from the GoTab menu underneath. The
# letters are a 5x7 pixel font, the same one the mock-up used.
GLYPHS = {
    'A': '01110100011000111111100011000110001', 'B': '11110100011000111110100011000111110',
    'C': '01110100011000010000100001000101110', 'D': '11110100011000110001100011000111110',
    'E': '11111100001000011110100001000011111', 'F': '11111100001000011110100001000010000',
    'G': '01110100011000010111100011000101111', 'H': '10001100011000111111100011000110001',
    'I': '01110001000010000100001000010001110', 'J': '00111000100001000010000101001001100',
    'K': '10001100101010011000101001001010001', 'L': '10000100001000010000100001000011111',
    'M': '10001110111010110101100011000110001', 'N': '10001100011100110101100111000110001',
    'O': '01110100011000110001100011000101110', 'P': '11110100011000111110100001000010000',
    'Q': '01110100011000110001101011001001101', 'R': '11110100011000111110101001001010001',
    'S': '01111100001000001110000010000111110', 'T': '11111001000010000100001000010000100',
    'U': '10001100011000110001100011000101110', 'V': '10001100011000110001100010101000100',
    'W': '10001100011000110101101011010101010', 'X': '10001100010101000100010101000110001',
    'Y': '10001100010101000100001000010000100', 'Z': '11111000010001000100010001000011111',
    '0': '01110100011001110101110011000101110', '1': '00100011000010000100001000010001110',
    '2': '01110100010000100010001000100011111', '3': '11111000100010000010000011000101110',
    '4': '00010001100101010010111110001000010', '5': '11111100001111000001000011000101110',
    '6': '00110010001000011110100011000101110', '7': '11111000010001000100010000100001000',
    '8': '01110100011000101110100011000101110', '9': '01110100011000101111000010001001100',
    "'": '00100001000100000000000000000000000', '.': '00000000000000000000000000110001100',
    '-': '00000000000000011111000000000000000', '$': '00100011111010001110001011111000100',
    '%': '11000110010001000100010001001100011', '!': '00100001000010000100001000000000100',
    '&': '01100100101010001000101011001001101', '/': '00000000010001000100010001000000000',
    ',': '00000000000000000000011000010001000', '?': '01110100010000100010001000000000100',
    ':': '00000011000110000000011000110000000',
}
STYLE_BLUE = (143, 176, 208)
DOT_DIM, DOT_LIT = (42, 58, 74), (91, 122, 153)


def pixel_text(img, s, x, y, color, z=1):
    """Write s in the 5x7 font, z pixels per font pixel, letters 6 apart."""
    p = img.load()
    for n, ch in enumerate(s.upper()):
        g = GLYPHS.get(ch)
        if not g:
            continue
        for k in range(35):
            if g[k] == "1":
                xx, yy = x + (n * 6 + k % 5) * z, y + (k // 5) * z
                for a in range(z):
                    for b in range(z):
                        if 0 <= xx + a < SIZE and 0 <= yy + b < SIZE:
                            p[xx + a, yy + b] = color


def centered_text(img, s, y, color, z=1):
    pixel_text(img, s, (SIZE - (6 * len(s) - 1) * z) // 2, y, color, z)


def caption_block(s, name, style="", info="", room=SIZE - TEXT_Y):
    """The words under the picture: the name (big on one line if it fits,
    otherwise small on up to two), the style in blue and ABV + price, as much
    of that as fits, centered in the first `room` rows under the picture. A
    name too long for any of that scrolls."""
    name = name.upper()
    style = style.upper() if style and len(style) <= 21 else ""
    big, small = wrap_words(name, 10), wrap_words(name, 21)
    names = []
    if big is not None and len(big) == 1:
        names.append([(big[0], AMBER, 2, 16)])  # 14 rows tall, 2 between
    if small is not None and len(small) <= 2:
        names.append([(line, AMBER, 1, 9) for line in small])
    extras = [r for r in ((style, STYLE_BLUE, 1, 9), (info, WHITE, 1, 9)) if r[0]]
    for rows in names:
        for more in (extras, extras[-1:]):
            block = rows + more
            height = sum(r[3] for r in block) - 2
            if height <= room:
                y = TEXT_Y + (room - height) // 2
                for line, color, z, h in block:
                    centered_text(s.base, line, y, color, z)
                    y += h
                return
    span = SIZE + 12 * len(name)  # too long to sit still: it scrolls
    s.layers.append(lambda img, t: pixel_text(img, name, SIZE - int(t * 40) % span, TEXT_Y + 1, AMBER, 2))
    if info:
        centered_text(s.base, info, TEXT_Y + 20, WHITE)


def hexc(h):
    v = int(h.lstrip("#"), 16)
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l / 100, s / 100)
    return (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def rnd(i):
    x = math.sin(i * 127.1 + 311.7) * 43758.5453
    return x - math.floor(x)


def jround(v):
    return int(math.floor(v + 0.5))  # rounds like the mock-up's JavaScript


class Pen:
    """A 32x32 cartoon being drawn. Colors are '#rrggbb' or (r, g, b)."""

    def __init__(self):
        self.img = Image.new("RGB", (32, 32))
        self.p = self.img.load()
        self.cache = {}

    def c(self, col):
        if col is None:
            return (0, 0, 0)
        if isinstance(col, tuple):
            return col
        if col not in self.cache:
            self.cache[col] = hexc(col)
        return self.cache[col]

    def px(self, x, y, col):
        x, y = jround(x), jround(y)
        if 0 <= x < 32 and 0 <= y < 32:
            self.p[x, y] = self.c(col)

    def rect(self, x, y, w, h, col):
        for j in range(int(h)):
            for i in range(int(w)):
                self.px(x + i, y + j, col)

    def disc(self, cx, cy, r, col):
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                if x * x + y * y <= r * r + r * 0.6:
                    self.px(cx + x, cy + y, col)

    def line(self, x0, y0, x1, y1, col):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(int(n) + 1):
            self.px(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, col)

    def pint(self, fill):
        """A pint glass; fill(y, x) gives each row's beer color."""
        for y in range(6, 31):
            inset = jround((y - 6) / 12)
            l, r = 9 + inset, 22 - inset
            self.px(l, y, "#7d8790")
            self.px(r, y, "#7d8790")
            for x in range(l + 1, r):
                col = fill(y, x)
                if col:
                    self.px(x, y, col)
        self.rect(11, 31, 10, 1, "#7d8790")


# The cartoons, ported from the mock-up. t is seconds since the beer came up.
def art_apple(d, t, name):  # AntiSocial Apple: glances around, then turns its back on you
    back = t % 7 > 4.6
    d.disc(16, 19, 10, "#c62a2a")
    d.disc(12, 15, 2, "#c62a2a" if back else "#e8645a")
    d.rect(15, 5, 2, 5, "#6b4a2a")
    d.disc(12 if back else 20, 7, 2, "#3f9a3a")
    if not back:
        dx = 1 if math.sin(t * 1.4) > 0 else 0
        d.rect(10, 16, 4, 4, "#f2f2f2")
        d.rect(18, 16, 4, 4, "#f2f2f2")
        d.rect(10 + dx * 2, 17, 2, 2, None)
        d.rect(18 + dx * 2, 17, 2, 2, None)
        d.rect(10, 15, 4, 1, "#7a1515")
        d.rect(18, 15, 4, 1, "#7a1515")
        d.rect(13, 24, 6, 1, "#7a1515")
    else:
        for i in range(3):
            if int(t * 3) % 4 > i:
                d.px(23 + i * 3, 3, "#f2f2f2")


def art_lager(d, t, name):  # a light lager, bubbles all the way up
    d.pint(lambda y, x: "#f4f1e4" if y < 10 else "#e8b020")
    for i in range(7):
        bx = 11 + math.floor(rnd(i) * 10)
        by = 30 - ((t * (6 + rnd(i + 9) * 5) + rnd(i + 3) * 20) % 20)
        if by > 10:
            d.px(bx, by, "#fff2a8")


def art_kentucky(d, t, name):  # Kentucky Common: a whiskey barrel pouring a beer
    d.rect(3, 4, 14, 15, "#8a5a2e")
    d.rect(2, 6, 16, 11, "#8a5a2e")
    d.rect(2, 8, 16, 1, "#4a4a4a")
    d.rect(2, 14, 16, 1, "#4a4a4a")
    for x in range(5, 17, 4):
        d.rect(x, 4, 1, 15, "#6e4522")
    d.rect(18, 11, 4, 2, "#9aa3ad")
    d.rect(21, 13, 1, 1, "#9aa3ad")
    lvl = min(8, math.floor((t % 6) * 1.6))
    d.px(21, 15 + ((t * 14) % 6), "#c87a2a")
    for y in range(20, 31):
        d.px(16, y, "#7d8790")
        d.px(27, y, "#7d8790")
    d.rect(16, 31, 12, 1, "#7d8790")
    d.rect(17, 31 - lvl, 10, lvl, "#b8661e")
    if lvl > 0:
        d.rect(17, 31 - lvl - 1, 10, 1, "#efe3c8")


TINY = {  # a 3x5 font for words inside the cartoons
    "I": "111010010010111", "D": "110101101101110", "O": "111101101101111",
    "T": "111010010010010", "Y": "101101010010010", "U": "101101101101111",
    "!": "010010010000010",
    "B": "110101110101110", "R": "110101110101101",
}


def tiny_text(d, word, x, y, col):
    for n, ch in enumerate(word):
        g = TINY.get(ch)
        if g:
            for k in range(15):
                if g[k] == "1":
                    d.px(x + n * 4 + k % 3, y + k // 3, col)


def art_gold(d, t, name):  # Fool's Gold: a dope digs up a nugget, his buddy: "YOU IDIOT"
    # Sam, Nov 12 2026: a stupid-looking guy digging for gold, finding a
    # nugget, and his friend going "you idiot".
    p = t % 8
    found = p >= 3.2
    skin, dirt, dirt2 = "#e3a97c", "#7a4a24", "#5e3618"
    d.rect(0, 26, 32, 6, dirt)  # the ground, with his hole
    for x in range(0, 32, 3):
        d.px(x + (x // 3) % 2, 28 + (x // 3) % 3, dirt2)
    d.rect(3, 26, 9, 2, "#2a1a10")
    # the digger, left: crossed eyes, buck teeth, a floppy hat
    d.rect(5, 18, 6, 6, "#c0392b")  # flannel
    d.px(7, 20, "#7a1a12")
    d.px(9, 22, "#7a1a12")
    d.rect(5, 24, 2, 2, "#34507a")
    d.rect(9, 24, 2, 2, "#34507a")
    d.disc(8, 13, 4, skin)
    d.rect(4, 8, 9, 2, "#8a6a3a")  # hat
    d.rect(6, 6, 5, 2, "#8a6a3a")
    d.px(7, 12, "#1a1a1a")  # crossed eyes
    d.px(9, 12, "#1a1a1a")
    d.rect(6, 15, 5, 2, "#7a1a12")  # open mouth
    d.px(8, 15, "#f2f2f2")  # buck teeth
    d.px(9, 15, "#f2f2f2")
    if not found:  # swinging the pickaxe
        up = int(t * 3) % 2 == 0
        if up:
            d.line(11, 19, 15, 12, "#9a6a3a")
            d.line(13, 10, 17, 14, "#9aa3ad")
        else:
            d.line(11, 19, 14, 25, "#9a6a3a")
            d.line(12, 26, 16, 24, "#9aa3ad")
            for k in range(3):  # dirt flying
                d.px(14 + k * 2, 22 - k - int(t * 6) % 2, dirt)
    else:  # holds up the nugget, thrilled
        d.line(10, 18, 13, 12, skin)
        gx, gy = 13, 9
        d.rect(gx, gy, 3, 3, "#f5cf4a")
        d.px(gx, gy, "#fff6c4")
        if int(t * 5) % 2:
            d.px(gx + 4, gy - 1, "#ffffff")
            d.px(gx - 1, gy - 2, "#fff6c4")
        d.line(2, 25, 4, 27, "#9a6a3a")  # the pickaxe dropped in the hole
    # the buddy, right
    d.rect(22, 18, 6, 6, "#2f6d4a")
    d.rect(22, 24, 2, 2, "#34507a")
    d.rect(26, 24, 2, 2, "#34507a")
    d.disc(25, 13, 4, skin)
    d.rect(21, 9, 9, 2, "#3a3a3a")  # cap
    d.rect(21, 9, 2, 1, "#3a3a3a")
    if p >= 4.4:  # face-palm and the line
        d.rect(23, 11, 5, 3, skin)
        d.line(22, 19, 24, 13, skin)
        d.rect(23, 12, 4, 2, "#c8865a")  # the hand over his eyes
        d.rect(12, 0, 20, 7, "#f2f2f2")  # speech bubble
        d.px(24, 7, "#f2f2f2")
        d.px(23, 8, "#f2f2f2")
        tiny_text(d, "IDIOT", 13, 1, "#c0392b")
    else:
        d.px(24, 12, "#1a1a1a")
        d.px(27, 12, "#1a1a1a")
        d.rect(24, 15, 3, 1, "#7a1a12")


def art_sisyfest(d, t, name):  # Sisyfest: up the hill, every single time
    for x in range(32):
        top = jround(31 - x * 0.78)
        d.rect(x, top, 1, 32 - top, "#3b5b3e")
        d.px(x, top, "#5f8a5f")
    p = t % 7
    s = p / 5.5 * 0.82 if p < 5.5 else 0.82 * (1 - (p - 5.5) / 1.5)
    bx = 8 + s * 20
    by = 31 - bx * 0.78 - 6
    d.disc(bx, by, 5, "#8c8c8c")
    d.px(bx - 1, by - 2, "#b5b5b5")
    d.px(bx - 2, by - 1, "#b5b5b5")
    top = p >= 5.5
    mx = 29 if top else bx - 6  # at the top he steps aside and watches it roll
    my = 31 - mx * 0.78
    man = "#e9e6df"
    d.px(mx, my - 7, man)
    d.line(mx, my - 6, mx, my - 3, man)
    d.line(mx, my - 3, mx - 1, my, man)
    d.line(mx, my - 3, mx + 1, my, man)
    if top:
        d.line(mx, my - 5, mx - 2, my - 8, man)
        d.line(mx, my - 5, mx + 2, my - 8, man)
    else:
        d.line(mx, my - 5, mx + 2, my - 5, man)
    d.disc(7, 7, 4, "#e8dcae")  # a big moon over the hill
    d.disc(9, 6, 3, "#000000")  # ...a crescent
    for k in range(4):
        d.px(14 + k * 4, 2 + (k % 2) * 3, "#3e4c5c")


def explorer(d, x, t, running, holding):
    """Our own temple-raiding explorer: pith helmet, khaki, satchel. x is his
    left edge; his feet are on the temple floor (row 26)."""
    skin, khaki, dark = "#e3a97c", "#c8a868", "#6a4a2a"
    d.rect(x, 12, 6, 2, "#d8c890")  # pith helmet
    d.rect(x + 1, 11, 4, 1, "#d8c890")
    d.rect(x + 1, 14, 4, 3, skin)  # face
    d.px(x + 4, 15, "#1a1a1a")
    d.px(x + 3, 16, "#a06040")  # stubble grin
    d.rect(x + 1, 17, 4, 5, khaki)  # shirt
    d.px(x + 2, 18, dark)  # satchel strap
    d.px(x + 3, 19, dark)
    d.rect(x, 20, 2, 2, dark)  # satchel
    if running:  # legs scissoring
        step = int(t * 8) % 2
        d.rect(x + 1, 22, 2, 4 - step, "#5a4030")
        d.rect(x + 3 + step, 22, 2, 4, "#5a4030")
    else:
        d.rect(x + 1, 22, 2, 4, "#5a4030")
        d.rect(x + 3, 22, 2, 4, "#5a4030")
    if holding:  # the chalice held high
        d.rect(x + 5, 13, 1, 4, skin)
        chalice(d, x + 5, 9)


def chalice(d, x, y):
    """A small golden chalice of pale ale, foam on top. (x, y) is its top left."""
    d.rect(x, y, 4, 1, "#f4f1e4")
    d.rect(x, y + 1, 4, 2, "#f0c040")
    d.rect(x + 1, y + 3, 2, 1, "#d9a520")
    d.rect(x, y + 4, 4, 1, "#d9a520")


def art_grail(d, t, name):  # Quest for the Holy Pale: a temple raid
    # Sam, Nov 12 2026: "a lot cooler, like Indiana Jones". Our own explorer
    # grabs the glowing pale ale off its pedestal, and a boulder (Sisyphus's,
    # naturally) chases him out of the temple.
    p = t % 8
    for x in (1, 28):  # dim temple pillars
        d.rect(x, 2, 3, 24, "#3a3428")
        d.rect(x - 1, 2, 5, 1, "#4e4636")
    d.rect(0, 26, 32, 6, "#5a5040")  # stone floor
    for x in range(0, 32, 5):
        d.rect(x, 28 + (x // 5) % 2 * 2, 4, 1, "#40382c")
    d.rect(19, 21, 6, 5, "#7a6a50")  # pedestal
    d.rect(18, 20, 8, 1, "#9a8a68")
    if p < 3.0:  # walking up to it while it glows
        pulse = (math.sin(t * 4) + 1) / 2
        for a in range(8):
            ang = a / 8 * math.pi * 2 + t
            r = 4 + pulse * 2
            d.px(21.5 + math.cos(ang) * r, 17 + math.sin(ang) * r, "#c8b050" if a % 2 else "#7a6a2a")
        chalice(d, 20, 15)
        explorer(d, jround(-2 + p / 3.0 * 12), t, p < 2.4, False)
    elif p < 4.0:  # he lifts it, the temple shakes
        shake = int(t * 20) % 2
        d.px(10 + shake, 1, "#8a7a60")
        d.px(16 - shake, 3, "#8a7a60")
        explorer(d, 10, t, False, True)
    else:  # run!
        q = (p - 4.0) / 4.0
        ex = jround(10 + q * 24)
        explorer(d, ex, t, True, True)
        bx = -8 + q * 30  # the boulder rolling in behind him
        d.disc(bx, 19, 7, "#8c8c8c")
        d.disc(bx - 2, 16, 2, "#a8a8a8")
        spin = int(t * 6) % 4
        for k in range(3):
            ang = spin * math.pi / 2 + k * 2.1
            d.px(bx + math.cos(ang) * 4, 19 + math.sin(ang) * 4, "#6a6a6a")


def art_comet(d, t, name):  # Comet Chameleon: a chameleon riding a comet, changing color as it goes
    # ("karma chameleon... you come and go", Sam asked for a cooler one, Nov 12 2026)
    for i in range(18):  # stars rushing past, near ones faster
        speed = 6 + rnd(i + 40) * 18
        sx = (rnd(i) * 40 - t * speed) % 40 - 4
        sy = math.floor(rnd(i + 20) * 30)
        d.px(sx, sy, "#8a96a8" if speed > 15 else "#3c4652")
        if speed > 18:
            d.px(sx + 1, sy, "#3c4652")
    bob = jround(math.sin(t * 2.2))
    hue = (t * 70) % 360
    for k in range(16):  # the rainbow tail, streaming back to the lower left
        for w in (-1, 0, 1):
            if abs(w) * 3 > k + 2:
                continue
            col = hsl((hue + 180 + k * 22) % 360, 90, 60 - k * 2)
            wav = jround(math.sin(t * 6 - k * 0.7) * min(1, k / 6))
            d.px(16 - k, 25 + bob + jround(k * 0.45) + w + wav, col)
    d.disc(19, 24 + bob, 4, "#ffb347")  # the comet's glowing head
    d.disc(19, 24 + bob, 2, "#fff4c4")
    d.px(20, 23 + bob, "#ffffff")
    body, dark, belly = hsl(hue, 85, 50), hsl(hue, 85, 28), hsl((hue + 40) % 360, 85, 70)
    y0 = 9 + bob
    for x in range(9, 22):  # body: an arched back
        top = y0 + 3 - jround(math.sin((x - 9) / 12 * math.pi) * 3)
        d.px(x, top, dark)
        d.rect(x, top + 1, 1, y0 + 8 - top - 1, body)
        d.px(x, y0 + 8, belly)
    for x in range(10, 21, 3):  # spots
        d.px(x, y0 + 4, dark)
    d.rect(21, y0 + 1, 6, 6, body)  # head with a little crest
    d.px(21, y0, dark)
    d.px(22, y0, dark)
    d.px(23, y0 - 1, dark)
    d.rect(24, y0, 3, 1, dark)
    d.rect(27, y0 + 3, 1, 3, body)
    d.rect(22, y0 + 6, 6, 1, dark)  # mouth line
    d.disc(24, y0 + 3, 1, "#f2f2f2")  # a big rolling eye
    d.px(24 + jround(math.cos(t * 1.7)), y0 + 3 + jround(math.sin(t * 2.3)), "#101010")
    flick = t % 3.5
    if 2.6 < flick < 3.2:  # the tongue shoots out for a star
        reach = jround(min(flick - 2.6, 0.3) / 0.3 * 4)
        d.rect(28, y0 + 5, reach, 1, "#ff5a8a")
        d.px(28 + reach, y0 + 5, "#ff9ab8")
    for lx in (11, 13, 18, 20):  # legs gripping the comet
        d.rect(lx, y0 + 9, 1, 2, dark)
    cx, cy = 7, y0 + 7  # tail curled into a spiral
    for a in range(26):
        ang = a * 0.42
        r = 3.6 - a * 0.13
        d.px(cx + math.cos(ang + math.pi * 0.1) * r + 1, cy - math.sin(ang + math.pi * 0.1) * r - 1, body if a % 4 else dark)


def art_scoop(d, t, name):  # Scoopshot IPA: pineapple and vanilla scoops
    for y in range(19, 32):
        half = max(0, jround((31 - y) * 0.45))
        for x in range(16 - half, 16 + half):
            d.px(x, y, "#c88a40" if (x + y) % 3 else "#9a6428")
    p = t % 6
    cols, rest = ("#f5d33a", "#f3ead0", "#f5d33a"), (15, 9, 4)
    for i in range(3):
        start = i * 1.4
        if p < start:
            break
        y = min(rest[i], -6 + (p - start) * 30)
        d.disc(16, y, 5, cols[i])
        d.px(13, y - 2, "#ffffff")
        if i == 2 and y >= rest[i]:
            d.px(15, y - 6, "#3f9a3a")
            d.px(16, y - 7, "#3f9a3a")
            d.px(17, y - 6, "#3f9a3a")


def art_nitro(d, t, name):  # Bobby Boy: Sam's friend Bob at the bar with his stout
    # Sam, Nov 12 2026: Bob's mutton chops run into a handlebar mustache
    # (a Colonel Sanders vibe); he lifts the pint, sips, and wears the foam.
    skin, chops, shirt = "#e3a97c", "#d6d6ce", "#2f5d8a"  # Bob has white hair (Sam)
    hair, edge = "#c8c8c0", "#8e8e88"
    p = t % 6
    lift = 0.0  # 0 resting on the bar, 1 at his mouth
    if 2.6 <= p < 3.4:
        lift = (p - 2.6) / 0.8
    elif 3.4 <= p < 4.6:
        lift = 1.0
    elif 4.6 <= p < 5.2:
        lift = 1 - (p - 4.6) / 0.6
    d.rect(5, 21, 22, 6, shirt)  # shoulders
    d.rect(13, 20, 6, 2, skin)  # neck
    d.px(15, 22, "#d8d8d8")
    d.px(16, 22, "#d8d8d8")
    d.rect(10, 5, 12, 15, skin)  # face
    d.px(10, 5, None)
    d.px(21, 5, None)
    d.rect(9, 9, 1, 5, skin)  # ears
    d.rect(22, 9, 1, 5, skin)
    d.rect(10, 3, 12, 3, hair)  # hair
    d.rect(9, 4, 1, 4, hair)
    d.rect(22, 4, 1, 4, hair)
    d.rect(12, 9, 3, 1, edge)  # brows
    d.rect(17, 9, 3, 1, edge)
    blink = (t % 3.7) > 3.5
    # his glasses (Sam): thin gold wire rims, so he looks friendly, not shady
    rim = "#4a4e58"  # dark wire, so it shows against his skin on the LEDs
    for x0 in (11, 16):
        d.rect(x0 + 1, 10, 3, 1, rim)
        d.rect(x0 + 1, 12, 3, 1, rim)
        d.px(x0, 11, rim)
        d.px(x0 + 4, 11, rim)
    d.px(10, 11, rim)
    d.px(21, 11, rim)
    if not blink:
        d.px(13, 11, "#3a9be8")  # blue eyes (Sam)
        d.px(18, 11, "#3a9be8")
    d.rect(15, 12, 2, 3, "#c8865a")  # nose
    for y in range(10, 18):  # mutton chops, widening down the cheeks
        w = 2 + (y - 10) // 3
        d.rect(10, y, w, 1, chops)
        d.rect(22 - w, y, w, 1, chops)
    d.rect(11, 15, 10, 2, chops)  # the mustache joining them
    d.rect(10, 18, 3, 1, chops)
    d.rect(19, 18, 3, 1, chops)
    for x, y in ((9, 15), (8, 14), (8, 13), (22, 15), (23, 14), (23, 13)):  # handlebar curls
        d.px(x, y, chops)
    d.rect(11, 17, 10, 1, edge)  # a gray edge so the white whiskers read against his face
    d.rect(14, 17, 4, 1, "#9a4a3a")  # mouth under it
    if 4.6 <= p < 5.9:  # foam on the mustache after a sip
        d.rect(12, 16, 8, 1, "#b08a50")
    d.rect(0, 26, 32, 1, "#c08850")  # the bar
    d.rect(0, 27, 32, 5, "#7a4a24")
    for x in range(2, 32, 7):
        d.rect(x, 28, 1, 4, "#5e3618")
    gx = jround(24 - lift * 6)  # the pint, from the bar up to his mouth
    gy = jround(17 - lift * 5)
    d.rect(gx, gy, 6, 9, "#7d8790")
    d.rect(gx + 1, gy + 2, 4, 6, "#2a1a10")
    d.rect(gx + 1, gy, 4, 2, "#efe0bc")
    if lift < 0.5:  # the nitro cascade, settling
        for i in range(4):
            by = gy + 7 - ((t * 5 + rnd(i) * 6) % 5)
            d.px(gx + 1 + math.floor(rnd(i + 3) * 4), by, "#8a6a48")
    d.rect(gx - 2, gy + 4, 2, 3, skin)  # his hand on the glass
    d.rect(gx - 4, gy + 6, 2, 2, shirt)


def art_jackpot(d, t, name):  # Peanut Butter Jackpot: three peanuts, every time
    p = t % 6
    win = p > 3
    d.rect(2, 6, 26, 21, "#a8282a")
    d.rect(4, 8, 22, 15, "#2a1416")
    if win and int(t * 6) % 2:
        for x in range(2, 28, 2):
            d.px(x, 6, "#ffd94a")
            d.px(x + 1, 26, "#ffd94a")
    for r in range(3):
        x0 = 5 + r * 7
        d.rect(x0, 10, 6, 11, "#f4efe4")
        if p < 1.8 + r * 0.6:
            for y in range(10, 21):
                if (y + math.floor(t * 30)) % 4 == 0:
                    d.rect(x0, y, 6, 1, "#b8b0a0")
        else:
            d.disc(x0 + 3, 13, 2, "#c8955a")
            d.disc(x0 + 3, 18, 2, "#c8955a")
            d.px(x0 + 2, 13, "#e0b27a")
    d.rect(29, 4, 1, 12, "#9aa3ad")
    d.disc(29, 3, 1, "#e23b3b")
    if win:
        for q in range(3):
            d.px(9 + q * 7, 28, "#ffd94a")


def art_sparkle(d, t, name):  # Mr. Sparkle's Lager: a loud late-night soap commercial
    # A nod to the joke the beer is named for, drawn as our own mascot (Sam asked
    # for the detergent box, Nov 12 2026; the cartoon character itself isn't ours
    # to use). "Cooler" (Sam): spinning burst, bouncing box, sparkles everywhere.
    spin = t * 0.8
    for y in range(32):  # a spinning sunburst behind the box
        for x in range(32):
            ang = math.atan2(y - 15, x - 15) + spin
            if int((ang / (2 * math.pi)) * 16) % 2:
                d.px(x, y, "#3a1a5a")
            else:
                d.px(x, y, "#1a2a6a")
    hop = abs(math.sin(t * 3.2)) * 3  # the box bounces
    y0 = jround(8 - hop)
    sq = 1 if hop < 0.4 else 0  # squashes a touch when it lands
    d.rect(25, y0 + 2 + sq, 3, 20 - sq, "#a02a24")  # side
    d.rect(7, y0 + sq, 18, 22 - sq, "#f2f2f2")  # front
    d.rect(7, y0 + sq, 18, 5, "#e8452f")  # red band, gold dots
    for x in range(9, 23, 2):
        d.px(x, y0 + 2 + sq, "#ffd94a")
    d.rect(7, y0 + 18, 18, 4, "#2d6fd0")  # blue band
    for x in range(8, 24, 3):
        d.px(x + int(t * 6) % 3, y0 + 19, "#8ac8ff")
    cx, cy = 16, y0 + 11 + sq  # the mascot: a beaming sun with a wink
    d.disc(cx, cy, 5, "#ffd23f")
    for k in range(8):  # its rays
        ang = k * math.pi / 4 + t * 2
        d.px(cx + math.cos(ang) * 6.5, cy + math.sin(ang) * 6.5, "#ffb000")
    wink = t % 3 > 2.3
    d.px(cx - 2, cy - 1, "#5a3a10")
    if wink:
        d.rect(cx + 1, cy - 1, 2, 1, "#5a3a10")
    else:
        d.px(cx + 2, cy - 1, "#5a3a10")
    d.px(cx - 3, cy + 2, "#5a3a10")
    d.rect(cx - 2, cy + 3, 5, 1, "#5a3a10")
    d.px(cx + 3, cy + 2, "#5a3a10")
    for k in range(9):  # sparkles popping all over
        ph = (t * 1.6 + rnd(k) * 4) % 4
        if ph < 1.0:
            sx, sy = math.floor(rnd(k + 2) * 30) + 1, math.floor(rnd(k + 9) * 30) + 1
            r = 1 if ph < 0.3 or ph > 0.7 else 2
            col = ("#fffbe6", "#8af0ff", "#ffb0f0")[k % 3]
            for i in range(-r, r + 1):
                d.px(sx + i, sy, col)
                d.px(sx, sy + i, col)


def art_gobstopper(d, t, name):  # Neverlasting Gobstopper: a candy-factory jawbreaker
    # Sam, Nov 12 2026: Wonka-themed. A giant jawbreaker in a purple top hat,
    # its layers changing color as it goes, with gold sparkles (our own drawing).
    layers = ("#e0306a", "#ff8a3d", "#ffd94a", "#5ad06a", "#3aa0ff", "#a050e0")
    shift = int(t * 1.5)
    for r in range(11, 0, -2):  # rings from the outside in, rotating colors
        d.disc(16, 20, r, layers[(r // 2 + shift) % len(layers)])
    d.disc(12, 16, 2, "#fff4f8")  # shine
    d.px(11, 15, "#ffffff")
    d.rect(8, 8, 16, 2, "#4a1a6a")  # the hat: brim
    d.rect(11, 0, 10, 8, "#6a2a9a")  # crown
    d.rect(11, 5, 10, 2, "#e0b030")  # gold band
    d.px(10, 9, "#8a4aba")
    for k in range(6):  # gold sparkles popping in and out
        ph = (t * 1.3 + rnd(k) * 3) % 3
        if ph < 0.9:
            sx, sy = 2 + math.floor(rnd(k + 3) * 28), 6 + math.floor(rnd(k + 8) * 24)
            if (sx - 16) ** 2 + (sy - 20) ** 2 > 140:
                d.px(sx, sy, "#ffe680")
                if ph > 0.3 and ph < 0.6:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        d.px(sx + dx, sy + dy, "#c89a20")


def art_colada(d, t, name):  # Piña colada: a beach at sunset, vacation vibes
    # Sam, Nov 12 2026: "a beach scene like vacation vibe", then "too messy
    # with the colors", so: dark sky, one big sun, plain sea and sand, and the
    # drink big in front.
    d.rect(0, 13, 32, 2, "#5a2a1a")  # a thin warm glow on the horizon
    d.disc(16, 15, 6, "#f8a830")  # the sun, half down
    d.disc(16, 15, 4, "#ffd06a")
    d.rect(0, 15, 32, 7, "#1e5aa0")  # the sea
    for k in range(3):  # the sun's reflection, rippling
        w = 6 - k * 2 + int(t * 3 + k) % 2 * 2
        d.rect(16 - w // 2, 16 + k * 2, w, 1, "#f8a830")
    d.rect(0, 22, 32, 10, "#e0c080")  # sand
    sway = math.sin(t * 1.5) * 1.5  # a palm tree on the right, swaying
    for y in range(4, 30):
        bend = (30 - y) / 26
        d.rect(27 - bend * 3 + sway * bend, y, 2, 1, "#7a4a24")
    tx, ty = 24 + sway, 4
    for ex, ey in ((-6, 3), (-4, -2), (6, 3), (4, -2)):
        d.line(tx, ty, tx + ex, ty + ey, "#3f9a3a")
    # the drink, big in front: white slush, pineapple, pink umbrella
    for y in range(17, 29):
        w = 5 if y < 21 or y > 24 else 3
        d.rect(10 - w, y, w * 2, 1, "#f2efe2")
    d.rect(9, 29, 2, 1, "#b8c0c8")
    d.rect(6, 30, 8, 1, "#b8c0c8")
    d.rect(13, 14, 3, 4, "#f5cf4a")  # pineapple wedge
    d.px(14, 13, "#3f9a3a")
    d.line(7, 17, 5, 11, "#c8a060")  # umbrella
    d.rect(1, 10, 9, 1, "#e8407a")
    d.rect(3, 9, 5, 1, "#e8407a")


def art_slushie(d, t, name):  # the slushies: a swirl in a cup
    colada = "colada" in name.lower()
    a, b = ("#f6f1df", "#f5d33a") if colada else ("#7ccf5a", "#b8ec8e")
    for y in range(11, 31):
        ins = (y - 11) // 6
        for x in range(9 + ins, 23 - ins):
            d.px(x, y, a if (x + y + math.floor(t * 6)) % 6 < 3 else b)
    d.disc(16, 10, 6, a)
    d.rect(9, 11, 14, 1, "#7d8790")
    d.line(19, 1, 17, 9, "#e23b3b")
    d.line(20, 1, 18, 9, "#e23b3b")
    if colada:
        d.rect(23, 7, 3, 3, "#f5cf4a")
        d.px(24, 6, "#3f9a3a")
    else:
        d.disc(24, 8, 2, "#a8e05a")
        d.px(24, 8, "#e9ffd0")


def art_spice(d, t, name):  # The Spice Must Flow!: a desert-planet sandworm swallows the pint
    # Sam, Nov 12 2026: "needs to be Dune themed". Our own desert world, not
    # the film's look: two moons over the dunes, orange spice drifting, a
    # ripple in the sand heading for the pumpkin pint, then a giant worm
    # bursts up under it, opens a round mouth full of teeth, gulps the pint
    # and sinks. The pint pops back.
    p = t % 7
    for y in range(22):  # dusk: deep purple up top, burnt orange at the horizon
        d.rect(0, y, 32, 1, hsl((270 + y * 5.2) % 360, 55, 7 + y * 0.8))
    d.disc(5, 5, 2, "#e8e0c8")  # two moons
    d.disc(11, 3, 1, "#c8b8a0")
    for k in range(5):  # stars
        if (math.floor(t * 2) + k) % 4:
            d.px(math.floor(rnd(k) * 32), math.floor(rnd(k + 9) * 10), "#9a90b0")

    def ground(x):
        return 21 + jround(1.6 * math.sin(x * 0.3 + 1))
    for x in range(32):  # the dunes, shaded on the far side of each crest
        g = ground(x)
        shade = ground(x + 1) < g
        for y in range(g, 32):
            d.px(x, y, "#b8823e" if shade and y - g < 3 else "#d9a35a")
        d.px(x, g, "#a8723a" if shade else "#f0c27a")
    cx = 24
    if p < 2.6:  # a ripple in the sand running toward the pint (wormsign)
        rx = jround(2 + p / 2.6 * 18)
        for i in range(-2, 3):
            x = rx + i
            d.px(x, ground(x) - (1 if abs(i) < 2 else 0), "#f0c27a")
            d.px(x, ground(x) + 1, "#8a5a2a")
    # how far the worm is out of the sand
    if p < 2.6 or p >= 5.6:
        h = 0
    elif p < 3.3:
        h = (p - 2.6) / 0.7 * 13
    elif p < 4.6:
        h = 13
    else:
        h = 13 * (1 - (p - 4.6))
    h = jround(h)
    base = ground(cx)
    top = base - h
    if h > 0:
        for y in range(top, base + 1):  # a ringed body with a slight sway
            sway = jround(1.2 * math.sin((base - y) * 0.35 + t * 2))
            for x in range(-5, 6):
                if x in (-5, 5):
                    col = "#5e3a24"
                elif x == -3:
                    col = "#d6a576"
                else:
                    col = "#9a6c45" if (y - top) % 3 == 0 else "#b98a5e"
                d.px(cx + x + sway, y, col)
        for x in range(cx - 7, cx + 8):  # sand spraying off it
            d.px(x, base, "#f0c27a")
            if (x + math.floor(t * 8)) % 3 == 0:
                d.px(x, base - 1 - (x % 2), "#f0c27a")
        if 3.3 <= p < 4.6:  # the mouth opens wide, ringed with teeth
            d.disc(cx, top, 6, "#5e3a24")
            d.disc(cx, top, 5, "#3a0c0c")
            d.disc(cx, top, 2, "#6a1a14")
            for k in range(12):
                a = k * math.pi / 6 + t * 0.8
                d.px(cx + math.cos(a) * 4.6, top + math.sin(a) * 4.6, "#efe4c4")
                d.px(cx + math.cos(a) * 3.6, top + math.sin(a) * 3.6, "#efe4c4" if k % 2 else "#3a0c0c")
        else:
            d.disc(cx, top, 5, "#b98a5e")
            d.disc(cx, top, 2, "#5e3a24")
    # the pumpkin pint: on the dune, lifted on the worm, then dropped in
    if p < 3.9 or p > 6.2:
        if p < 2.6 or p > 6.2:
            py, size = base, 7
        elif p < 3.3:
            py, size = top - 2, 7
        else:  # tossed up, then falling into the mouth and shrinking away
            k = (p - 3.3) / 0.6
            py, size = top - 6 + jround(k * k * 8), max(3, 7 - jround(k * 4))
        w = 5 if size > 4 else 3
        x0 = cx - w // 2
        d.rect(x0, py - size, w, size, "#e8782a")
        d.rect(x0, py - size, w, 2, "#f4ecd8")
        for y in range(py - size + 1, py):
            d.px(x0 - 1, y, "#c9d2d6")
            d.px(x0 + w, y, "#c9d2d6")
        if 6.2 < p < 6.7:  # pops back with a sparkle
            for a in range(4):
                d.px(cx + (5 if a % 2 else -5), py - 9 + a * 2, "#ffd35a")
    for k in range(8):  # spice drifting on the wind
        x = (rnd(k) * 40 + t * (3 + rnd(k + 4) * 3)) % 36 - 2
        y = 6 + rnd(k + 2) * 14 - ((t * 1.5 + rnd(k) * 10) % 6)
        d.px(x, y, "#ff9a30" if k % 2 else "#ffc040")


def art_margarita(d, t, name):  # Margarita: a lime sips the slushie and gets BRAIN FREEZE
    # Sam, Nov 12 2026: "needs to be way cooler", no idea given. A lime with a
    # face slurps the frozen margarita through a long straw, freezes solid
    # from the top down, shivers with ice sparkles ("BRR"), then thaws.
    p = t % 6
    frozen = 0 if p < 2.2 else min(1, (p - 2.2) / 0.8) if p < 4.6 else max(0, 1 - (p - 4.6) / 0.9)
    shake = (1 if math.sin(t * 40) > 0 else -1) if 3.0 < p < 4.6 else 0
    d.rect(0, 29, 32, 3, "#6b4224")  # the bar top
    d.rect(0, 29, 32, 1, "#8a5a32")
    # the glass: salt rim, a bowl of green slush, stem and foot
    level = 12 + (min(p, 2.2) / 2.2) * 4 if p < 4.6 else 16 - (p - 4.6) / 1.4 * 4
    for y in range(12, 20):
        half = 7 - (y - 12) * 0.75
        for x in range(jround(24 - half), jround(24 + half) + 1):
            edge = x in (jround(24 - half), jround(24 + half)) or y == 19
            if edge:
                d.px(x, y, "#9fb3b8")
            elif y >= level:
                d.px(x, y, "#8fe36a" if (x * 3 + y * 5 + math.floor(t * 5)) % 7 < 4 else "#5fc24a")
    for x in range(17, 32):
        d.px(x, 11, "#f2f2ea" if (x + math.floor(t * 4)) % 3 else "#b4b4b4")  # salt, glinting
    d.rect(24, 20, 1, 8, "#9fb3b8")
    d.rect(21, 28, 7, 1, "#9fb3b8")
    d.disc(30, 10, 2, "#3f9a3a")  # lime wedge on the rim
    d.disc(30, 10, 1, "#c8f27a")
    # the straw, slush running up it while he sips
    d.line(14, 13, 23, 15, "#e23b3b")
    d.line(23, 15, 23, 18, "#e23b3b")
    if p < 2.2:
        k = math.floor(t * 8) % 9
        d.px(23 - k, 15 - k * 2 / 9, "#8fe36a")
    # the lime guy, frosting over from the top down
    cx, cy = 8 + shake, 15
    line_y = cy - 8 + frozen * 17
    for y in range(-7, 8):
        for x in range(-7, 8):
            r2 = x * x + y * y
            if r2 > 7 * 7 + 4:
                continue
            ice = cy + y < line_y
            if r2 > 5 * 5 + 3:
                col = "#3fa0c8" if ice else "#2f8a2a"   # rind
            elif r2 > 4 * 4 + 2:
                col = "#bfeaff" if ice else "#e6f7b0"   # pith
            else:
                col = "#8fd2f0" if ice else "#a8e05a"   # flesh
            d.px(cx + x, cy + y, col)
    for a in range(6):  # the lime's segment lines
        ang = a * math.pi / 3 + 0.5
        for r in range(1, 4):
            y = cy + math.sin(ang) * r
            d.px(cx + math.cos(ang) * r, y, "#d4f0ff" if y < line_y else "#d8f59a")
    if frozen > 0.5:  # eyes squeezed shut, teeth chattering
        d.line(cx - 4, cy - 2, cx - 2, cy - 2, "#1d3550")
        d.line(cx + 2, cy - 2, cx + 4, cy - 2, "#1d3550")
        d.rect(cx - 2, cy + 3, 5, 2, "#f2f2ea")
        d.px(cx - 1 + (math.floor(t * 20) % 2), cy + 3, "#1d3550")
        d.px(cx + 1 + (math.floor(t * 20) % 2), cy + 4, "#1d3550")
    else:  # big happy eyes, lips on the straw
        for ex in (cx - 3, cx + 3):
            d.rect(ex - 1, cy - 3, 2, 3, "#ffffff")
            d.px(ex, cy - 2, "#1a1a1a")
        d.disc(cx + 4, cy + 3, 1, "#c23b5a")
    d.line(cx - 3, cy + 7, cx - 3, 28, "#2f8a2a")  # legs
    d.line(cx + 3, cy + 7, cx + 3, 28, "#2f8a2a")
    d.rect(cx - 5, 28, 3, 1, "#2f8a2a")
    d.rect(cx + 3, 28, 3, 1, "#2f8a2a")
    if frozen > 0.9 and 3.0 < p < 4.6:
        for k in range(6):  # ice sparkles flying off
            a = rnd(k) * 6.28
            r = 8 + (t * 6 + rnd(k + 3) * 4) % 5
            d.px(cx - shake + math.cos(a) * r, cy + math.sin(a) * r * 0.8, "#e8fbff")
        tiny_text(d, "BRR", 1, 0, "#8fd2f0")


def art_glass(d, t, name):  # anything new: a pint in a color from its name
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) % 360
    d.pint(lambda y, x: "#f4f1e4" if y < 9 else hsl(h, 60, 45))
    for k in range(5):
        by = 30 - ((t * 7 + rnd(k) * 20) % 20)
        if by > 9:
            d.px(11 + math.floor(rnd(k + 7) * 10), by, hsl(h, 70, 75))


CARTOONS = [  # first match on the beer's name wins; anything else gets a glass
    (r"apple|cider", art_apple), (r"sparkle", art_sparkle), (r"gobstop|wonka", art_gobstopper), (r"samm|lager", art_lager), (r"kentucky", art_kentucky),
    (r"gold", art_gold), (r"sisyfest|oktober", art_sisyfest), (r"holy|grail", art_grail),
    (r"comet", art_comet), (r"scoop", art_scoop), (r"bobby|nitro|stout", art_nitro),
    (r"peanut|jackpot", art_jackpot), (r"colada", art_colada), (r"margarita", art_margarita), (r"spice|dune", art_spice), (r"slush", art_slushie),
]


def cartoon_for(name):
    n = name.lower()
    for pattern, art in CARTOONS:
        if re.search(pattern, n):
            return art
    return art_glass


def style_of(desc):
    """'Golden Amber Ale\n5.4% ABV 20 IBU' -> ('Golden Amber Ale', '5.4%').
    The style is the first short line of the description once a glass size
    ('10oz') and the ABV are taken off; a line that reads like a sentence is
    not a style, so then there is none."""
    desc = desc or ""
    m = re.search(r"(\d+(\.\d+)?)\s*%", desc)
    style = ""
    for line in desc.split("\n")[:2]:
        line = re.sub(r"\d+(\.\d+)?\s*%\s*ABV.*$", "", line, flags=re.I)
        line = re.sub(r"^\s*\d+\s*oz\b", "", line, flags=re.I)
        line = re.sub(r"[-\u2013\s]+$", "", line).strip()
        if line:
            if len(line) <= 22 and not re.search(r"[.!?,:)]", line):
                style = line
            break
    return style, (m.group(1) + "%" if m else "")


def plain(name):
    """Letters the sign's font has: Piña -> PINA."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def beer_screen(item):
    """One beer: its cartoon (moving), name, style, ABV and price."""
    s = Screen()
    name = plain(item.get("name") or "")
    style, abv = style_of(item.get("description"))
    try:
        price = "$%g" % float(item.get("price") or "")
    except ValueError:
        price = ""
    art = cartoon_for(name)

    def draw(img, t):
        pen = Pen()
        art(pen, t, name)
        img.paste(pen.img.resize((ART, ART), Image.NEAREST), (ART_X, ART_Y))
    s.layers.append(draw)
    caption_block(s, name, plain(style), "   ".join(p for p in (abv, price) if p))
    return s


def plug_screen():
    """'Draw on this sign', scrolling between two marching dotted lines."""
    s = Screen()
    # the short address goes to the drawing page (a Shopify redirect, Sam, Nov 13 2026)
    msg = "DRAW ON THIS SIGN AT " + DRAW_URL
    span = SIZE + len(msg) * 12

    def draw(img, t):
        p = img.load()
        step = int(t * 8)
        for i in range(0, SIZE, 2):
            p[i, 44] = DOT_DIM if (i // 2 + step) % 4 else DOT_LIT
            p[i + 1, 83] = DOT_DIM if (i // 2 + step) % 4 else DOT_LIT
        pixel_text(img, msg, SIZE - int(t * 40) % span, 57, AMBER, 2)
    s.layers.append(draw)
    return s


def lum(c):
    return sum(c) / 765


DRAW_URL = "SISYPHUSBREWING.COM/DRAW"  # redirects to staff.sisyphusbrewing.com/sign/
GUEST_FPS = 3  # guest pictures flip through their frames 3 times a second


def art_screen(a):
    """A guest's picture (from sign_next): big at the top, caption under it,
    and "BY <their name>" if they gave one. A picture with frames moves: the
    sign loops it and its frames (Sam, Nov 12 2026: "the customer ones need
    to be animated too")."""
    s = Screen()
    pal = []
    for c in a.get("palette", [])[:15]:
        v = int(c, 16)
        pal.append(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
    pics = [a.get("rows") or []] + [f for f in (a.get("frames") or [])[:3] if isinstance(f, list) and f]
    grids = []
    worst = 0
    for rows in pics:
        n = len(rows) or 1
        counts = [0] * 16
        idx = [[0] * ART for _ in range(ART)]
        for y in range(ART):  # 32-row art is drawn three times the size
            row = str(rows[y * n // ART] or ".")
            w = len(row) or 1
            for x in range(ART):
                i = CODES.find(row[x * w // ART])
                i = i if 0 < i <= len(pal) else 0
                idx[y][x] = i
                counts[i] += 1
        grids.append(idx)
        worst = max(worst, sum(counts[i + 1] * lum(c) for i, c in enumerate(pal)) * MA_PER_LED)
    # keep the whole sign under what the power supply gives, on its brightest frame
    dim = min(1.0, POWER_MA / worst) if worst else 1.0
    pal = [tuple(int(v * dim) for v in c) for c in pal]
    pictures = []
    for idx in grids:
        img = Image.new("RGB", (ART, ART))
        px = img.load()
        for y in range(ART):
            for x in range(ART):
                i = idx[y][x]
                if i:
                    px[x, y] = pal[i - 1]
        pictures.append(img)
    if len(pictures) == 1:
        s.base.paste(pictures[0], (ART_X, ART_Y))
    else:
        def draw(img, t):
            img.paste(pictures[int(t * GUEST_FPS) % len(pictures)], (ART_X, ART_Y))
        s.layers.append(draw)
    # who drew it, from the name box on /sign/ (Sam, Nov 12 2026)
    who = " ".join(plain(a.get("from_name") or "").split())
    caption_block(s, plain(a.get("caption") or ""), ("BY " + who)[:21] if who else "", room=SIZE - TEXT_Y - 9)
    # and how to draw your own, scrolling along the bottom row (Sam, Nov 13 2026:
    # "Can we have the sign display a simple url")
    url = "DRAW YOURS AT " + DRAW_URL
    span = SIZE + 6 * len(url)
    s.layers.append(lambda img, t: pixel_text(img, url, SIZE - int(t * 30) % span, SIZE - 8, WHITE))
    return s


# ---- network ----
http = requests.Session()


def next_art():
    r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}", timeout=15)
    a = r.json()
    return a if isinstance(a, dict) and a.get("id") else None


def sign_config():
    """Seconds per picture, the slides switched off, the brightness and whether
    the sign is on at all, all set by a manager on /sign/review.html."""
    r = http.post(URL.replace("sign_next", "sign_config"), headers={"apikey": KEY, "Content-Type": "application/json"},
                  data="{}", timeout=15)
    c = r.json()
    bright = min(100, max(5, int(c.get("brightness") or BRIGHT)))
    return (min(120.0, max(2.0, float(c.get("seconds") or SHOW))), set(c.get("hidden") or []), bright,
            c.get("on") is not False)


def slide_key(name):
    """A beer's key for switching it off: 'Piña colada' -> 'pinacolada'."""
    return "".join(ch for ch in plain(name).lower() if ch.isascii() and ch.isalnum())


def load_beers():
    """The beers and slushies on tap, in menu order, from the GoTab feed."""
    data = http.get(MENU, timeout=15).json()
    beers = []
    for sec in data.get("sections", []):
        if re.search(r"beer|slush", sec.get("category") or sec.get("name") or "", re.I):
            beers += [it for it in sec.get("items", []) if it.get("name")]
    return beers


def newer_on_site():
    """Save the site's sign.py over this file if it changed. True if it did."""
    r = http.get(SITE + "sign.py", params={"t": int(time.time())}, timeout=15)
    if r.status_code != 200 or b"def main" not in r.content:
        return False
    me = os.path.abspath(__file__)
    with open(me, "rb") as f:
        if f.read() == r.content:
            return False
    with open(me + ".new", "wb") as f:
        f.write(r.content)
    os.replace(me + ".new", me)
    return True


# ---- the panels ----
def pi_model():
    try:
        with open("/proc/device-tree/model") as f:
            return f.read()
    except OSError:
        return ""


def open_panels():
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # only on the Pi

    o = RGBMatrixOptions()
    o.rows = 64
    o.cols = 64
    o.chain_length = 4
    o.parallel = 1
    # No pixel mapper: the panels see one 256x64 strip, one 64x64 block per
    # panel in cable order, and to_panels() below cuts the 128x128 picture up
    # to suit (the library's own mappers could not match the cabling).
    o.hardware_mapping = os.getenv("SIGN_WIRING") or "regular"
    # Faster Pis have to be slowed down or the panels show garbage.
    o.gpio_slowdown = int(os.getenv("SIGN_SLOWDOWN") or (4 if "Pi 4" in pi_model() else 2))
    # 8 bits a colour is plenty for pixel art and refreshes several times faster
    # than the library's default of 11 (the flashing on the old board was a
    # refresh too slow for four panels; Sam, Nov 11 2026).
    o.pwm_bits = int(os.getenv("SIGN_PWM_BITS") or 8)
    o.show_refresh_rate = bool(os.getenv("SIGN_SHOW_REFRESH"))
    o.brightness = BRIGHT
    o.drop_privileges = False  # it needs to rewrite its own file to update
    return RGBMatrix(options=o)


# How the panels sit (Sam's numbered-panel photo, Nov 12 2026). Seen from the
# front with the sign the right way up: panel 1 (the Pi's) top right, 2 top
# left, 3 bottom right, 4 bottom left, and all four mounted upside down. That
# puts panel 1's socket next to the Pi's spot behind the SISYPHUS blade.
SPOTS = {"TL": (0, 0), "TR": (64, 0), "BL": (0, 64), "BR": (64, 64)}


def panel_layout():
    order = (os.getenv("SIGN_PANELS") or "TR TL BR BL").upper().split()
    turns = [int(t) % 360 for t in (os.getenv("SIGN_PANEL_TURN") or "180").split()]
    if len(turns) == 1:
        turns *= 4
    if sorted(order) != sorted(SPOTS) or len(turns) != 4 or any(t % 90 for t in turns):
        raise SystemExit(f"bad SIGN_PANELS / SIGN_PANEL_TURN: {order} {turns}")
    return list(zip(order, turns))


def to_panels(img, layout, turn_all=0):
    """The 128x128 picture as the 256x64 strip the chained panels expect."""
    if turn_all:
        img = img.rotate(-turn_all)  # PIL turns anticlockwise; this is clockwise
    strip = Image.new("RGB", (64 * len(layout), 64))
    for i, (spot, turn) in enumerate(layout):
        x, y = SPOTS[spot]
        block = img.crop((x, y, x + 64, y + 64))
        if turn:
            block = block.rotate(-turn)
        strip.paste(block, (64 * i, 0))
    return strip


def playlist(beers):
    """One lap of the sign: every beer in menu order, a guest's picture after
    every 3rd beer, and "draw on this sign" once, at the end of the lap (Sam,
    Nov 12 2026: every 5 beers was too often)."""
    out = []
    for i, beer in enumerate(beers):
        out.append(("beer", beer))
        if i % 3 == 2:
            out.append(("guest", None))
    if not out or out[-1][0] != "guest":
        out.append(("guest", None))
    out.append(("plug", None))
    return out


def screen_for(kind, beer):
    if kind == "beer":
        return beer_screen(beer)
    if kind == "guest":
        a = next_art()
        # beers come from the menu now; a guest's drawing is anything else
        if a and a.get("kind") != "beer":
            return art_screen(a)
        return None
    return plug_screen()


def main():
    preview = os.getenv("SIGN_PREVIEW")
    if preview:  # draw screens to PNGs, for checking the layout off the Pi
        laps = playlist(load_beers())
        for n, (kind, beer) in enumerate(laps):
            sc = screen_for(kind, beer)
            if sc:
                img = sc.frame(float(os.getenv("SIGN_PREVIEW_T") or 2.2))
                img.resize((SIZE * 4, SIZE * 4), Image.NEAREST).save(preview.replace(".png", "-%02d.png" % n))
        return
    layout = panel_layout()
    turn_all = int(os.getenv("SIGN_ROTATE") or 0) % 360
    matrix = open_panels()
    canvas = matrix.CreateFrameCanvas()

    def stay_dark():
        """Switched off on the review page (Sam, Nov 14 2026: "turn off taproom
        bar digital animation sign"): black panels, a look at the setting every
        30 seconds, and still picking up new versions of this program."""
        nonlocal canvas
        print("switched off on the review page", flush=True)
        canvas.Clear()
        canvas = matrix.SwapOnVSync(canvas)
        checked = time.monotonic()
        while True:
            time.sleep(30)
            try:
                if sign_config()[3]:
                    print("switched back on", flush=True)
                    return
            except Exception as e:  # no Wi-Fi: stay dark and keep asking
                print("config", e, flush=True)
            if time.monotonic() - checked > UPDATE_EVERY:
                checked = time.monotonic()
                try:
                    if newer_on_site():
                        sys.exit(0)  # the service starts the new version
                except Exception as e:
                    print("update check", e, flush=True)

    def show(screen, seconds):
        nonlocal canvas
        start = time.monotonic()
        while True:
            now = time.monotonic()
            canvas.SetImage(to_panels(screen.frame(now - start).convert("RGB"), layout, turn_all))
            canvas = matrix.SwapOnVSync(canvas)  # whole frame at once, no tearing
            left = start + seconds - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 1 / FPS if screen.moving else 0.5))

    show(quadrant_screen(), 4)
    show(words_screen("SISYPHUS"), 2)
    beers, menu_at, update_at = [], -1e9, time.monotonic()
    seconds, hidden, config_at = SHOW, set(), -1e9
    plug_at = time.monotonic()  # first plug 10 minutes after start-up
    empty = 0  # laps in a row with nothing shown
    while True:
        now = time.monotonic()
        if now - menu_at > MENU_EVERY or not beers:
            try:
                beers, menu_at = load_beers(), now
            except Exception as e:  # no Wi-Fi: keep the last list
                print("menu", e, flush=True)
        shown = False
        for kind, beer in playlist(beers):
            if time.monotonic() - update_at > UPDATE_EVERY:
                update_at = time.monotonic()
                try:
                    if newer_on_site():
                        show(words_screen("UPDATING..."), 1)
                        sys.exit(0)  # the service starts the new version
                except Exception as e:
                    print("update check", e, flush=True)
            if time.monotonic() - config_at > 60:
                config_at = time.monotonic()
                try:
                    seconds, hidden, bright, on = sign_config()
                    if os.getenv("SIGN_BRIGHTNESS"):
                        bright = BRIGHT
                    matrix.brightness = bright  # Sam, Nov 13 2026: "make it dimmer"
                    if not on:
                        stay_dark()
                        config_at = -1e9  # fresh settings once it's back on
                except Exception as e:  # keep the last settings
                    print("config", e, flush=True)
                if os.getenv("SIGN_SHOW"):
                    seconds = SHOW
            if kind == "plug":
                if "plug" in hidden or time.monotonic() - plug_at < PLUG_GAP:
                    continue
                plug_at = time.monotonic()
            if kind == "beer" and slide_key(beer.get("name") or "") in hidden:
                continue
            try:
                screen = screen_for(kind, beer)
            except Exception as e:  # no Wi-Fi for a guest's picture: skip it
                print("sign", e, flush=True)
                continue
            if screen:
                show(screen, seconds)
                shown = True
        if not shown:  # everything switched off or no Wi-Fi: don't spin
            # Say why in the log, and after 3 empty laps in a row start over
            # fresh (Sam, Nov 12 2026: it sat on SISYPHUS until a restart).
            empty += 1
            print("nothing to show: %d beers, hidden %s, lap %d" % (len(beers), sorted(hidden), empty), flush=True)
            show(words_screen("SISYPHUS"), seconds)
            menu_at = config_at = -1e9  # fetch the menu and settings again next lap
            if empty >= 3:
                sys.exit(1)  # the service starts it again
        else:
            empty = 0


if __name__ == "__main__":
    main()
