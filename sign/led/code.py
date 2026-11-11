# Sisyphus taproom sign: LED panels on an Adafruit Matrix Portal S3 that show
# pictures Claude drew from customer suggestions (staff.sisyphusbrewing.com/sign/)
# and the beers on tap, once a manager has OK'd them on /sign/review.html.
# Either a 64x32 panel (two side by side with SIGN_WIDTH = 128), or the front
# bar's 15" square: four 64x64 panels, 128x128, with SIGN_HEIGHT = 128.
#
# CircuitPython 10. Asks Supabase (rpc sign_next) for the next picture every
# SHOW seconds. settings.toml holds the Wi-Fi and the shape.

import os
import time

import adafruit_connection_manager
import adafruit_requests
import displayio
import microcontroller
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_matrixportal.matrix import Matrix

URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/sign_next"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
SHOW = 15  # seconds per picture
PLUG_EVERY = 6  # every 6th turn, tell the room they can draw on the sign
PLUG = "DRAW ON THIS SIGN - SCAN THE QR AT THE BAR"
MENU = "https://sisyphusmenu.stharriman.workers.dev/"  # GoTab, for ABV and price
SCROLL = 20  # pixels a second for captions too long to sit still
AMBER = 0xE09000
WHITE = 0xB4B4B4  # warm gray: pure white glares
CODES = ".123456789ABCDEF"
# New versions load by themselves (Sam: remote updates by default): every few minutes
# the sign compares its code.py with the site and restarts so boot.py swaps it in.
SITE = "https://staff.sisyphusbrewing.com/sign/led/"
UPDATE_EVERY = 300

# Two shapes. The default is one 64x32 panel, or two side by side with
# SIGN_WIDTH = 128 in settings.toml. SIGN_HEIGHT = 128 in settings.toml means
# the front bar's square: four 64x64 panels in a 2x2 grid, 128x128.
WIDTH = int(os.getenv("SIGN_WIDTH") or 64)
SQUARE = int(os.getenv("SIGN_HEIGHT") or 32) >= 128
# How the four panels are cabled. If the quadrant test at power-up shows the
# numbers in the wrong places, these get fixed here and the sign updates itself.
SERPENTINE = True  # second row of panels mounted upside down
ROTATION = 0
# One 5V 10A supply runs all four square panels. A panel can pull 4 A with
# every LED full white, so pictures that would pull more than this are dimmed.
POWER_MA = 8000
MA_PER_LED = 0.98  # full white; 4 A over 4096 LEDs

if SQUARE:
    WIDTH = HEIGHT = 128
    # Colour depth 3, not 4 (Sam, Nov 11 2026): four panels in one chain at depth 4
    # refresh slowly enough that Sam saw a shimmer, worst while the board was busy on
    # Wi-Fi fetching the next picture. Depth 3 refreshes about twice as fast; on these
    # small pictures the colour difference doesn't show.
    matrix = Matrix(width=128, height=128, tile_rows=2, serpentine=SERPENTINE, rotation=ROTATION, bit_depth=3)
    ART = 64  # pictures fill a 64x64 square at the top; 32x32 ones are drawn twice the size
    ART_X, ART_Y = 32, 1
else:
    HEIGHT = 32
    matrix = Matrix(width=WIDTH, height=32, bit_depth=4)
    ART = 32
    ART_X, ART_Y = 0, 0
display = matrix.display

# ---- what's on screen ----
# Wide: the caption sits right of the picture; long ones scroll and slide under it.
# Square: the caption sits under the picture, beers get their ABV and price.
root = displayio.Group()
caption = displayio.Group()
root.append(caption)
art_palette = displayio.Palette(16)
art_bitmap = displayio.Bitmap(ART, ART, 16)
art = displayio.TileGrid(art_bitmap, pixel_shader=art_palette, x=ART_X, y=ART_Y)
root.append(art)
display.root_group = root

TEXT_LEFT = 0 if SQUARE else ART + 2
scroller = None  # (label, started, left) when the caption scrolls


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


def clear_caption():
    global scroller
    while len(caption):
        caption.pop()
    scroller = None


