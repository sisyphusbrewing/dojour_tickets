# Sisyphus stage clock: a 64x32 LED panel on an Adafruit Matrix Portal S3
# that shows the same countdown as https://staff.sisyphusbrewing.com/timer/
# and follows the Stream Deck buttons (Supabase rpc timer_start/stop/add/light).
#
# CircuitPython 10. Copy this file, settings.toml and the libraries listed in
# README.md onto the CIRCUITPY drive.

import os
import time

import adafruit_connection_manager
import adafruit_requests
import board
import displayio
import keypad
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_matrixportal.matrix import Matrix

import kevin

URL = "https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/timer_state"
KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"
POLL = 1.0  # seconds between checks; a deck press shows up within about a second

WHITE = 0xB4B4B4  # not full white: plenty from the stage, less glow
RED = 0xFF0000
IDLE = 0x101010

# ---- display ----
matrix = Matrix(width=64, height=32, bit_depth=4)
display = matrix.display
root = displayio.Group()
digits = label.Label(terminalio.FONT, text="", color=IDLE, scale=2)
digits.anchor_point = (0.5, 0.5)
digits.anchored_position = (32, 16)
root.append(digits)
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


def show(text, color):
    if digits.text != text:
        digits.text = text
    if digits.color != color:
        digits.color = color


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


def fmt(sec):
    sec = max(0, int(sec))
    return "%d:%02d" % (sec // 60, sec % 60)


state = None
elapsed_at_fetch = 0.0  # seconds into the set when we last heard from the server
fetched = time.monotonic()
last_poll = -POLL

while True:
    check_buttons()
    if kevin_mode:
        kevin_tick()
        time.sleep(0.02)
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
            state = s
            fetched = time.monotonic()
            if s["started_at"]:
                elapsed_at_fetch = seconds_between(s["started_at"], s["now"])
        except Exception as e:  # lost a poll: keep counting on the last state we had
            print("poll", e)

    if not wifi.radio.connected:
        show("WIFI", IDLE)
    elif state is None:
        show("...", IDLE)
    elif not state["started_at"]:
        show(fmt(state["set_seconds"]), RED if state["light_now"] else IDLE)
    else:
        left = state["set_seconds"] - (elapsed_at_fetch + time.monotonic() - fetched)
        if left > 0:
            lit = state["light_now"] or (state["light_seconds"] > 0 and left <= state["light_seconds"])
            show(fmt(-(-left // 1)), RED if lit else WHITE)
        else:
            # over time: blink red, counting up
            show("+" + fmt(-left) if int(-left * 2) % 2 == 0 else "", RED)
    time.sleep(0.05)
