"""Michael Longfellow Meta ad images: 4:5 and 1:1, prospecting and remarketing kickers.

Usage: python3 ads/make_michael_longfellow_ads.py <out_dir>
Photo: official press photo from michaellongfellow.com (ads/michael-longfellow/source-press-photo.jpg).
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "posters")
F = lambda name, size: ImageFont.truetype(f"{REPO}/fonts/{name}.ttf", size)
BLUE, DARK, PALE, WHITE = (74, 107, 138), (40, 39, 40), (160, 185, 210), (255, 255, 255)
photo = Image.open(os.path.join(HERE, "michael-longfellow", "source-press-photo.jpg")).convert("RGB")
badge = Image.open(f"{REPO}/assets/sisyphus-badge-dark-bg.png").convert("RGBA")
out = sys.argv[1]


def spaced(d, xy, text, font, fill, spacing, anchor="l"):
    """Draw letter-spaced text; anchor l/m for left or centered."""
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor == "m":
        x -= total / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w + spacing
    return total


def fit(d, text, name, size, spacing, max_w):
    """Largest font size <= size that keeps the spaced line inside max_w."""
    while size > 20:
        f = F(name, size)
        if sum(d.textlength(ch, font=f) for ch in text) + spacing * (len(text) - 1) <= max_w:
            return f
        size -= 2
    return F(name, size)


def make(w, h, kicker, lines):
    tall = h > w
    img = Image.new("RGB", (w, h), DARK)
    photo_h = int(h * (0.50 if tall else 0.47))
    # crop around his face (face centered ~x=0.40, y=0.27 of source)
    sw, sh = photo.size
    scale = max(w / sw, (photo_h + 60) / sh) * (1.32 if tall else 1.2)
    p = photo.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    cx = max(0, min(int(p.width * 0.41 - w / 2), p.width - w))
    cy = max(0, min(int(p.height * 0.03), p.height - photo_h - 60))
    img.paste(p.crop((cx, cy, cx + w, cy + photo_h + 60)), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(170):
        d.line([(0, y), (w, y)], fill=(0, 0, 0, int(150 * (1 - y / 170))))
    spaced(d, (w / 2, 48), kicker, fit(d, kicker, "JosefinSans-Bold", 50, 5, w - 110), WHITE, 5, anchor="m")
    # tilted blue band, two-line name
    band_top, band_h, tilt = photo_h - 10, 250, 26
    d.polygon([(0, band_top + tilt), (w, band_top), (w, band_top + band_h), (0, band_top + band_h + tilt)], fill=BLUE)
    d.polygon([(0, band_top + band_h + tilt), (w, band_top + band_h), (w, h), (0, h)], fill=DARK)
    nf = F("JosefinSans-Bold", 104)
    spaced(d, (w / 2, band_top + 34), "MICHAEL", nf, WHITE, 12, anchor="m")
    spaced(d, (w / 2, band_top + 140), "LONGFELLOW", nf, WHITE, 12, anchor="m")
    y = band_top + band_h + tilt + (34 if tall else 18)
    big, mid, price = lines
    spaced(d, (w / 2, y), big, fit(d, big, "JosefinSans-Bold", 60 if tall else 52, 5, w - 90), WHITE, 5, anchor="m")
    y += 88 if tall else 70
    spaced(d, (w / 2, y), mid, fit(d, mid, "JosefinSans-SemiBold", 42 if tall else 36, 3, w - 90), PALE, 3, anchor="m")
    y += 76 if tall else 58
    spaced(d, (w / 2, y), price, F("JosefinSans-Bold", 62 if tall else 50), WHITE, 6, anchor="m")
    # footer
    bs = 190 if tall else 140
    b = badge.resize((bs, int(badge.height * bs / badge.width)), Image.LANCZOS)
    img.paste(b, (w - bs - 50, h - b.height - (40 if tall else 26)), b)
    fy = h - (120 if tall else 88)
    spaced(d, (64, fy), "COMEDY CLUB & BREWERY", F("JosefinSans-Bold", 34 if tall else 28), WHITE, 5)
    spaced(d, (64, fy + (54 if tall else 44)), "712 ONTARIO AVE W  ·  MINNEAPOLIS", F("JosefinSans-SemiBold", 30 if tall else 24), PALE, 3)
    return img


TIMES, PRICE = "THU 8 · FRI 7 & 9 · SAT 7 & 9 · SUN 6", "TICKETS $28"
ADS = (
    ("tickets", "THREE SEASONS OF SNL. ONE BREWERY.", "NOV 5–8 · SIX SHOWS"),
    ("remarketing", "STILL THINKING ABOUT IT?", "FROM SNL · NOV 5–8 · SIX SHOWS"),
    ("room", "THESE THREE STILL HAVE ROOM.", "FRI 9PM · SAT 9PM · SUN 6PM"),
)
for kind, kicker, big in ADS:
    times = "FROM SNL · NOV 6, 7 & 8" if kind == "room" else TIMES
    make(1080, 1350, kicker, (big, times, PRICE)).save(f"{out}/michael-longfellow-{kind}-4x5.jpg", quality=92)
    make(1080, 1080, kicker, (big, times, PRICE)).save(f"{out}/michael-longfellow-{kind}-1x1.jpg", quality=92)