def put(text, y, color=AMBER, scale=1):
    """One still line, centered across the sign."""
    t = label.Label(terminalio.FONT, text=text, color=color, scale=scale)
    t.x = (WIDTH - 6 * scale * len(text)) // 2
    t.y = y
    caption.append(t)


def scroll(text, y, left=0, scale=1):
    global scroller
    t = label.Label(terminalio.FONT, text=text, color=AMBER, scale=scale)
    t.y = y
    t.x = WIDTH
    caption.append(t)
    scroller = (t, time.monotonic(), left)


def set_caption(text, full_width=False):
    """Wide: up to 3 still lines beside the picture, or one scrolling line."""
    clear_caption()
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
        scroll(text, 16, left)


def square_caption(text, info=""):
    """Square: the name big under the picture (10 letters a line), smaller if
    it won't fit in two big lines, scrolling if it won't fit at all."""
    clear_caption()
    big = wrap_words(text, 10)
    small = wrap_words(text, 21)
    if big is not None and len(big) <= 2:
        ys = (77, 99) if len(big) == 2 else (86,)
        for line, y in zip(big, ys):
            put(line, y, scale=2)
    elif small is not None and len(small) <= 2:
        for line, y in zip(small, (82, 96) if len(small) == 2 else (88,)):
            put(line, y)
    else:
        scroll(text, 88, scale=2)
    if info:
        put(info, 119, color=WHITE)


def tick_scroll():
    global scroller
    if not scroller:
        return
    t, started, left = scroller
    x = WIDTH - int((time.monotonic() - started) * SCROLL * t.scale)
    if x < left - 6 * t.scale * len(t.text):  # gone: come round again
        scroller = None
        caption.remove(t)
        scroll(t.text, t.y, left, t.scale)
        return
    t.x = x


def hold_screen():
    """Stop showing changes while a new picture or caption is drawn. Without this
    the panels showed the new picture half drawn in the old picture's colours for a
    moment, which Sam saw as a flash every time the picture changed (Nov 11 2026)."""
    display.auto_refresh = False


def show_screen():
    """Show everything drawn since hold_screen() in one go."""
    display.refresh(minimum_frames_per_second=0)
    display.auto_refresh = True  # scrolling captions need it back on


def lum(c):
    return ((c >> 16) + ((c >> 8) & 0xFF) + (c & 0xFF)) / 765


def show_art(a, info=""):
    hold_screen()
    try:
        draw_art(a, info)
    finally:
        show_screen()


