# Sisyphus stage clock: a 64x32 LED panel on an Adafruit Matrix Portal S3
# that shows the same count-up clock as https://staff.sisyphusbrewing.com/timer/
# and follows the Stream Deck buttons (Supabase rpc timer_start/stop/add/light).
#
# CircuitPython 10. Copy this file, settings.toml and the libraries listed in
# README.md onto the CIRCUITPY drive.

import math
import os
import random
import time

import adafruit_connection_manager
import adafruit_requests
import bitmaptools
import board
import displayio
import microcontroller
import keypad
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_matrixportal.matrix import Matrix

import kevin

URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/timer_state"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
POLL = 1.0  # seconds between checks; a deck press shows up within about a second
# New versions load by themselves: while the clock is stopped (never mid-set), every
# couple of minutes it compares its files with the site and, if one changed, restarts
# so boot.py swaps it in. No RESET needed (Sam, Oct 29 2026).
SITE = "https://staff.sisyphusbrewing.com/timer/led/"
UPDATE_EVERY = 120

WHITE = 0xB4B4B4  # not full white: plenty from the stage, less glow
RED = 0xFF0000
IDLE = 0x101010
DIM = 0x505050  # the small "left" line: readable, but the big time wins

# What the clock says to the comic (Sam, Oct 28 2026). The deck's WRAP IT UP key
# (timer_light) shows the first one at any time.
WRAP_AT = 30  # seconds left
OVER = "YOU BETTER KNOW WHAT YOU ARE DOING...."
WAY_OVER = "NO SERIOUSLY.... ARE YOU FAMOUS?"  # a minute or more over
SCROLL = 30  # pixels a second (small line)

# Layout (Sam, Oct 29 2026): time done is the most important, so it's big on top;
# time left is small underneath. Time added gets a BONUS TIME burst,
# time taken away a game-show buzzer "penalty for being a bad comedian", and WRAP IT UP
# a present getting wrapped. (Sam: big over-the-top celebrations, like a bowling alley's
# screen, but nothing actually about bowling.)

# ---- display ----
matrix = Matrix(width=64, height=32, bit_depth=4)
display = matrix.display
root = displayio.Group()
# time done: big, on top
digits = label.Label(terminalio.FONT, text="", color=IDLE, scale=2)
digits.anchor_point = (0.5, 0.5)
digits.anchored_position = (32, 10)
root.append(digits)
# small line underneath: time left, WRAP IT UP, or the over-time lines scrolling
small = label.Label(terminalio.FONT, text="", color=DIM)
small.anchor_point = (0.5, 0.5)
small.anchored_position = (32, 26)
root.append(small)
display.root_group = root

# ---- big celebration animations ----
FX_COLORS = (0x000000, 0xFF0000, 0xFFB000, 0xFFFF00, 0x00FF40, 0x00A0FF, 0xC040FF, 0xFFFFFF)
fx_palette = displayio.Palette(len(FX_COLORS))
for i, c in enumerate(FX_COLORS):
    fx_palette[i] = c
fx_palette.make_transparent(0)
fx_bmp = displayio.Bitmap(64, 32, len(FX_COLORS))
fx_big = label.Label(terminalio.FONT, text="", color=0xFFFF00, scale=2)
fx_big.anchor_point = (0.5, 0.5)
fx_small = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
fx_small.anchor_point = (0.5, 0.5)
fx_small.anchored_position = (32, 26)
fx_group = displayio.Group()
for item in (displayio.TileGrid(fx_bmp, pixel_shader=fx_palette), fx_big, fx_small):
    fx_group.append(item)
RAINBOW = (0xFF0000, 0xFFB000, 0xFFFF00, 0x00FF40, 0x00A0FF, 0xC040FF)
WHITE_I, RED_I = 7, 1

BONUS_LEN = 3.5
PENALTY_LEN = 4.5
PRESENT_LEN = 4.5
fx_kind, fx_start, fx_text = None, 0.0, ""


