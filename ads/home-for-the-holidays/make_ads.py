"""Home For The Holidays (Ben Katzner host, Fri Nov 27 + Sat Nov 28 2026, 7 PM) Meta ad images, 4:5 and 1:1.
Photo: Ben's Santa-hat cutout from his own Oct 26 flyer (ben-flyer-oct26.png).
Usage: python3 make_ads.py <fonts_dir> <out_dir>
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, OUT = sys.argv[1], sys.argv[2]
F = lambda n, s: ImageFont.truetype(f"{FONTS}/{n}.ttf", s)
CHAR, SLATE, PALE, WHITE = (30, 32, 36), (74, 108, 134), (196, 204, 212), (255, 255, 255)
flyer = Image.open(os.path.join(HERE, "ben-flyer-oct26.png")).convert("RGB")
ben = flyer.crop((632, 392, 902, 785))  # hat to shoulders; clear of the lineup text, "Hosted by" and the 7PM bubble
_d = ImageDraw.Draw(ben)
_d.rectangle((0, 0, 40, 70), fill=(0, 0, 0))  # hide a flyer ornament in the top-left corner


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
    img = Image.new("RGB", (w, h), CHAR)
    ph = int(h * (0.50 if tall else 0.46))
    top = int(h * (0.14 if tall else 0.12))
    bg = ben.resize((w, int(ben.height * w / ben.width)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    bg = Image.blend(bg, Image.new("RGB", bg.size, CHAR), 0.55)
    img.paste(bg.crop((0, (bg.height - ph) // 2, w, (bg.height - ph) // 2 + ph)), (0, top))
    p = ben.resize((int(ben.width * ph / ben.height), ph), Image.LANCZOS)
    px = (w - p.width) // 2
    img.paste(p, (px, top))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(kicker):
        f = fit(d, line, "JosefinSans-Bold", 46 if tall else 40, 3, w - 170)
        spaced(d, w / 2, int(h * 0.03) + i * (f.size + 14), line, f, WHITE, 3)
    y = top + ph - 30
    d.polygon([(0, y + 26), (w, y), (w, y + 150), (0, y + 176)], fill=SLATE)
    t = "HOME FOR THE HOLIDAYS"
    spaced(d, w / 2, y + 40, t, fit(d, t, "JosefinSans-Bold", 96, 6, w - 170), WHITE, 6)
    y += 200 if tall else 188
    rows = [("HOSTED BY BEN KATZNER", 46 if tall else 40, WHITE),
            ("FRI NOV 27 & SAT NOV 28 · 7 PM", 52 if tall else 44, WHITE),
            ("SISYPHUS COMEDY CLUB · MINNEAPOLIS", 32 if tall else 28, PALE)]
    for text, size, col in rows:
        f = fit(d, text, "JosefinSans-Bold" if col == WHITE else "JosefinSans-SemiBold", size, 3, w - 170)
        spaced(d, w / 2, y, text, f, col, 3)
        y += size + (30 if tall else 20)
    img.save(os.path.join(OUT, name), quality=92)


KICK = ["YOUR PARENTS ASKED CHATGPT TO", "REMOVE YOU FROM THE CHRISTMAS CARD"]
make(1080, 1350, KICK, "hfth-chatgpt-4x5.jpg")
make(1080, 1080, KICK, "hfth-chatgpt-1x1.jpg")
