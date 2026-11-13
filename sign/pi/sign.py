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
drew from a guest's suggestion (Supabase rpc sign_next), and once a lap,
"DRAW ON THIS SIGN - SCAN THE QR AT THE BAR". Each frame is drawn
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
SITE = "https://staff.sisyphusbrewing.com/sign/pi/"
SHOW = float(os.getenv("SIGN_SHOW") or 12)  # seconds per beer or picture, as in the mock-up
FPS = 20  # frames a second while something moves
MENU_EVERY = 600
UPDATE_EVERY = 300
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


def caption_block(s, name, style="", info=""):
    """The words under the picture: the name (big on one line if it fits,
    otherwise small on up to two), the style in blue and ABV + price, as much
    of that as fits, centered in the rows left under the picture. A name too
    long for any of that scrolls."""
    name = name.upper()
    room = SIZE - TEXT_Y
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


def art_grail(d, t, name):  # Quest for the Holy Pale: the glow
    pulse = (math.sin(t * 2.4) + 1) / 2
    for a in range(12):
        ang = a / 12 * math.pi * 2 + t * 0.3
        r = 11
        while r < 12 + pulse * 4:
            d.px(16 + math.cos(ang) * r, 13 + math.sin(ang) * r, "#7a6a2a" if a % 2 else "#c8b050")
            r += 1
    for y in range(8, 17):
        ins = (y - 8) // 3
        d.rect(9 + ins, y, 14 - ins * 2, 1, "#fff4c4" if y < 10 else "#f0c040")
    d.rect(15, 17, 2, 7, "#d9a520")
    d.rect(11, 24, 10, 2, "#d9a520")
    d.rect(10, 26, 12, 1, "#b8861a")
    d.px(12, 12, "#fffbe6")
    if pulse > 0.7:
        d.px(16, 3, "#ffffff")
        d.px(26, 9, "#ffffff")
        d.px(5, 18, "#ffffff")


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
    if not blink:
        d.px(13, 11, "#1a1a1a")
        d.px(18, 11, "#1a1a1a")
    frame = "#1c1c1c"  # his glasses (Sam): dark frames read as outlines on the LEDs
    for x0 in (11, 16):
        d.rect(x0, 10, 5, 1, frame)
        d.rect(x0, 12, 5, 1, frame)
        d.px(x0, 11, frame)
        d.px(x0 + 4, 11, frame)
    d.px(10, 11, frame)
    d.px(21, 11, frame)
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


def art_sparkle(d, t, name):  # Mr. Sparkle's Lager: a winking box of soap flakes
    # A nod to the joke the beer is named for, drawn as our own mascot (Sam asked
    # for the detergent box, Nov 12 2026; the cartoon character itself isn't ours to use).
    for k in range(6):  # soap bubbles drifting up out of the box
        by = 9 - ((t * (4 + rnd(k + 11) * 3) + rnd(k) * 9) % 9)
        bx = 9 + math.floor(rnd(k + 5) * 14) + jround(math.sin(t * 2 + k))
        d.px(bx, by, "#bfe6ff")
    d.rect(23, 12, 3, 19, "#b0302a")  # the box's side, in shadow
    d.rect(7, 10, 16, 21, "#f2f2f2")  # the front
    d.rect(7, 10, 16, 5, "#e8452f")  # red top band with a "label"
    for x in range(9, 21, 2):
        d.px(x, 12, "#ffd94a")
    d.rect(7, 27, 16, 4, "#2d6fd0")  # blue bottom band
    d.disc(15, 20, 5, "#ffd23f")  # the mascot: a beaming sun
    wink = t % 4 > 3.3
    d.px(13, 19, "#5a3a10")
    if wink:
        d.px(16, 19, "#5a3a10")
        d.px(17, 19, "#5a3a10")
    else:
        d.px(17, 19, "#5a3a10")
    d.px(12, 22, "#5a3a10")
    d.rect(13, 23, 5, 1, "#5a3a10")
    d.px(18, 22, "#5a3a10")
    tw = (math.sin(t * 4) + 1) / 2  # a big sparkle that twinkles
    r = 2 + jround(tw * 2)
    for i in range(-r, r + 1):
        d.px(26 + i, 6, "#fffbe6")
        d.px(26, 6 + i, "#fffbe6")
    if tw > 0.6:
        d.px(25, 5, "#fff3a0")
        d.px(27, 7, "#fff3a0")
        d.px(25, 7, "#fff3a0")
        d.px(27, 5, "#fff3a0")


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
    (r"peanut|jackpot", art_jackpot), (r"colada|margarita|slush", art_slushie),
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
    msg = "DRAW ON THIS SIGN - SCAN THE QR AT THE BAR"
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