def px(x, y, c):
    x, y = int(x), int(y)
    if 0 <= x < 64 and 0 <= y < 32:
        fx_bmp[x, y] = c


def rect(x0, y0, x1, y1, c):
    """Fill x0..x1-1, y0..y1-1, clipped to the panel."""
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(64, int(x1)), min(32, int(y1))
    if x1 > x0 and y1 > y0:
        bitmaptools.fill_region(fx_bmp, x0, y0, x1, y1, c)


# the present: a box 24 wide, 14 tall, sitting at the bottom middle, and its bow
BOX_X, BOX_Y, BOX_W, BOX_H = 20, 17, 24, 14
BOW = ((-4, (-5, -4, -3, 2, 3, 4)), (-3, (-6, -5, -4, -3, -2, 1, 2, 3, 4, 5)),
       (-2, (-5, -4, -3, -2, -1, 0, 1, 2, 3, 4)), (-1, (-2, -1, 0, 1)))


def draw_present(t):
    """WRAP IT UP, literally: the box drops in, the paper wraps it, the ribbon goes
    round, a bow pops on top. t runs 0..2.6 s."""
    drop = 0
    if t < 0.5:  # falls in from the top with a little bounce
        drop = -30 * (1 - t / 0.5) ** 2
    elif t < 0.7:
        drop = -2 * math.sin((t - 0.5) / 0.2 * math.pi)
    x, y = BOX_X, BOX_Y + int(drop)
    rect(x, y, x + BOX_W, y + BOX_H, 2)  # plain cardboard (amber)
    if t > 0.7:  # red paper sweeps across
        w = min(BOX_W, int((t - 0.7) / 0.6 * BOX_W))
        rect(x, y, x + w, y + BOX_H, 1)
    cx = x + BOX_W // 2
    if t > 1.3:  # ribbon down the middle...
        h = min(BOX_H, int((t - 1.3) / 0.3 * BOX_H))
        rect(cx - 1, y, cx + 1, y + h, 3)
    if t > 1.6:  # ...and across
        w = min(BOX_W, int((t - 1.6) / 0.3 * BOX_W))
        rect(x, y + BOX_H // 2 - 1, x + w, y + BOX_H // 2 + 1, 3)
    if t > 1.9:  # the bow pops on (jumps a pixel as it lands)
        lift = 1 if t < 2.05 else 0
        for dy, xs in BOW:
            for dx in xs:
                px(cx + dx, y + dy - lift, 3)


def start_fx(kind, text=""):
    global fx_kind, fx_start, fx_text
    fx_kind, fx_start, fx_text = kind, time.monotonic(), text
    fx_bmp.fill(0)
    fx_big.text, fx_small.text = "", ""
    display.root_group = fx_group


def fx_tick():
    """One frame of the running animation; returns False when it's done."""
    global fx_kind
    t = time.monotonic() - fx_start
    fx_bmp.fill(0)
    if fx_kind == "bonus":
        if t > BONUS_LEN:
            fx_kind = None
            return False
        if t < 0.6:  # the whole screen flashes rainbow
            fx_bmp.fill(1 + int(t * 10) % 6)
            fx_big.text = fx_small.text = ""
        else:
            # sparkles all over, the added time bouncing in rainbow colours
            for _ in range(18):
                px(random.randrange(64), random.randrange(32), random.randrange(1, 8))
            fx_big.text = fx_text
            fx_big.color = RAINBOW[int(t * 8) % len(RAINBOW)]
            fx_big.anchored_position = (32, 10 - int(abs(math.sin((t - 0.6) * 6)) * 4 * max(0, 1.6 - (t - 0.6)) / 1.6))
            fx_small.text = "BONUS TIME"
            fx_small.color = 0xFFFFFF if int(t * 4) % 2 else 0xFFFF00
        return True
    if fx_kind == "penalty":  # time taken away: game-show buzzer for a bad comedian
        if t > PENALTY_LEN:
            fx_kind = None
            return False
        if t < 0.4:  # two red flashes
            if int(t * 10) % 2 == 0:
                fx_bmp.fill(RED_I)
            fx_big.text = fx_small.text = ""
        elif t < 1.5:  # a big red X stamps on, shaking
            shake = random.choice((-1, 0, 1))
            for i in range(-11, 12):
                for w in (-1, 0, 1):
                    px(32 + i + w + shake, 16 + i, RED_I)
                    px(32 + i + w + shake, 16 - i, RED_I)
            fx_big.text = fx_small.text = ""
        else:  # then the lost time, red and shaking
            shake = random.choice((-1, 0, 1)) if t < 2.6 else 0
            fx_big.text = fx_text
            fx_big.color = RED if int(t * 6) % 2 else 0x800000
            fx_big.anchored_position = (32 + shake, 10)
            fx_small.text = ("PENALTY!", "BAD COMIC", "BOOOOO")[int((t - 1.5) / 1.0) % 3]
            fx_small.color = RED
        return True
    if fx_kind == "present":  # WRAP IT UP: a present gets wrapped
        if t > PRESENT_LEN:
            fx_kind = None
            return False
        if t < 2.6:
            fx_big.text = fx_small.text = ""
            draw_present(t)
        else:  # then the message, big and flashing, with confetti
            for _ in range(12):
                px(random.randrange(64), random.randrange(32), random.randrange(1, 8))
            fx_big.text = "WRAP"
            fx_big.anchored_position = (32, 8)
            col = RED if int(t * 5) % 2 else 0xFFFF00
            fx_big.color = col
            fx_small.color = col
            fx_small.text = "IT UP"  # 5 letters at scale 2 = 60 px; "IT UP!" ran off the edge and cut the I in half
            fx_small.scale = 2
            fx_small.anchored_position = (32, 24)
        return True
    return False


def end_fx():
    fx_big.anchored_position = (32, 10)
    fx_small.scale = 1
    fx_small.anchored_position = (32, 26)
    display.root_group = root


# Kevin: press UP for Kevin asking for another beer, DOWN for the timer.
kevin_palette = displayio.Palette(len(kevin.PALETTE))
kevin_index = {}
for i, (ch, color) in enumerate(kevin.PALETTE.items()):
    kevin_palette[i] = color
    kevin_index[ch] = i
kevin_bitmaps = {}
for pic, _, _ in kevin.SCRIPT:
    key = "".join(pic)
    if key not in kevin_bitmaps:
        bmp = displayio.Bitmap(24, 32, len(kevin.PALETTE))
        for y, row in enumerate(pic):
            for x, ch in enumerate(row):
                bmp[x, y] = kevin_index[ch]
        kevin_bitmaps[key] = bmp
first = kevin_bitmaps["".join(kevin.SCRIPT[0][0])]
kevin_sprite = displayio.TileGrid(first, pixel_shader=kevin_palette)
kevin_line1 = label.Label(terminalio.FONT, text="", color=kevin.AMBER, x=26, y=8)
kevin_line2 = label.Label(terminalio.FONT, text="", color=kevin.AMBER, x=26, y=22)
kevin_group = displayio.Group()
for item in (kevin_sprite, kevin_line1, kevin_line2):
    kevin_group.append(item)


# keypad watches the buttons in the background, so a quick tap still counts
# while the board is busy asking the server for the timer.
buttons = keypad.Keys((board.BUTTON_UP, board.BUTTON_DOWN), value_when_pressed=False, pull=True)
UP, DOWN = 0, 1
kevin_mode = False
kevin_step, kevin_until = 0, 0.0


def check_buttons():
    global kevin_mode, kevin_step, kevin_until
    event = buttons.events.get()
    while event:
        if event.pressed:
            if event.key_number == UP and not kevin_mode:
                kevin_mode, kevin_step, kevin_until = True, 0, 0.0
                display.root_group = kevin_group
            elif kevin_mode:  # DOWN, or UP again, goes back to the timer
                kevin_mode = False
                display.root_group = root
        event = buttons.events.get()


def kevin_tick():
    global kevin_step, kevin_until
    now = time.monotonic()
    if now < kevin_until:
        return
    pic, (l1, l2), seconds = kevin.SCRIPT[kevin_step]
    kevin_sprite.bitmap = kevin_bitmaps["".join(pic)]
    if l2:
        kevin_line1.text, kevin_line2.text = l1, l2
        kevin_line1.y = 8
    else:
        kevin_line1.text, kevin_line2.text = l1, ""
        kevin_line1.y = 15
    kevin_until = now + seconds
    kevin_step = (kevin_step + 1) % len(kevin.SCRIPT)


def show(text, color, line="", line_color=DIM):
    small.anchor_point = (0.5, 0.5)
    small.anchored_position = (32, 26)
    if digits.text != text:
        digits.text = text
    if digits.color != color:
        digits.color = color
    if small.text != line:
        small.text = line
    if small.color != line_color:
        small.color = line_color


scroll_text, scroll_start = None, 0.0


def scroll(time_text, text, over_text):
    """Over time: the big time stays put; the small line scrolls the message,
    then shows how far over for 2 s, round and round."""
    global scroll_text, scroll_start
    show(time_text, RED)
    now = time.monotonic()
    if text != scroll_text:
        scroll_text, scroll_start = text, now
    x = 64 - int((now - scroll_start) * SCROLL)
    if x < -6 * len(text):  # scrolled off: show how far over for 2 s, then go again
        show(time_text, RED, over_text, RED)
        if x < -6 * len(text) - 2 * SCROLL:
            scroll_start = now
        return
    small.text, small.color = text, RED
    small.anchor_point = (0, 0.5)
    small.anchored_position = (x, 26)


# ---- network ----
def connect():
    """One try at joining Wi-Fi; the main loop keeps retrying, so Kevin still works offline."""
    try:
        wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
    except Exception as e:  # the room's Wi-Fi may come up after us
        print("wifi", e)


pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
# The built-in certificate list on these boards misses the root Supabase uses
# (Google Trust Services, GTS Root R4), so trust a short list of roots directly.
try:
    with open("roots.pem") as f:
        ssl.load_verify_locations(cadata=f.read())
except Exception as e:
    print("roots", e)
http = adafruit_requests.Session(pool, ssl)


def stamp(text):
    """'2026-10-16T22:03:39.181132+00:00' -> (day number, seconds into the day), UTC.
    Kept as two parts because CircuitPython floats are 32-bit."""
    y, mo, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
    frac = float("0." + text[20:26]) if text[19] == "." else 0.0
    secs = int(text[11:13]) * 3600 + int(text[14:16]) * 60 + int(text[17:19]) + frac
    # days from civil (Howard Hinnant), exact for any Gregorian date
    if mo <= 2:
        y -= 1
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy, secs


def seconds_between(a, b):
    (da, sa), (db, sb) = stamp(a), stamp(b)
    return (db - da) * 86400 + (sb - sa)


def checksum(data):
    c = 0
    for b in data:
        c = (c * 31 + b) & 0xFFFFFFFF
    return c


def newer_on_site():
    """True if code.py or kevin.py on the site differs from the copy on the board.

    A version that boot.py already refused (didn't download whole, didn't compile)
    would differ forever, so each site version gets only one restart: its checksum
    is kept in the board's nvm across the restart."""
    for name in ("code.py", "kevin.py"):
        r = http.get(SITE + name + "?t=%d" % time.monotonic_ns())
        new = r.content if r.status_code == 200 else None
        r.close()
        if not new:
            continue
        try:
            with open(name, "rb") as f:
                same = f.read() == new
        except OSError:
            same = False
        if not same:
            mark = checksum(new).to_bytes(4, "little")
            if bytes(microcontroller.nvm[0:4]) == mark:
                continue  # already restarted once for this version and it didn't take
            microcontroller.nvm[0:4] = mark
            return True
    return False


def fmt(sec):
    sec = max(0, int(sec))
    return "%d:%02d" % (sec // 60, sec % 60)


state = None
elapsed_at_fetch = 0.0  # seconds into the set when we last heard from the server
fetched = time.monotonic()
last_poll = -POLL
was_wrapping = False
last_update_check = time.monotonic()
bonus_pending, bonus_seen = 0, 0.0  # seconds added (or taken, < 0) waiting for the knob to stop

while True:
    check_buttons()
    if kevin_mode:
        kevin_tick()
        time.sleep(0.02)
        continue
    if fx_kind:  # no polling mid-animation (a poll would freeze it for a moment)
        if not fx_tick():
            end_fx()
        time.sleep(0.03)
        continue
    now = time.monotonic()
    if now - last_poll >= POLL:
        last_poll = now
        if not wifi.radio.connected:
            show("WIFI", IDLE)
            connect()
            last_poll = time.monotonic() + 2  # give a failed join a few seconds before the next try
            continue
        try:
            r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}")
            s = r.json()
            r.close()
            # time added to or taken from a running set (not a new START): add it up
            # while the deck knob is still turning, then play one animation for the total
            if (state and s["started_at"] and s["started_at"] == state["started_at"]
                    and s["set_seconds"] != state["set_seconds"]):
                bonus_pending += s["set_seconds"] - state["set_seconds"]
                bonus_seen = time.monotonic()
            elif state and s["started_at"] != state["started_at"]:
                bonus_pending = 0
            state = s
            fetched = time.monotonic()
            if s["started_at"]:
                elapsed_at_fetch = seconds_between(s["started_at"], s["now"])
        except Exception as e:  # lost a poll: keep counting on the last state we had
            print("poll", e)
    if (state is not None and not state["started_at"] and wifi.radio.connected
            and time.monotonic() - last_update_check > UPDATE_EVERY):
        last_update_check = time.monotonic()
        try:
            if newer_on_site():
                show("NEW", WHITE, "UPDATING...", DIM)
                time.sleep(1)
                microcontroller.reset()  # boot.py downloads the new files
        except Exception as e:
            print("update check", e)
    if bonus_pending and time.monotonic() - bonus_seen > 1.5:
        if bonus_pending > 0:
            start_fx("bonus", "+" + fmt(bonus_pending))
        else:
            start_fx("penalty", "-" + fmt(-bonus_pending))
        bonus_pending = 0
        continue

    if not wifi.radio.connected:
        show("WIFI", IDLE)
    elif state is None:
        show("...", IDLE)
    elif not state["started_at"]:
        was_wrapping = False
        if state["light_now"]:
            show(fmt(state["set_seconds"]), RED, "WRAP IT UP", RED)
        else:
            show(fmt(state["set_seconds"]), IDLE)
    else:
        # counts up from 0:00 (a countdown makes comics panic, Sam, Oct 28 2026)
        elapsed = elapsed_at_fetch + time.monotonic() - fetched
        left = state["set_seconds"] - elapsed
        wrapping = left > 0 and (state["light_now"] or left <= WRAP_AT)
        if wrapping and not was_wrapping:
            was_wrapping = True
            start_fx("present")
            continue
        was_wrapping = wrapping
        if wrapping:
            flash = int(time.monotonic() / 0.5) % 2
            show(fmt(elapsed), RED, "WRAP IT UP" if flash else fmt(left) + " LEFT", RED)
        elif left > 0:
            lit = state["light_seconds"] > 0 and left <= state["light_seconds"]
            show(fmt(elapsed), RED if lit else WHITE, fmt(left) + " LEFT", RED if lit else DIM)
        else:
            # over time: the comic gets told, with how far over in between
            scroll(fmt(elapsed), OVER if left > -60 else WAY_OVER, fmt(-left) + " OVER")
    time.sleep(0.03)
