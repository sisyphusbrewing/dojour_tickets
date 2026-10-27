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
   (`code.py`, `settings.toml`, `lib/`) onto the `CIRCUITPY` drive. The kit is
   in the project files at `av/timer/stage-clock-CIRCUITPY.zip`; to rebuild it,
   take `code.py` and `settings.toml` from here and the libraries with
   `circup install adafruit_matrixportal adafruit_display_text adafruit_requests adafruit_connection_manager`.
4. Open `settings.toml` on the drive and fill in the Wi-Fi name and password.
   The board restarts on save.

It shows `WIFI` while connecting, then the timer: dim gray when stopped, white
while running, red at the light, blinking red with a count-up when over.
