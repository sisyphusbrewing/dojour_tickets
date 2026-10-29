# Stage clock (LED)

A red/white LED digital clock that sits on the stage floor facing the comic and
follows the same Stream Deck timer buttons as the timer page.

## Parts (about $70)

- Adafruit Matrix Portal S3 (product 5778)
- 64x32 RGB LED matrix, 4 mm pitch, about 10" x 5" (Adafruit 2278)
- 5 V 4 A USB-C power supply, or any good USB-C charger
- Optional: a small black box or wedge so it tilts up at the comic and the
  audience sees only the back

## Setup (once, about 20 minutes)

1. Press the Matrix Portal onto the panel's **INPUT** header (the arrows on the
   back of the panel point away from it). Screw the panel's red power lead to
   the board's `+5V` post and the black to `GND`.
2. Install CircuitPython 10 for "Adafruit Matrix Portal S3" from
   https://circuitpython.org/board/adafruit_matrixportal_s3/ : plug in USB-C,
   double-click the reset button, drag the .uf2 onto the `MATRIXS3BOOT` drive.
   It reboots as `CIRCUITPY`.
3. Copy everything inside the ready-made kit's `CIRCUITPY` folder
   (`boot.py`, `code.py`, `kevin.py`, `roots.pem`, `settings.toml`, `lib/`) onto the `CIRCUITPY` drive. The kit is
   in the project files at `av/timer/stage-clock-CIRCUITPY.zip`; to rebuild it,
   take `code.py` and `settings.toml` from here and the libraries with
   `circup install adafruit_matrixportal adafruit_display_text adafruit_requests adafruit_connection_manager`.
4. Open `settings.toml` on the drive and fill in the Wi-Fi name and password.
   The board restarts on save.

It shows `WIFI` while connecting, then the timer. The time the comic has done is big on top
and counts up from 0:00; the time left is small underneath ("3:21 LEFT"). Dim gray when
stopped, white while running, red at the light. At 30 seconds left (or when the deck's WRAP IT UP
key is pressed) a bowling ball rolls in and knocks the pins down, then WRAP IT UP flashes, and the
small line keeps flashing WRAP IT UP. Time added to a running set (deck TIME knob) gets a
bowling-alley BONUS TIME burst with the added time. Over time, the small line scrolls "YOU BETTER
KNOW WHAT YOU ARE DOING....", then "NO SERIOUSLY.... ARE YOU FAMOUS?" a minute over, with how far
over in between; the big time keeps counting.

## Updates over Wi-Fi

`boot.py` checks https://staff.sisyphusbrewing.com/timer/led/ every time the
clock is powered up or RESET is pressed, and swaps in a newer `code.py` or
`kevin.py` by itself. Merge the change, wait a couple of minutes for the site to
publish, then press RESET. A file that doesn't download whole or doesn't
compile is skipped, so a bad copy never replaces a good one.

Because the board writes its own files, the computer sees `CIRCUITPY` as
read-only. To copy files over USB (new libraries, Wi-Fi settings), hold
**DOWN** while pressing **RESET**; the drive is writable until the next reset.

Press **UP** for Kevin (`kevin.py`): a pixel guy in a robe with an empty mug
asking for another beer. Press **DOWN** (or UP again) to go back to the timer. Kevin works
even when Wi-Fi doesn't.
