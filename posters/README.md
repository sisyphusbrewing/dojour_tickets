# Show posters

`make_posters.py` (in the repo root) turns every upcoming show on
sisyphusbrewing.com into a print-ready **11 x 17 in** poster: the show's
headshot from the website, the name in the tilted slate band, dates and
times, price, and a QR code to the ticket page.

* Page is 11.25 x 17.25 in with a 1/8 in bleed on every side; the PDF carries a
  TrimBox at 11 x 17, so a print shop trims it. For an office printer, print
  with "fit to page" or run with `POSTER_BLEED=0` for a plain 11 x 17.
* The photo is embedded at 300 dpi for its printed size. The only limit is the
  picture on the website: anything under ~150 dpi on the poster is flagged in the
  log and in `manifest.json`. Upload a bigger photo to the product and rerun.
* Headshots are cropped to fill the top of the poster. A picture a crop would
  cut badly (a flyer, a very tall or wide photo) is shown whole over a blurred
  copy instead. Tag the product `poster: fit` or `poster: cover` to force either.
* Recurring shows (tagged `recurring: ...`, see `recurring_events.py`) say
  "EVERY THURSDAY · 8:00 PM" with the next dates under it.
* Classes and workshops are skipped.
* `print-order.pdf` on the release has every poster in one file, in date
  order, for a single upload to a print shop. `POSTER_FROM=<handle>` (or the
  action's "from" box) starts the set at that show.

## Where the posters are

The **Show posters** GitHub Action runs after the daily sync and after a show
is created with the Create Show button, and keeps the current set on the
repo's `posters` release:

    https://github.com/sisyphusbrewing/dojour_tickets/releases/tag/posters

Each file has a stable link, e.g. `.../releases/download/posters/sam-jay.pdf`.
Run the action by hand (Actions > Show posters > Run workflow) to regenerate
now, optionally for just a few product handles.

## Running it locally

    pip install requests pillow reportlab pypdf
    python make_posters.py                      # all upcoming shows -> posters/out/
    python make_posters.py sam-jay ali-sultan   # only these handles
    POSTER_BLEED=0 python make_posters.py       # no bleed

No Shopify credentials are needed; it reads the public collection feed.

`fonts/` holds Josefin Sans and Assistant (SIL Open Font License, see the
OFL files), the same fonts the website uses. `assets/` holds the official badge.
