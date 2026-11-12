#!/usr/bin/env python3
"""Front bar chalkboard on a Raspberry Pi.

The square 128x128 LED sign at the front bar (four Adafruit 64x64 panels in a
2x2 grid) runs from a Raspberry Pi instead of the Matrix Portal board. Sam chose
this on Nov 11 2026 after live tests showed the Matrix Portal's panel driver
can't refresh four panels without visible flashing (Sam, Nov 11 2026). The Pi
drives the panels with the rpi-rgb-led-matrix library, which keeps a processor
core just for refreshing, so Wi-Fi and drawing never disturb it.

What it shows is the same as sign/led/code.py: pictures Claude drew from
customer suggestions and the beers on tap (Supabase rpc sign_next), one every
15 seconds, beers with ABV and price from the GoTab menu feed, and every 6th
turn "DRAW ON THIS SIGN". Each picture is drawn off-screen and swapped in whole.

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
  SIGN_SHOW_REFRESH  set to 1 to print the refresh rate, for tuning.
  SIGN_PREVIEW   set to a file name to draw one screen to a PNG and stop
               (for checking the layout on a computer without panels).
"""

import os
import sys
import time

import requests
from PIL import BdfFontFile, Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/sign_next"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
MENU = "https://sisyphusmenu.stharriman.workers.dev/"  # GoTab, for ABV and price
SITE = "https://staff.sisyphusbrewing.com/sign/pi/"
SHOW = 15  # seconds per picture
PLUG_EVERY = 6  # every 6th turn, tell the room they can draw on the sign
MENU_EVERY = 600
UPDATE_EVERY = 300
SCROLL = 20  # pixels a second for captions too long to sit still
AMBER = (224, 144, 0)
WHITE = (180, 180, 180)  # warm gray: pure white glares
CODES = ".123456789ABCDEF"
SIZE = 128
ART = 64  # pictures fill a 64x64 square at the top; 32x32 ones are drawn twice the size
ART_X, ART_Y = 32, 1
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
    """One screenful: a still background (picture + still text) and, if the
    caption is too long, one line that scrolls across it."""

    def __init__(self):
        self.base = Image.new("RGB", (SIZE, SIZE))
        self.scroll = None  # (text, font, letter width, y, started)

    def text(self, line, y, font, w, color=AMBER):
        """One still line, centered across the sign. y is the top of the letters."""
        ImageDraw.Draw(self.base).text(((SIZE - w * len(line)) // 2, y), line, font=font, fill=color)

    def frame(self, now):
        if not self.scroll:
            return self.base
        line, font, w, y, started = self.scroll
        img = self.base.copy()
        travel = SIZE + w * len(line)
        x = SIZE - int((now - started) * SCROLL) % travel
        ImageDraw.Draw(img).text((x, y), line, font=font, fill=AMBER)
        return img


def words_screen(text, small=""):
    s = Screen()
    lines = wrap_words(text, BIG_FIT)
    if lines is None or len(lines) > 3:
        s.scroll = (text, BIG, BIG_W, 55, time.monotonic())
        return s
    smalls = wrap_words(small, SMALL_FIT) or []
    height = len(lines) * 22 + len(smalls) * 12
    top = (SIZE - height) // 2
    for n, line in enumerate(lines):
        s.text(line, top + n * 22, BIG, BIG_W)
    for n, line in enumerate(smalls):
        s.text(line, top + len(lines) * 22 + n * 12, SMALL, SMALL_W, WHITE)
    return s


def lum(c):
    return sum(c) / 765


def art_screen(a, info=""):
    """The picture big at the top, the name under it, ABV and price for beers."""
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
    for y in range(ART):  # 32-row art is drawn twice the size
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
    caption = a.get("caption") or ""
    big = wrap_words(caption, BIG_FIT)
    small = wrap_words(caption, SMALL_FIT)
    if big is not None and len(big) <= 2:
        for line, y in zip(big, (68, 88) if len(big) == 2 else (76,)):
            s.text(line, y, BIG, BIG_W)
    elif small is not None and len(small) <= 2:
        for line, y in zip(small, (74, 86) if len(small) == 2 else (80,)):
            s.text(line, y, SMALL, SMALL_W)
    else:
        s.scroll = (caption, BIG, BIG_W, 76, time.monotonic())
    if info:
        s.text(info, 112, SMALL, SMALL_W, WHITE)
    return s


def quadrant_screen():
    """1 2 / 3 4 in the four panels at start-up, so a photo shows whether the
    panels are cabled the way the program expects."""
    s = Screen()
    for n, (x, y) in enumerate(((32, 32), (96, 32), (32, 96), (96, 96))):
        ImageDraw.Draw(s.base).text((x - 4, y - 9), str(n + 1), font=BIG, fill=AMBER)
    return s


# ---- network ----
http = requests.Session()


def next_art():
    r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}", timeout=15)
    a = r.json()
    return a if isinstance(a, dict) and a.get("id") else None


def beer_key(name):
    return "".join(ch for ch in name.lower() if ch.isalpha() or ch.isdigit())


def abv_of(desc):
    """'6.3% ABV - 36 IBU' -> '6.3%'"""
    i = desc.find("%")
    if i < 1:
        return ""
    j = i
    while j > 0 and (desc[j - 1].isdigit() or desc[j - 1] == "."):
        j -= 1
    return desc[j:i + 1] if j < i else ""


def load_menu():
    data = http.get(MENU, timeout=15).json()
    found = {}
    for sec in data.get("sections", []):
        for it in sec.get("items", []):
            try:
                price = "$%g" % float(it.get("price") or "")
            except ValueError:
                price = ""
            found[beer_key(it.get("name", ""))] = "  ".join(
                p for p in (abv_of(it.get("description") or ""), price) if p)
    return found


def info_for(a, menu):
    if a.get("kind") != "beer":
        return ""
    # a beer's caption is its menu name, cut down if it was over 24 letters
    k = beer_key(a.get("caption") or "")
    if k in menu:
        return menu[k]
    for name, info in menu.items():
        if len(k) >= 5 and (name.startswith(k) or k.startswith(name)):
            return info
    return ""


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


def main():
    preview = os.getenv("SIGN_PREVIEW")
    if preview:  # draw one screen to a PNG, for checking the layout off the Pi
        a = next_art()
        img = art_screen(a, info_for(a, load_menu())).frame(time.monotonic()) if a else \
            words_screen("DRAW ON THIS SIGN", "SCAN THE QR AT THE BAR").frame(0)
        img.resize((SIZE * 4, SIZE * 4), Image.NEAREST).save(preview)
        return
    layout = panel_layout()
    turn_all = int(os.getenv("SIGN_ROTATE") or 0) % 360
    matrix = open_panels()
    canvas = matrix.CreateFrameCanvas()

    def show(screen, seconds):
        nonlocal canvas
        end = time.monotonic() + seconds
        while True:
            now = time.monotonic()
            canvas.SetImage(to_panels(screen.frame(now).convert("RGB"), layout, turn_all))
            canvas = matrix.SwapOnVSync(canvas)  # whole frame at once, no tearing
            if now >= end:
                return
            time.sleep(1 / 30 if screen.scroll else min(0.5, end - now))

    show(quadrant_screen(), 4)
    show(words_screen("SISYPHUS"), 2)
    menu, menu_at, update_at, turn = {}, -1e9, time.monotonic(), 0
    while True:
        turn += 1
        now = time.monotonic()
        if now - update_at > UPDATE_EVERY:
            update_at = now
            try:
                if newer_on_site():
                    show(words_screen("UPDATING..."), 1)
                    sys.exit(0)  # the service starts the new version
            except Exception as e:
                print("update check", e, flush=True)
        screen = None
        if turn % PLUG_EVERY:
            try:
                if now - menu_at > MENU_EVERY:
                    menu, menu_at = load_menu(), now
            except Exception as e:  # no prices this time, still show the picture
                print("menu", e, flush=True)
            try:
                a = next_art()
                if a:
                    screen = art_screen(a, info_for(a, menu))
            except Exception as e:  # no Wi-Fi: say the plug line, try again next turn
                print("sign", e, flush=True)
        show(screen or words_screen("DRAW ON THIS SIGN", "SCAN THE QR AT THE BAR"), SHOW)


if __name__ == "__main__":
    main()
