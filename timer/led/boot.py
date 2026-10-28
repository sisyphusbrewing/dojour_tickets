# Sisyphus stage clock: runs once at power-up (or RESET), before code.py.
#
# Keeps the clock up to date over Wi-Fi: fetches the latest code.py and kevin.py
# from https://staff.sisyphusbrewing.com/timer/led/ and swaps them in if they
# changed. A file that doesn't download whole or doesn't compile is skipped, so
# a bad copy never replaces a good one.
#
# For the board to write its own files, the computer sees CIRCUITPY as
# read-only. To copy files over USB instead, hold DOWN while pressing RESET.

import os
import time

import board
import digitalio
import storage

BASE = "https://staff.sisyphusbrewing.com/timer/led/"
FILES = ("code.py", "kevin.py")


def update():
    import adafruit_connection_manager
    import adafruit_requests
    import wifi

    wifi.radio.connect(os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD"), timeout=15)
    pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
    ssl = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
    with open("roots.pem") as f:  # same root list code.py trusts
        ssl.load_verify_locations(cadata=f.read())
    http = adafruit_requests.Session(pool, ssl)
    for name in FILES:
        try:
            r = http.get(BASE + name + "?t=%d" % time.monotonic_ns())
            new = r.content if r.status_code == 200 else None
            r.close()
            if not new:
                continue
            try:
                with open(name, "rb") as f:
                    if f.read() == new:
                        continue
            except OSError:
                pass  # not on the board yet
            try:
                compile(new.decode(), name, "exec")  # raises on a broken or cut-off file
            except NameError:  # a build without compile(): trust the download
                pass
            with open(name + ".new", "wb") as f:
                f.write(new)
            try:
                os.remove(name)
            except OSError:
                pass
            os.rename(name + ".new", name)
            print("updated", name)
        except Exception as e:
            print("update", name, e)


down = digitalio.DigitalInOut(board.BUTTON_DOWN)
down.switch_to_input(pull=digitalio.Pull.UP)
usb_copy = not down.value  # DOWN held: leave the drive to the computer
down.deinit()

if not usb_copy:
    storage.remount("/", readonly=False)
    try:
        update()
    except Exception as e:  # no Wi-Fi: just run what's on the board
        print("update", e)
