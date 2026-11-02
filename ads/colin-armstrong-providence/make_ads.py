"""Colin Armstrong (Comedy Connection, East Providence RI, Wed Dec 2 2026 7 PM) Meta/Reddit ad images, 4:5, 1:1 and Reddit 1.91:1.
Photo: Avalon's headshot (colin-headshot.jpg). Usage: python3 make_ads.py <fonts_dir> <out_dir>
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, OUT = sys.argv[1], sys.argv[2]
F = lambda n, s: ImageFont.truetype(f"{FONTS}/{n}.ttf", s)
DARK, GOLD, PALE, WHITE = (24, 22, 20), (214, 178, 96), (200, 190, 170), (255, 255, 255)
head = Image.open(os.path.join(HERE, "colin-headshot.jpg")).convert("RGB").crop((60, 90, 920, 1150))


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
    top = int(h * 0.075)
    bg = head.resize((w, int(head.height * w / head.width)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, DARK), 0.6)
    img.paste(bg.crop((0, (bg.height - ph) // 2, w, (bg.height - ph) // 2 + ph)), (0, top))
    s = ph / head.height
    p = head.resize((int(head.width * s), ph), Image.LANCZOS)
    px = (w - p.width) // 2
    img.paste(p, (px, top))
    d = ImageDraw.Draw(img)
    d.rectangle((px - 6, top - 6, px + p.width + 5, top + ph + 5), outline=GOLD, width=6)
    spaced(d, w / 2, int(h * 0.03), kicker, fit(d, kicker, "JosefinSans-Bold", 44, 5, w - 100), GOLD, 5)
    y = top + ph - (40 if tall else 30)
    d.polygon([(0, y + 24), (w, y), (w, y + 150), (0, y + 174)], fill=GOLD)
    spaced(d, w / 2, y + 30, "COLIN ARMSTRONG", fit(d, "COLIN ARMSTRONG", "JosefinSans-Bold", 120, 10, w - 80), DARK, 10)
    y += 200 if tall else 186
    for text, font, col, step in [
        ("EAST PROVIDENCE · WED DEC 2", F("JosefinSans-Bold", 58 if tall else 50), WHITE, 76 if tall else 64),
        ("7 PM · DOORS 6 · 18+", F("JosefinSans-SemiBold", 36 if tall else 32), PALE, 64 if tall else 54),
        ("COMEDY CONNECTION · 39 WARREN AVE", F("JosefinSans-SemiBold", 32 if tall else 28), GOLD, 70 if tall else 0),
    ]:
        spaced(d, w / 2, y, text, fit(d, text, "JosefinSans-Bold" if col == WHITE else "JosefinSans-SemiBold", font.size, 4, w - 90), col, 4)
        y += step
    if tall:
        spaced(d, w / 2, y + 10, "TICKETS $23.99", F("JosefinSans-Bold", 54), WHITE, 6)
    img.save(os.path.join(OUT, name), quality=92)


def wide(kicker, name, w=1200, h=628):
    img = Image.new("RGB", (w, h), DARK)
    p = head.resize((int(head.width * h / head.height), h), Image.LANCZOS)
    img.paste(p, (0, 0))
    d = ImageDraw.Draw(img)
    x0 = p.width + 30
    cx = x0 + (w - x0 - 20) / 2
    mw = w - x0 - 40
    spaced(d, cx, 60, kicker, fit(d, kicker, "JosefinSans-Bold", 34, 3, mw), GOLD, 3)
    d.polygon([(p.width, 150), (w, 135), (w, 265), (p.width, 280)], fill=GOLD)
    spaced(d, cx, 175, "COLIN ARMSTRONG", fit(d, "COLIN ARMSTRONG", "JosefinSans-Bold", 80, 6, mw), DARK, 6)
    y = 320
    for text, size, col in [("WED DEC 2 · 7 PM", 48, WHITE), ("COMEDY CONNECTION", 36, PALE), ("EAST PROVIDENCE, RI", 36, PALE), ("TICKETS $23.99", 44, GOLD)]:
        spaced(d, cx, y, text, fit(d, text, "JosefinSans-Bold", size, 3, mw), col, 3)
        y += size + 30
    img.save(os.path.join(OUT, name), quality=92)


for k, slug in [("COMEDIAN (SORRY)", "sorry"), ("NEW JERSEY'S APOLOGY TO RHODE ISLAND", "jersey"), ("ONE NIGHT ONLY IN RHODE ISLAND", "onenight")]:
    make(1080, 1350, k, f"colin-armstrong-{slug}-4x5.jpg")
    make(1080, 1080, k, f"colin-armstrong-{slug}-1x1.jpg")
    wide(k, f"colin-armstrong-{slug}-reddit.jpg")
