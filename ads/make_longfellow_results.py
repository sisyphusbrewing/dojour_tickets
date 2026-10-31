"""One-page phone image: what the Longfellow Meta ads sold (for showing comics)."""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "..", "posters")
F = lambda name, size: ImageFont.truetype(f"{P}/fonts/{name}.ttf", size)
BLUE, DARK, PALE, WHITE, GRAY = (74, 107, 138), (40, 39, 40), (160, 185, 210), (255, 255, 255), (120, 124, 130)


def spaced(d, xy, text, font, fill, sp, anchor="l"):
    ws = [d.textlength(c, font=font) for c in text]
    tot = sum(ws) + sp * (len(text) - 1)
    x, y = xy
    if anchor == "m":
        x -= tot / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=font, fill=fill)
        x += w + sp


W, H = 1080, 1920
img = Image.new("RGB", (W, H), DARK)
d = ImageDraw.Draw(img)
spaced(d, (W / 2, 70), "WHAT $58 OF FACEBOOK ADS DID", F("JosefinSans-Bold", 46), PALE, 4, "m")
# tilted band with name
top, bh, tilt = 150, 210, 24
d.polygon([(0, top + tilt), (W, top), (W, top + bh), (0, top + bh + tilt)], fill=BLUE)
spaced(d, (W / 2, top + 26), "MICHAEL", F("JosefinSans-Bold", 84), WHITE, 10, "m")
spaced(d, (W / 2, top + 112), "LONGFELLOW", F("JosefinSans-Bold", 84), WHITE, 10, "m")
# ad thumbnail
ad = Image.open(os.path.join(HERE, "michael-longfellow", "michael-longfellow-room-4x5.jpg")).convert("RGB")
tw = 420
ad = ad.resize((tw, int(ad.height * tw / ad.width)), Image.LANCZOS)
ty = 430
img.paste(ad, (70, ty))
d.text((70, ty + ad.height + 14), "One of the ads", font=F("Assistant-Regular", 30), fill=GRAY)
# stats column
x, y = 540, ty - 6
for big, small in (("$58", "spent on ads"), ("28", "tickets sold"), ("$804", "in ticket sales")):
    d.text((x, y), big, font=F("JosefinSans-Bold", 120), fill=WHITE)
    d.text((x + 4, y + 128), small, font=F("Assistant-SemiBold", 38), fill=PALE)
    y += 200
# headline result
y = ty + ad.height + 80
spaced(d, (W / 2, y), "ABOUT 14X BACK", F("JosefinSans-Bold", 96), WHITE, 8, "m")
y += 120
spaced(d, (W / 2, y), "$2 OF ADS PER TICKET", F("JosefinSans-SemiBold", 52), PALE, 5, "m")
# how
y += 100
d.line([(70, y), (W - 70, y)], fill=BLUE, width=4)
y += 40
lines = [
    "Three ads on Facebook and Instagram.",
    "Shown to people near Minneapolis who like stand-up and SNL.",
    "About $13 a day, starting ten days before the shows.",
    "578 visits to the ticket page came from the ads.",
    "Every ad link was tagged, so we only count sales we can trace",
    "straight back to an ad. The real number is probably higher.",
]
for ln in lines:
    d.text((70, y), ln, font=F("Assistant-Regular", 36), fill=WHITE)
    y += 52
y += 30
d.text((70, y), "Fame helps. Telling people the show exists helps more.", font=F("Assistant-SemiBold", 38), fill=PALE)
# footer
badge = Image.open(f"{P}/assets/sisyphus-badge-dark-bg.png").convert("RGBA")
bs = 170
b = badge.resize((bs, int(badge.height * bs / badge.width)), Image.LANCZOS)
img.paste(b, (W - bs - 60, H - b.height - 30), b)
spaced(d, (70, H - 130), "COMEDY CLUB & BREWERY", F("JosefinSans-Bold", 34), WHITE, 5)
spaced(d, (70, H - 80), "NUMBERS FROM SHOPIFY · OCT 26–30, 2026", F("JosefinSans-SemiBold", 26), GRAY, 3)
img.save(sys.argv[1], quality=92)
