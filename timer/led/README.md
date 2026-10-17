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

1. Plug the Matrix Portal onto the back of the panel and power it.
2. Install CircuitPython 9 for "Adafruit Matrix Portal S3" from circuitpython.org
   (double-tap reset, drag the .uf2 onto the drive).
3. Install the libraries with circup from a computer with the board plugged in:
   `pip install circup` then
   `circup install adafruit_matrixportal adafruit_display_text adafruit_requests adafruit_connection_manager`
4. Copy `code.py` and `settings.toml` (with the Wi-Fi name and password filled
   in) to `CIRCUITPY/`.

It shows `WIFI` while connecting, then the timer: dim gray when stopped, white
while running, red at the light, blinking red with a count-up when over.
