"""James Stanley special taping (Sisyphus, Fri Feb 19 + Sat Feb 20 2027, 7 PM) Meta ad images, 4:5 and 1:1.

Usage: python3 ads/make_james_stanley_ads.py <out_dir>
Photo: press photo from jamesstanleycomedy.com (ads/james-stanley/source-press-photo.jpg).
Call it a special taping, not an album recording (Sam, Nov 6 2026).
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..", "posters")
F = lambda name, size: ImageFont.truetype(f"{REPO}/fonts/{name}.ttf", size)
BLUE, DARK, PALE, WHITE = (74, 107, 138), (40, 39, 40), (160, 185, 210), (255, 255, 255)
photo = Image.open(os.path.join(HERE, "james-stanley", "source-press-photo.jpg")).convert("RGB")
badge = Image.open(f"{REPO}/assets/sisyphus-badge-dark-bg.png").convert("RGBA")


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
    # square photo, face centered around y = 0.40 of the source
    ph = photo_h + 60
    if tall:
        p = photo.resize((w, w), Image.LANCZOS)
        cy = max(0, min(int(w * 0.40 - ph * 0.52), w - ph))
        img.paste(p.crop((0, cy, w, cy + ph)), (0, 0))
    else:
        # square ad: shrink so head-to-mustache fits, soft blurred photo fills the sides
        side = int(ph / 0.70)
        bg = photo.resize((w, w), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
        img.paste(bg.crop((0, 0, w, ph)), (0, 0))
        p = photo.resize((side, side), Image.LANCZOS)
        img.paste(p.crop((0, int(side * 0.02), side, int(side * 0.02) + ph)), ((w - side) // 2, 0))
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(170):
        d.line([(0, y), (w, y)], fill=(0, 0, 0, int(150 * (1 - y / 170))))
    spaced(d, (w / 2, 48), kicker, fit(d, kicker, "JosefinSans-Bold", 50, 5, w - 110), WHITE, 5, anchor="m")
    # tilted blue band, two-line name
    band_top, band_h, tilt = photo_h - 10, 250, 26
    d.polygon([(0, band_top + tilt), (w, band_top), (w, band_top + band_h), (0, band_top + band_h + tilt)], fill=BLUE)
    d.polygon([(0, band_top + band_h + tilt), (w, band_top + band_h), (w, h), (0, h)], fill=DARK)
    nf = F("JosefinSans-Bold", 110)
    spaced(d, (w / 2, band_top + 34), "JAMES", nf, WHITE, 14, anchor="m")
    spaced(d, (w / 2, band_top + 140), "STANLEY", nf, WHITE, 14, anchor="m")
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


if __name__ == "__main__":
    out = sys.argv[1]
    MID, PRICE = "FRI FEB 19 & SAT FEB 20 · 7 PM · 18+", "TICKETS $26"
    ADS = (
        ("tickets", "HE'S TAPING A SPECIAL. YOU'RE THE AUDIENCE.", "LIVE SPECIAL TAPING"),
        ("remarketing", "YOUR LAUGH, ON TAPE. FOREVER.", "LIVE SPECIAL TAPING"),
    )
    for kind, kicker, big in ADS:
        make(1080, 1350, kicker, (big, MID, PRICE)).save(f"{out}/james-stanley-{kind}-4x5.jpg", quality=92)
        make(1080, 1080, kicker, (big, MID, PRICE)).save(f"{out}/james-stanley-{kind}-1x1.jpg", quality=92)
