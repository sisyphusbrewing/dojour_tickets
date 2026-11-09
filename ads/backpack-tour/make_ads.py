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
    tall = h > w
    img = Image.new("RGB", (w, h), CHAR)
    d = ImageDraw.Draw(img)
    spaced(d, w / 2, 34, kicker, fit(d, kicker, 46, 5, w - 90), PALE, 5)
    top = 110
    ph = 740 if tall else 560
    pw = w // 2 - 3
    for i, (p, label) in enumerate([(punkie, "PUNKIE JOHNSON · SNL"), (kalea, "KALEA MCNEIL · JUST FOR LAUGHS")]):
        s = max(pw / p.width, ph / p.height)
        r = p.resize((int(p.width * s), int(p.height * s)), Image.LANCZOS)
        r = r.crop(((r.width - pw) // 2, 0, (r.width - pw) // 2 + pw, ph))
        x = i * (w // 2 + 3)
        img.paste(r, (x, top))
        d.rectangle((x, top + ph - 52, x + pw, top + ph), fill=(30, 28, 28))
        spaced(d, x + pw / 2, top + ph - 42, label, fit(d, label, 28, 2, pw - 30), WHITE, 2)
    y = top + ph - 6
    d.polygon([(0, y + 26), (w, y), (w, y + 120), (0, y + 146)], fill=BLUE)
    spaced(d, w / 2, y + 36, "THE BACKPACK TOUR", fit(d, "THE BACKPACK TOUR", 96, 8, w - 80), WHITE, 8)
    y += 180 if tall else 166
    lines = [("THU NOV 12 · 8 PM", 66, WHITE), ("SISYPHUS · 712 ONTARIO AVE W · MINNEAPOLIS", 34, PALE)]
    if tall:
        lines.append(("TICKETS $23", 56, WHITE))
    else:
        lines[1] = ("ONE NIGHT · SISYPHUS · TICKETS $23", 34, PALE)
    for text, size, col in lines:
        spaced(d, w / 2, y, text, fit(d, text, size, 5, w - 90), col, 5)
        y += size + (40 if tall else 30)
    img.save(os.path.join(HERE, name), quality=92)


for k, slug in [("FOUR SEASONS OF SNL. ONE NIGHT IN MINNEAPOLIS.", "tickets"), ("YOU LOOKED. THURSDAY IS THE NIGHT.", "remarketing")]:
    make(1080, 1350, k, f"backpack-tour-{slug}-4x5.jpg")
    make(1080, 1080, k, f"backpack-tour-{slug}-1x1.jpg")
