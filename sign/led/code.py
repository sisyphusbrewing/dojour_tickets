# Sisyphus taproom sign: a 64x32 LED panel (or two side by side, 128x32) on an
# Adafruit Matrix Portal S3 that shows pictures Claude drew from customer
# suggestions (staff.sisyphusbrewing.com/sign/) and the beers on tap, once a
# manager has OK'd them on /sign/review.html.
#
# CircuitPython 10. Asks Supabase (rpc sign_next) for the next picture every
# SHOW seconds. settings.toml holds the Wi-Fi, plus SIGN_WIDTH = 128 when two
# panels are chained.

import os
import time

import adafruit_connection_manager
import adafruit_requests
import displayio
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_matrixportal.matrix import Matrix

URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/sign_next"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
SHOW = 15  # seconds per picture
PLUG_EVERY = 6  # every 6th turn, tell the room they can draw on the sign
PLUG = "DRAW ON THIS SIGN - SCAN THE QR AT THE BAR"
SCROLL = 20  # pixels a second for captions too long to sit still
AMBER = 0xE09000
CODES = ".123456789ABCDEF"
ART = 32  # pictures are 32x32

WIDTH = os.getenv("SIGN_WIDTH") or 64
matrix = Matrix(width=WIDTH, height=32, bit_depth=4)
display = matrix.display

# ---- what's on screen ----
# The caption sits right of the picture; long ones scroll and slide under it.
root = displayio.Group()
caption = displayio.Group()
root.append(caption)
art_palette = displayio.Palette(16)
art_bitmap = displayio.Bitmap(ART, ART, 16)
art = displayio.TileGrid(art_bitmap, pixel_shader=art_palette)
root.append(art)
display.root_group = root

TEXT_LEFT = ART + 2
TEXT_WIDTH = WIDTH - TEXT_LEFT
PER_LINE = TEXT_WIDTH // 6  # terminalio letters are 6 pixels wide
scroller = None  # (label, started) when the caption scrolls


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


def set_caption(text, full_width=False):
    """Up to 3 still lines beside the picture, or one scrolling line."""
    global scroller
    while len(caption):
        caption.pop()
    scroller = None
    left = 0 if full_width else TEXT_LEFT
    width = WIDTH - left
    lines = wrap_words(text, width // 6)
    if lines is not None and len(lines) <= 3:
        for n, line in enumerate(lines):  # label y is the middle of the letters
            t = label.Label(terminalio.FONT, text=line, color=AMBER)
            t.x = left + (width - 6 * len(line)) // 2
            t.y = 16 - (len(lines) - 1) * 5 + n * 10
            caption.append(t)
    else:
        t = label.Label(terminalio.FONT, text=text, color=AMBER)
        t.y = 16
        t.x = WIDTH
        caption.append(t)
        scroller = (t, time.monotonic(), left)


def tick_scroll():
    if not scroller:
        return
    t, started, left = scroller
    x = WIDTH - int((time.monotonic() - started) * SCROLL)
    if x < left - 6 * len(t.text):  # gone: come round again
        set_caption(t.text, left == 0)
        return
    t.x = x


def show_art(a):
    pal = a["palette"]
    art_palette[0] = 0x000000
    for i in range(15):
        art_palette[i + 1] = int(pal[i], 16) if i < len(pal) else 0
    for y, row in enumerate(a["rows"][:ART]):
        for x, ch in enumerate(row[:ART]):
            i = CODES.find(ch)
            art_bitmap[x, y] = i if i > 0 else 0
    art.hidden = False
    set_caption(a["caption"] or "")


def show_words(text):
    art.hidden = True
    set_caption(text, full_width=True)


# ---- network ----
def connect():
    try:
        wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
    except Exception as e:  # the room's Wi-Fi may come up after us
        print("wifi", e)


pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
# Same as the stage clock: the board's built-in roots miss Supabase's (GTS Root R4).
try:
    with open("roots.pem") as f:
        ssl.load_verify_locations(cadata=f.read())
except Exception as e:
    print("roots", e)
http = adafruit_requests.Session(pool, ssl)


def next_art():
    r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}")
    a = r.json()
    r.close()
    return a if a.get("id") else None


show_words("SISYPHUS")
turn = 0
next_at = 0.0
while True:
    now = time.monotonic()
    if now >= next_at:
        next_at = now + SHOW
        turn += 1
        if not wifi.radio.connected:
            connect()
            next_at = time.monotonic() + 5
        elif turn % PLUG_EVERY == 0:
            show_words(PLUG)
        else:
            try:
                a = next_art()
                if a:
                    show_art(a)
                else:
                    show_words(PLUG)  # nothing approved yet
            except Exception as e:  # keep the last picture up and try again next turn
                print("sign", e)
    tick_scroll()
    time.sleep(0.03)
