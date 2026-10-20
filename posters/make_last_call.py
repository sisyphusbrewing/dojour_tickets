"""
Last Call - one-off 11 x 17 poster for the Saturday 9 PM showcase (Lucy Beers Shenk & Ryan Kahl).

The show has no live listing to read (it runs most Saturdays), so this draws it by hand in the
make_posters.py house style: host portraits cut from the show's flyer, the slate band, the
"MOST SATURDAYS / 9:00 PM" block, and the usual footer with a QR to the events page.

    python posters/make_last_call.py            # -> posters/one-off/last-call.pdf
"""
import io
import os
import sys

POSTERS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(POSTERS_DIR))
import make_posters as mp
from make_posters import *
from PIL import Image, ImageDraw

FLYER_URL = ("https://cdn.shopify.com/s/files/1/0310/0669/files/"
             "1791306575283_825312086_28248183658211586_5116575842980506433_n.jpg?v=1791314566")
URL = "https://www.sisyphusbrewing.com/collections/comedy-and-events"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(POSTERS_DIR, "one-off", "last-call.pdf")
FLYER = mp.fetch_image(FLYER_URL).convert("RGB")
S = FLYER.width / 1546                    # crop boxes below were measured on a 1546 px wide copy


def portrait(box, center, r, px=1200):
    im = FLYER.crop(tuple(int(v * S) for v in box))
    cx, cy = center
    im = im.crop((cx - r, cy - r, cx + r, cy + r)).resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px * 4, px * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill=255)
    mask = mask.resize((px, px), Image.LANCZOS)
    out = Image.new("RGBA", (px, px)); out.paste(im, (0, 0), mask)
    buf = io.BytesIO(); out.save(buf, "PNG"); buf.seek(0)
    return ImageReader(buf)

register_fonts()
mp.fetch_image = lambda url: FLYER

footer_bottom = STYLE["footer_bottom"] * inch
footer_top = footer_bottom + (STYLE["caption"] + STYLE["tile"]) * inch
prices = [("GENERAL ADMISSION", "$8")]

# dates block: MOST SATURDAYS / 9:00 PM / joke
size = fit_size("MOST SATURDAYS", "JosefinSans-Bold", PAGE_W - 2 * MARGIN, 64, 30, 0.08)
when_size = size * 0.78
gap1, gap2 = size * STYLE["rec_gap1"], size * STYLE["rec_gap2"]
joke = "THE LATE SHOW. FOR PEOPLE WHO WEREN'T READY TO GO HOME."
jsize = fit_size(joke, "JosefinSans-SemiBold", PAGE_W - 2 * MARGIN, 19, 13, 0.1)
block_h = size * CAP + gap1 + when_size * CAP + gap2 + jsize * CAP
band_lines, band_size, band_h = band_layout("Last Call")
band_bottom = max(footer_top + STYLE["gap_footer"] * inch + block_h + STYLE["gap_band"] * inch,
                  STYLE["photo_frac"] * PAGE_H - band_h / 2)
room_top = band_bottom - 0.15 * inch
block_top = max((room_top + footer_top + block_h) / 2, footer_top + STYLE["gap_footer"] * inch + block_h)
photo_bottom = band_bottom + band_h * STYLE["band_overlap"]

c = canvas.Canvas(OUT, pagesize=(PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED))
c.setTitle("Last Call at Sisyphus"); c.setAuthor("Sisyphus"); c.setSubject(URL)
c.setTrimBox([BLEED, BLEED, BLEED + PAGE_W, BLEED + PAGE_H])
c.setBleedBox([0, 0, PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED])
c.translate(BLEED, BLEED)
c.setFillColor(CHARCOAL); c.rect(-BLEED, -BLEED, PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED, stroke=0, fill=1)
pw, ph = PAGE_W + 2 * BLEED, PAGE_H + BLEED - photo_bottom
c.drawImage(texture_panel("x", pw, ph), -BLEED, photo_bottom, pw, ph)

# hero: label, two host portraits, names
top = PAGE_H
label = "A STAND-UP COMEDY SHOWCASE"
lsize = 26
draw_text(c, PAGE_W / 2, top - 1.25 * inch, label, "JosefinSans-SemiBold", lsize, LIGHT_SLATE, lsize * 0.18, align="center")
d = 4.1 * inch
gap = 0.55 * inch
y0 = top - 1.25 * inch - 0.75 * inch - d
x1 = PAGE_W / 2 - gap / 2 - d
x2 = PAGE_W / 2 + gap / 2
for x, box, center in ((x1, (0, 860, 380, 1300), (155, 178)), (x2, (1180, 1080, 1546, 1500), (215, 175))):
    c.setFillColor(WHITE); c.circle(x + d / 2, y0 + d / 2, d / 2 + 6, stroke=0, fill=1)
    c.drawImage(portrait(box, center, 150), x, y0, d, d, mask="auto")
hosted = "HOSTED BY"
draw_text(c, PAGE_W / 2, y0 - 0.65 * inch, hosted, "JosefinSans-SemiBold", 18, GRAY, 4, align="center")
for x, name in ((x1, "LUCY BEERS SHENK"), (x2, "RYAN KAHL")):
    draw_text(c, x + d / 2, y0 - 1.15 * inch, name, "JosefinSans-Bold", 30, WHITE, 2, align="center")

draw_band(c, band_bottom, band_lines, band_size, band_h)
y = block_top - size * CAP
draw_text(c, PAGE_W / 2, y, "MOST SATURDAYS", "JosefinSans-Bold", size, WHITE, size * 0.08, align="center")
y -= gap1 + when_size * CAP
draw_text(c, PAGE_W / 2, y, "9:00 PM", "JosefinSans-SemiBold", when_size, LIGHT_SLATE, size * 0.08, align="center")
y -= gap2 + jsize * CAP
draw_text(c, PAGE_W / 2, y, joke, "JosefinSans-SemiBold", jsize, GRAY, jsize * 0.1, align="center")
draw_footer(c, footer_bottom, URL, prices)
c.showPage(); c.save()
print(f"wrote {OUT}")
