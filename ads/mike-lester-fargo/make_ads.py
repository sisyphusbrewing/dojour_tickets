"""Mike Lester (Comedy in the Cellar, Fargo, Dec 18-19 2026) Meta/Reddit ad images, 4:5 and 1:1.
Photo: Mike cut from the venue's own flyer (venue-flyer.jpg) since it's his current look.
Usage: python3 make_ads.py <fonts_dir> <out_dir>
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, OUT = sys.argv[1], sys.argv[2]
F = lambda n, s: ImageFont.truetype(f"{FONTS}/{n}.ttf", s)
DARK, GOLD, PALE, WHITE = (24, 22, 20), (214, 178, 96), (200, 190, 170), (255, 255, 255)

flyer = Image.open(os.path.join(HERE, "venue-flyer.jpg")).convert("RGB")
head = flyer.crop((250, 140, 700, 660))  # Mike's head, clear of flyer logos inside the ellipse
mask = Image.new("L", head.size, 0)
ImageDraw.Draw(mask).ellipse((72, 14, 392, 556), fill=255)
mask = mask.filter(ImageFilter.GaussianBlur(3))


def spaced(d, cx, y, text, font, fill, sp):
    ws = [d.textlength(c, font=font) for c in text]
    x = cx - (sum(ws) + sp * (len(text) - 1)) / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=font, fill=fill)
        x += w + sp


def fit(d, text, name, size, sp, max_w):
    while size > 20:
        f = F(name, size)
        if sum(d.textlength(c, font=f) for c in text) + sp * (len(text) - 1) <= max_w:
            return f
        size -= 2
    return F(name, size)


def make(w, h, kicker, name):
    tall = h > w
    img = Image.new("RGB", (w, h), DARK)
    ph = int(h * (0.56 if tall else 0.52))
    s = ph / head.height
    p = head.resize((int(head.width * s), ph), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 2))
    m = mask.resize(p.size, Image.LANCZOS)
    px, py = (w - p.width) // 2, int(h * 0.075)
    img.paste(p, (px, py), m)
    d = ImageDraw.Draw(img)
    k = p.width / head.width  # gold cameo ring
    d.ellipse((px + 72 * k - 6, py + 14 * k - 6, px + 392 * k + 6, py + 556 * k + 6), outline=GOLD, width=6)
    spaced(d, w / 2, int(h * 0.03), kicker, fit(d, kicker, "JosefinSans-Bold", 44, 5, w - 100), GOLD, 5)
    y = int(h * 0.075) + ph - (40 if tall else 30)
    d.polygon([(0, y + 24), (w, y), (w, y + 150), (0, y + 174)], fill=GOLD)
    spaced(d, w / 2, y + 30, "MIKE LESTER", fit(d, "MIKE LESTER", "JosefinSans-Bold", 120, 12, w - 80), DARK, 12)
    y += 200 if tall else 186
    for text, font, col, step in [
        ("FARGO · DEC 18 & 19", F("JosefinSans-Bold", 58 if tall else 50), WHITE, 76 if tall else 64),
        ("FRI 8 · SAT 7 & 9:30 · WITH LUIS UZ", F("JosefinSans-SemiBold", 36 if tall else 32), PALE, 64 if tall else 54),
        ("COMEDY IN THE CELLAR · 614 MAIN AVE", F("JosefinSans-SemiBold", 32 if tall else 28), GOLD, 70 if tall else 0),
    ]:
        spaced(d, w / 2, y, text, fit(d, text, "JosefinSans-Bold" if col == WHITE else "JosefinSans-SemiBold", font.size, 4, w - 90), col, 4)
        y += step
    if tall:
        spaced(d, w / 2, y + 10, "TICKETS $25 · 21+", F("JosefinSans-Bold", 54), WHITE, 6)
    img.save(os.path.join(OUT, name), quality=92)


for k, slug in [("FORMER EXTERMINATOR. CURRENT COMEDIAN.", "exterminator"), ("FARGO'S FUNNIEST BASEMENT", "basement")]:
    make(1080, 1350, k, f"mike-lester-{slug}-4x5.jpg")
    make(1080, 1080, k, f"mike-lester-{slug}-1x1.jpg")