def draw_art(a, info):
    pal = [int(c, 16) for c in a["palette"][:15]]
    rows = a["rows"]
    n = len(rows) or 1
    counts = [0] * 16
    for y in range(ART):  # 32-row art on the square is drawn twice the size
        row = rows[y * n // ART] or "."
        w = len(row) or 1
        for x in range(ART):
            i = CODES.find(row[x * w // ART])
            i = i if 0 < i <= len(pal) else 0
            art_bitmap[x, y] = i
            counts[i] += 1
    # keep the whole sign under what the power supply gives
    ma = sum(counts[i + 1] * lum(c) for i, c in enumerate(pal)) * MA_PER_LED
    dim = min(1.0, POWER_MA / ma) if ma else 1.0
    art_palette[0] = 0x000000
    for i in range(15):
        c = pal[i] if i < len(pal) else 0
        if dim < 1:
            c = (int((c >> 16) * dim) << 16) | (int(((c >> 8) & 0xFF) * dim) << 8) | int((c & 0xFF) * dim)
        art_palette[i + 1] = c
    art.hidden = False
    if SQUARE:
        square_caption(a.get("caption") or "", info)
    else:
        set_caption(a.get("caption") or "")


def show_words(text, small=""):
    hold_screen()
    try:
        draw_words(text, small)
    finally:
        show_screen()


def draw_words(text, small):
    art.hidden = True
    if not SQUARE:
        set_caption(text, full_width=True)
        return
    clear_caption()
    lines = wrap_words(text, 10)
    if lines is None or len(lines) > 3:
        scroll(text, 64, scale=2)
        return
    top = 64 - (len(lines) - 1) * 13 - (10 if small else 0)
    for n, line in enumerate(lines):
        put(line, top + n * 26, scale=2)
    for n, line in enumerate(wrap_words(small, 21) or []):
        put(line, top + len(lines) * 26 + n * 12, color=WHITE)


def quadrant_test():
    """Square only: 1 2 / 3 4 in the four panels for a few seconds at power-up,
    so a photo shows whether the panels are cabled the way the code expects."""
    clear_caption()
    art.hidden = True
    for n, (x, y) in enumerate(((32, 32), (96, 32), (32, 96), (96, 96))):
        t = label.Label(terminalio.FONT, text=str(n + 1), color=AMBER, scale=4)
        t.x, t.y = x - 12, y
        caption.append(t)
    time.sleep(4)


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


def checksum(data):
    c = 0
    for b in data:
        c = (c * 31 + b) & 0xFFFFFFFF
    return c


def newer_on_site():
    """True if code.py on the site differs from the board's copy. Each site version
    gets one restart (its checksum is kept in nvm), so a version boot.py refuses
    doesn't make the sign reboot forever."""
    r = http.get(SITE + "code.py?t=%d" % time.monotonic_ns())
    new = r.content if r.status_code == 200 else None
    r.close()
    if not new:
        return False
    try:
        with open("code.py", "rb") as f:
            if f.read() == new:
                return False
    except OSError:
        pass
    mark = checksum(new).to_bytes(4, "little")
    if bytes(microcontroller.nvm[0:4]) == mark:
        return False
    microcontroller.nvm[0:4] = mark
    return True


def next_art():
    r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}")
    a = r.json()
    r.close()
    return a if a.get("id") else None


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


menu = {}  # beer key -> "6.3%  $8", from GoTab
menu_at = -1e9


def load_menu():
    global menu, menu_at
    menu_at = time.monotonic()
    r = http.get(MENU)
    data = r.json()
    r.close()
    found = {}
    for sec in data.get("sections", []):
        for it in sec.get("items", []):
            price = it.get("price") or ""
            try:
                price = "$%g" % float(price)
            except ValueError:
                price = ""
            found[beer_key(it.get("name", ""))] = "  ".join(p for p in (abv_of(it.get("description") or ""), price) if p)
    menu = found


def info_for(a):
    if not SQUARE or a.get("kind") != "beer":
        return ""
    # a beer's caption is its menu name, cut down if it was over 24 letters
    k = beer_key(a.get("caption") or "")
    if k in menu:
        return menu[k]
    for name, info in menu.items():
        if len(k) >= 5 and (name.startswith(k) or k.startswith(name)):
            return info
    return ""


if SQUARE:
    quadrant_test()
show_words("SISYPHUS")
turn = 0
next_at = 0.0
last_update_check = time.monotonic()
while True:
    now = time.monotonic()
    if wifi.radio.connected and now - last_update_check > UPDATE_EVERY:
        last_update_check = now
        try:
            if newer_on_site():
                show_words("UPDATING...")
                time.sleep(1)
                microcontroller.reset()  # boot.py downloads the new code
        except Exception as e:
            print("update check", e)
    if now >= next_at:
        next_at = now + SHOW
        turn += 1
        if not wifi.radio.connected:
            connect()
            next_at = time.monotonic() + 5
        elif turn % PLUG_EVERY == 0:
            if SQUARE:
                show_words("DRAW ON THIS SIGN", "SCAN THE QR AT THE BAR")
            else:
                show_words(PLUG)
        else:
            try:
                if SQUARE and now - menu_at > 600:
                    load_menu()
            except Exception as e:  # no prices this turn, still show the picture
                print("menu", e)
            try:
                a = next_art()
                if a:
                    show_art(a, info_for(a))
                elif SQUARE:
                    show_words("DRAW ON THIS SIGN", "SCAN THE QR AT THE BAR")
                else:
                    show_words(PLUG)  # nothing approved yet
            except Exception as e:  # keep the last picture up and try again next turn
                print("sign", e)
    tick_scroll()
    time.sleep(0.03)
