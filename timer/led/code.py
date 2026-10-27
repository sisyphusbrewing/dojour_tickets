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
import displayio
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_matrixportal.matrix import Matrix

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


def show(text, color):
    if digits.text != text:
        digits.text = text
    if digits.color != color:
        digits.color = color


# ---- network ----
def connect():
    show("WIFI", IDLE)
    while not wifi.radio.connected:
        try:
            wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"))
        except Exception as e:  # keep trying; the room's Wi-Fi may come up after us
            print("wifi", e)
            time.sleep(3)


connect()
pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
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
    now = time.monotonic()
    if now - last_poll >= POLL:
        last_poll = now
        try:
            if not wifi.radio.connected:
                connect()
            r = http.post(URL, headers={"apikey": KEY, "Content-Type": "application/json"}, data="{}")
            s = r.json()
            r.close()
            state = s
            fetched = time.monotonic()
            if s["started_at"]:
                elapsed_at_fetch = seconds_between(s["started_at"], s["now"])
        except Exception as e:  # lost a poll: keep counting on the last state we had
            print("poll", e)

    if state is None:
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