def art_screen(a):
    """A guest's picture (from sign_next): big at the top, caption under it,
    and "BY <their name>" if they gave one."""
    s = Screen()
    pal = []
    for c in a.get("palette", [])[:15]:
        v = int(c, 16)
        pal.append(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
    rows = a.get("rows") or []
    n = len(rows) or 1
    px = s.base.load()
    counts = [0] * 16
    idx = [[0] * ART for _ in range(ART)]
    for y in range(ART):  # 32-row art is drawn three times the size
        row = rows[y * n // ART] or "."
        w = len(row) or 1
        for x in range(ART):
            i = CODES.find(row[x * w // ART])
            i = i if 0 < i <= len(pal) else 0
            idx[y][x] = i
            counts[i] += 1
    # keep the whole sign under what the power supply gives
    ma = sum(counts[i + 1] * lum(c) for i, c in enumerate(pal)) * MA_PER_LED
    dim = min(1.0, POWER_MA / ma) if ma else 1.0
    pal = [tuple(int(v * dim) for v in c) for c in pal]
    for y in range(ART):
        for x in range(ART):
            i = idx[y][x]
            if i:
                px[ART_X + x, ART_Y + y] = pal[i - 1]
    # who drew it, from the name box on /sign/ (Sam, Nov 12 2026)
    who = " ".join(plain(a.get("from_name") or "").split())
    caption_block(s, plain(a.get("caption") or ""), ("BY " + who)[:21] if who else "")
    return s


# ---- network ----
http = requests.Session()


def next_art():
    r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}", timeout=15)
    a = r.json()
    return a if isinstance(a, dict) and a.get("id") else None


def sign_seconds():
    """Seconds per picture, set by a manager on /sign/review.html."""
    r = http.post(URL.replace("sign_next", "sign_seconds"), headers={"apikey": KEY, "Content-Type": "application/json"},
                  data="{}", timeout=15)
    return min(120.0, max(2.0, float(r.json())))


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
    o.brightness = 100
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
    seconds, seconds_at = SHOW, -1e9
    while True:
        now = time.monotonic()
        if now - menu_at > MENU_EVERY or not beers:
            try:
                beers, menu_at = load_beers(), now
            except Exception as e:  # no Wi-Fi: keep the last list
                print("menu", e, flush=True)
        for kind, beer in playlist(beers):
            if time.monotonic() - update_at > UPDATE_EVERY:
                update_at = time.monotonic()
                try:
                    if newer_on_site():
                        show(words_screen("UPDATING..."), 1)
                        sys.exit(0)  # the service starts the new version
                except Exception as e:
                    print("update check", e, flush=True)
            try:
                screen = screen_for(kind, beer)
            except Exception as e:  # no Wi-Fi for a guest's picture: skip it
                print("sign", e, flush=True)
                continue
            if screen:
                if not os.getenv("SIGN_SHOW") and time.monotonic() - seconds_at > 60:
                    seconds_at = time.monotonic()
                    try:
                        seconds = sign_seconds()
                    except Exception as e:  # keep the last setting
                        print("seconds", e, flush=True)
                show(screen, seconds)


if __name__ == "__main__":
    main()
