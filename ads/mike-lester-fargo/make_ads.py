"""Mike Lester (Comedy in the Cellar, Fargo, Dec 18-19 2026) Meta/Reddit ad images, 4:5 and 1:1.
Photo: Mike cropped from the venue's own flyer (venue-flyer.jpg) since it's his current look.
Usage: python3 make_ads.py <fonts_dir> <out_dir>
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, OUT = sys.argv[1], sys.argv[2]
F = lambda n, s: ImageFont.truetype(f"{FONTS}/{n}.ttf", s)
DARK, GOLD, PALE, WHITE = (24, 22, 20), (214, 178, 96), (200, 190, 170), (255, 255, 255)

flyer = Image.open(os.path.join(HERE, "venue-flyer.jpg")).convert("RGB")
# Mike's head from the flyer, with the flyer's logo bits patched out
fl = flyer.copy()
strip = fl.crop((308, 175, 346, 262)).transpose(Image.FLIP_LEFT_RIGHT)
fl.paste(strip, (618, 175))
fl.paste(fl.getpixel((345, 640)), (300, 590, 326, 670))
head = fl.crop((306, 142, 656, 660))


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
    p = head.resize((int(head.width * s), ph), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 2))
    px = (w - p.width) // 2
    img.paste(p, (px, top))
    d = ImageDraw.Draw(img)
    d.rectangle((px - 6, top - 6, px + p.width + 5, top + ph + 5), outline=GOLD, width=6)
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


for k, slug in [("FORMER EXTERMINATOR. CURRENT COMEDIAN.", "exterminator"), ("FARGO'S FUNNIEST BASEMENT", "basement"), ("BALD. HAS A POMERANIAN. DOING FINE.", "bald")]:
    make(1080, 1350, k, f"mike-lester-{slug}-4x5.jpg")
    make(1080, 1080, k, f"mike-lester-{slug}-1x1.jpg")
