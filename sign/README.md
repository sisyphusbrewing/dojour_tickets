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
It needs an `ANTHROPIC_API_KEY` secret in Supabase (Edge Functions > Secrets);
without one the form says the sign isn't set up to draw yet.

## The board

Same hardware as the stage clock (timer/led/README.md): an Adafruit Matrix
Portal S3 on the panel, CircuitPython 10, the same libraries. Copy
`sign/led/boot.py`, `code.py` and `roots.pem` plus `lib/` and a
`settings.toml` with the Wi-Fi onto `CIRCUITPY`. For two panels chained side
by side, add `SIGN_WIDTH = 128` to `settings.toml`.

`boot.py` fetches the latest `code.py` from https://staff.sisyphusbrewing.com/sign/led/
at every power-up or RESET, like the stage clock. Hold **DOWN** while pressing
**RESET** to copy files over USB.
