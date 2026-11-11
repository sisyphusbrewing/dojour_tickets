# Taproom sign (LED, draws its own pictures)

A 64x32 LED panel in the taproom (or two side by side, 128x32) that shows
pixel art Claude drew from customer suggestions and from the beers on tap.

- **Customers** scan a QR code at the bar to https://staff.sisyphusbrewing.com/sign/ ,
  type what the sign should draw, and see their picture on the spot. Nothing
  goes on the sign until a manager OKs it.
- **Managers** approve, turn down or redraw pictures at
  https://staff.sisyphusbrewing.com/sign/review.html (staff hub tile "Sign
  pictures"). "Draw new beers" gives every beer on tap without a picture its
  own, approved straight away (8 per press).
- **The sign** asks Supabase (`rpc sign_next`) for the next approved picture
  every 15 seconds, least recently shown first, and every 6th turn says
  "DRAW ON THIS SIGN - SCAN THE QR AT THE BAR".

How it works: edge function `sign-art` (supabase/functions/sign-art) calls the
Claude API (claude-opus-5-5) for 32x32 pixel art as 32 rows of 32 characters
(`.` off, 1-9 A-F pick palette colors) plus a caption, and saves it in table
`sign_art` (migration 20261029010000_sign_art.sql). Claude also turns down
suggestions a bar couldn't show. Customer suggestions are capped at 30 an hour.
It needs a Claude API key secret in Supabase (Edge Functions > Secrets), named `ANTHROPIC_CLIENT_API` (or `ANTHROPIC_API_KEY`);
without one the form says the sign isn't set up to draw yet.

## The front bar square (Nov 2026)

Four Adafruit 64x64 3mm panels (4732) in a 2x2 grid, 15" square, 128x128, on
one Matrix Portal S3 (the uFL version, 6475, with the little stick-on antenna).
Add `SIGN_HEIGHT = 128` to `settings.toml` and the same `code.py` switches to
the square layout: the picture big at the top (32x32 art drawn at twice the
size), the caption under it, and for beers the ABV and price from the GoTab
menu feed.

Wiring: the Matrix Portal plugs onto the first panel's INPUT header, and each
panel's OUTPUT ribbon goes to the next panel's INPUT. At power-up the sign shows
1 2 / 3 4 in the four panels for a few seconds; if they're in the wrong places,
`SERPENTINE` and `ROTATION` at the top of `code.py` fix it, and the sign picks
up the change by itself. Adafruit's 64x64 panels use address pin E on 8, which
is the Matrix Portal S3's default (a factory trace, checked on Sam's board Nov 11),
so there's nothing to solder.

Power: one 5V 10A supply through a 2.1mm jack-to-screw-terminal adapter, all
four panel power leads on its + and - terminals; the Matrix Portal runs off its
own USB-C charger. Pictures only cover a quarter of the square, so the sign
draws far less than 10 A, and `POWER_MA` dims any picture that would go over.

## The board

Same hardware as the stage clock (timer/led/README.md): an Adafruit Matrix
Portal S3 on the panel, CircuitPython 10, the same libraries. Copy
`sign/led/boot.py`, `code.py` and `roots.pem` plus `lib/` and a
`settings.toml` with the Wi-Fi onto `CIRCUITPY`. For two panels chained side
by side, add `SIGN_WIDTH = 128` to `settings.toml`.

`boot.py` fetches the latest `code.py` from https://staff.sisyphusbrewing.com/sign/led/
at every power-up or RESET, like the stage clock. It also checks the site every 5 minutes and restarts itself
when there's a new version, so you never have to press RESET. Hold **DOWN** while pressing
**RESET** to copy files over USB.

## Moving the square to a Raspberry Pi (Nov 11 2026)

Live tests with Sam showed the Matrix Portal S3 can't drive four 64x64 panels
without visible flashing: its panel driver refreshes on a timer that Wi-Fi and
drawing knock off for an instant, and the longer the chain the worse it gets
(one panel was clean, the same panel running the four-panel program flashed).
`code.py` now runs the square at colour depth 2 with the Wi-Fi off between
5-minute picture batches, which helps but doesn't cure it. Sam chose to move
the square to a Raspberry Pi (Pi 4 recommended) with the rpi-rgb-led-matrix
library, the usual way to run big LED signs.

`sign/pi/` holds the Pi version: `sign.py` shows the same pictures and layout,
draws each screen off-screen and swaps it in whole, and updates itself from
https://staff.sisyphusbrewing.com/sign/pi/sign.py every 5 minutes. On a fresh
Raspberry Pi OS Lite, `install.sh` sets everything up as a service that starts
at power-up. `SIGN_PREVIEW=out.png python3 sign/pi/sign.py` draws one screen to
a PNG on any computer, to check the layout.

Wiring: either Adafruit's RGB Matrix Bonnet/HAT (`SIGN_WIRING=adafruit-hat`;
64x64 panels need its address E jumper soldered to 8) or the panel cable wired
straight to the Pi's pins (`regular`): panel R1 to Pi pin 23, G1 13, B1 26,
R2 24, G2 21, B2 19, A 15, B 16, C 18, D 22, E 10, CLK 11, LAT 7, OE 12, GND 6.
The panels keep their own 5V supply; the Pi has its own USB-C power.
