"""The Backpack Tour (Punkie Johnson & Kalea McNeil, Sisyphus, Thu Nov 12 2026 8 PM) Meta ad images, 4:5 and 1:1.
Photos: the two press photos on the Shopify product (shopify-poster.png): top = Kalea McNeil, bottom = Punkie Johnson.
Usage: python3 make_ads.py <fonts_dir>   (writes next to this script)
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = sys.argv[1]
B = lambda s: ImageFont.truetype(f"{FONTS}/JosefinSans-Bold.ttf", s)
BLUE, CHAR, GRAY, WHITE, PALE = (74, 108, 134), (40, 38, 38), (145, 143, 144), (255, 255, 255), (190, 205, 218)
src = Image.open(os.path.join(HERE, "shopify-poster.png")).convert("RGB")
# Portrait crops centred on each face (source px).
punkie = src.crop((370, 1160, 1290, 2290))
kalea = src.crop((420, 15, 1340, 1145))


def spaced(d, cx, y, text, font, fill, sp):
    ws = [d.textlength(c, font=font) for c in text]
    x = cx - (sum(ws) + sp * (len(text) - 1)) / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=font, fill=fill)
        x += w + sp


def fit(d, text, size, sp, max_w):
    while size > 18:
        f = B(size)
        if sum(d.textlength(c, font=f) for c in text) + sp * (len(text) - 1) <= max_w:
            return f
        size -= 2
    return B(size)


def make(w, h, kicker, name):
    """Faces sit in the vertical middle so Meta's wide (1.91:1) and square crops
    of this image still show both faces whole (Sam, Nov 11 2026)."""
    tall = h > w
    img = Image.new("RGB", (w, h), CHAR)
    d = ImageDraw.Draw(img)
    if tall:
        spaced(d, w / 2, 36, kicker, fit(d, kicker, 44, 5, w - 90), PALE, 5)
        y = 110
        d.polygon([(0, y + 24), (w, y), (w, y + 126), (0, y + 150)], fill=BLUE)
        spaced(d, w / 2, y + 38, "THE BACKPACK TOUR", fit(d, "THE BACKPACK TOUR", 96, 8, w - 80), WHITE, 8)
        top, ph = 360, 640
    else:
        top, ph = 40, 600
    pw = w // 2 - 3
    for i, (p, label) in enumerate([(punkie, "PUNKIE JOHNSON · SNL"), (kalea, "KALEA MCNEIL · JUST FOR LAUGHS")]):
        s = max(pw / p.width, ph / p.height)
        r = p.resize((int(p.width * s), int(p.height * s)), Image.LANCZOS)
        r = r.crop(((r.width - pw) // 2, 0, (r.width - pw) // 2 + pw, ph))
        x = i * (w // 2 + 3)
        img.paste(r, (x, top))
        d.rectangle((x, top + ph - 52, x + pw, top + ph), fill=(30, 28, 28))
        spaced(d, x + pw / 2, top + ph - 42, label, fit(d, label, 28, 2, pw - 30), WHITE, 2)
    y = top + ph + 40
    if tall:
        lines = [("THU NOV 12 · 8 PM", 66, WHITE), ("TICKETS $23 · SISYPHUS · MINNEAPOLIS", 34, PALE)]
    else:
        d.polygon([(0, y + 4), (w, y - 16), (w, y + 104), (0, y + 124)], fill=BLUE)
        spaced(d, w / 2, y + 22, "THE BACKPACK TOUR", fit(d, "THE BACKPACK TOUR", 84, 8, w - 80), WHITE, 8)
        y += 160
        lines = [("THU NOV 12 · 8 PM · TICKETS $23", 56, WHITE), ("SISYPHUS · MINNEAPOLIS", 32, PALE)]
    for text, size, col in lines:
        spaced(d, w / 2, y, text, fit(d, text, size, 5, w - 90), col, 5)
        y += size + 34
    img.save(os.path.join(HERE, name), quality=92)


for k, slug in [("FOUR SEASONS OF SNL. ONE NIGHT IN MINNEAPOLIS.", "tickets"), ("YOU LOOKED. THURSDAY IS THE NIGHT.", "remarketing")]:
    make(1080, 1350, k, f"backpack-tour-{slug}-4x5.jpg")
    make(1080, 1080, k, f"backpack-tour-{slug}-1x1.jpg")
