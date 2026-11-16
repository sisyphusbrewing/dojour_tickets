"""Tuesday open mic debut (Sisyphus, Tue Nov 17 2026 7 PM, free) Meta awareness ad images, 4:5 and 1:1.
No photos: plain type in brand colours. Date/time and FREE sit in the centre so every Meta crop
(wide 1.91:1, square, 9:16 stories) keeps them whole (Sam, Nov 11 2026).
Usage: python3 make_ads.py <fonts_dir> <badge_png>
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, BADGE = sys.argv[1], sys.argv[2]
B = lambda s: ImageFont.truetype(f"{FONTS}/JosefinSans-Bold.ttf", s)
BLUE, CHAR, WHITE, PALE = (74, 108, 134), (40, 38, 38), (255, 255, 255), (190, 205, 218)


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


def make(w, h, name):
    img = Image.new("RGB", (w, h), CHAR)
    d = ImageDraw.Draw(img)
    safe = min(int(h * 9 / 16 * 0.92), w - 90)  # stays inside the 9:16 stories crop
    wide = min(int(h * 4 / 5) - 70, w - 90)       # stays inside the 4:5 feed crop
    mid = h // 2
    # Kicker above the band.
    k1, k2 = "SISYPHUS · MINNEAPOLIS", "THE NEW TUESDAY OPEN MIC"
    ky = mid - (330 if h > w else 270)
    spaced(d, w / 2, ky, k1, fit(d, k1, 32, 6, safe), PALE, 6)
    spaced(d, w / 2, ky + 52, k2, fit(d, k2, 52, 5, safe), WHITE, 5)
    # Tilted blue band with the time, centred vertically.
    bh = 300 if h > w else 260
    y0 = mid - bh // 2
    d.polygon([(0, y0 + 30), (w, y0), (w, y0 + bh - 30), (0, y0 + bh)], fill=BLUE)
    t1, t2 = "TUE NOV 17 · 7 PM", "FREE"
    spaced(d, w / 2, y0 + 48, t1, fit(d, t1, 92, 6, safe), WHITE, 6)
    spaced(d, w / 2, y0 + (150 if h > w else 140), t2, fit(d, t2, 110 if h > w else 92, 14, safe), WHITE, 14)
    # Below: the hook.
    y = y0 + bh + (50 if h > w else 30)
    lines = [("NAMES DRAWN FROM A HAT.", 50, WHITE), ("ANYONE COULD GO UP.", 50, WHITE),
             ("COMICS: SIGN UP ONLINE BY 5 PM", 32, PALE)]
    for text, size, col in lines:
        spaced(d, w / 2, y, text, fit(d, text, size, 4, safe), col, 4)
        y += size + 24
    img.save(os.path.join(HERE, name), quality=92)


make(1080, 1350, "open-mic-4x5.jpg")
make(1080, 1080, "open-mic-1x1.jpg")
