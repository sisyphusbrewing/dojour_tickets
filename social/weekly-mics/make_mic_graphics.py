"""Weekly free comedy graphics (Sam, Nov 16 2026): Tuesday open mic and Thursday showcase.
Evergreen (no dates), so they work every week. Feed 4:5 (1080x1350, also the Shopify listing image)
and story 9:16 (1080x1920). Brand: charcoal, slate blue tilted band, Josefin Sans.
Usage: python3 make_mic_graphics.py <fonts_dir> <room_photo>
"""
import os, sys, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS, ROOM = sys.argv[1], sys.argv[2]
B = lambda s: ImageFont.truetype(f"{FONTS}/JosefinSans-Bold.ttf", s)
R = lambda s: ImageFont.truetype(f"{FONTS}/Assistant-SemiBold.ttf", s)
BLUE, CHAR, WHITE, PALE, GRAY, PAPER = (74, 108, 134), (40, 38, 38), (255, 255, 255), (190, 205, 218), (150, 148, 148), (236, 230, 216)


def spaced(d, cx, y, text, font, fill, sp):
    ws = [d.textlength(c, font=font) for c in text]
    x = cx - (sum(ws) + sp * (len(text) - 1)) / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=font, fill=fill)
        x += w + sp


def fit(d, text, size, sp, max_w, face=B):
    while size > 16:
        f = face(size)
        if sum(d.textlength(c, font=f) for c in text) + sp * (len(text) - 1) <= max_w:
            return f
        size -= 2
    return face(size)


def band(img, y, h, text, size):
    """Tilted slate band with the text tilted to match (Sam, Nov 3 2026)."""
    w = img.width
    layer = Image.new("RGBA", (w + 400, h + 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 100, w + 400, 100 + h), fill=BLUE)
    f = fit(d, text, size, 10, w - 160)
    spaced(d, (w + 400) / 2, 100 + (h - size) / 2 - size * 0.06, text, f, WHITE, 10)
    layer = layer.rotate(2.2, resample=Image.BICUBIC, expand=False)
    img.paste(layer, (-200, y - 100), layer)


def hat(img, cx, cy, s):
    """A top hat with name slips sticking out: the draw."""
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    for i in range(7):
        x = cx - 110 * s + i * 36 * s + rnd.randint(-6, 6)
        top = cy - 150 * s - rnd.randint(0, 70) * s
        ang = rnd.uniform(-14, 14)
        slip = Image.new("RGBA", (int(46 * s), int(150 * s)), PAPER + (255,))
        sd = ImageDraw.Draw(slip)
        for k in range(3):
            sd.line((8 * s, (22 + 18 * k) * s, (38 - 8 * (k % 2)) * s, (22 + 18 * k) * s), fill=(150, 145, 135), width=max(2, int(3 * s)))
        slip = slip.rotate(ang, expand=True, resample=Image.BICUBIC)
        img.paste(slip, (int(x), int(top)), slip)
    d.rectangle((cx - 150 * s, cy - 60 * s, cx + 150 * s, cy + 150 * s), fill=(22, 21, 21))
    d.rectangle((cx - 150 * s, cy + 70 * s, cx + 150 * s, cy + 112 * s), fill=BLUE)
    d.ellipse((cx - 250 * s, cy + 128 * s, cx + 250 * s, cy + 186 * s), fill=(22, 21, 21))
    d.ellipse((cx - 150 * s, cy - 84 * s, cx + 150 * s, cy - 36 * s), fill=(12, 12, 12))


def tuesday(w, h, name):
    img = Image.new("RGB", (w, h), CHAR)
    d = ImageDraw.Draw(img)
    story = h > 1500
    y = 150 if story else 70
    spaced(d, w / 2, y, "SISYPHUS · MINNEAPOLIS", fit(d, "SISYPHUS · MINNEAPOLIS", 30, 6, w - 200), PALE, 6)
    y += 70
    band(img, y, 150, "TUESDAYS", 104)
    y += 190
    spaced(d, w / 2, y, "OPEN MIC", B(150), WHITE, 10)
    y += 190
    spaced(d, w / 2, y, "7 PM · COMEDY CLUB · FREE", fit(d, "7 PM · COMEDY CLUB · FREE", 60, 6, w - 140), WHITE, 6)
    y += 100 if story else 80
    hy = y + (300 if story else 190)
    hat(img, w // 2, hy, 1.15 if story else 0.75)
    y = hy + (240 if story else 150)
    for text, size, col in [("NAMES DRAWN FROM A HAT.", 50, WHITE), ("ANYONE COULD GO UP.", 50, WHITE)]:
        spaced(d, w / 2, y, text, fit(d, text, size, 4, w - 140), col, 4)
        y += size + 22
    y += 18 if story else 10
    t = "Put your name in and find out what your friends were too nice to tell you."
    f = R(34)
    for line in ["Put your name in and find out what your", "friends were too nice to tell you."]:
        d.text((w / 2, y), line, font=f, fill=GRAY, anchor="ma")
        y += 44
    y = h - (260 if story else 120)
    spaced(d, w / 2, y, "COMICS: SIGN UP BY 6:30 PM", fit(d, "COMICS: SIGN UP BY 6:30 PM", 38, 4, w - 140), PALE, 4)
    spaced(d, w / 2, y + 54, "SISYPHUSBREWING.COM/PAGES/OPEN-MIC", fit(d, "SISYPHUSBREWING.COM/PAGES/OPEN-MIC", 30, 3, w - 140), WHITE, 3)
    img.save(os.path.join(HERE, name), quality=92)


def thursday(w, h, name):
    img = Image.new("RGB", (w, h), CHAR)
    story = h > 1500
    ph = 1000 if story else 560
    room = Image.open(ROOM).convert("RGB")
    s = max(w / room.width, ph / room.height)
    room = room.resize((int(room.width * s), int(room.height * s)), Image.LANCZOS)
    room = room.crop(((room.width - w) // 2, (room.height - ph) // 2, (room.width - w) // 2 + w, (room.height - ph) // 2 + ph))
    room = ImageEnhance.Brightness(room).enhance(0.8)
    top = 0
    img.paste(room, (0, top))
    fade = Image.new("L", (1, 220))
    for i in range(220):
        fade.putpixel((0, i), int(255 * i / 219))
    fade = fade.resize((w, 220))
    img.paste(Image.new("RGB", (w, 220), CHAR), (0, top + ph - 220), fade)
    # Dark fade at the top so the name reads over the photo.
    tf = Image.new("L", (1, 160))
    for i in range(160):
        tf.putpixel((0, i), int(200 * (1 - i / 159)))
    img.paste(Image.new("RGB", (w, 160), (0, 0, 0)), (0, 0), tf.resize((w, 160)))
    d = ImageDraw.Draw(img)
    ty = 150 if story else 40
    if story:
        img.paste(Image.new("RGB", (w, 160), (0, 0, 0)), (0, ty - 60), tf.resize((w, 160)))
        d = ImageDraw.Draw(img)
    spaced(d, w / 2, ty, "SISYPHUS · MINNEAPOLIS", fit(d, "SISYPHUS · MINNEAPOLIS", 30, 6, w - 200), WHITE, 6)
    y = top + ph - 120
    band(img, y, 150, "THURSDAYS", 104)
    y += 190
    spaced(d, w / 2, y, "SHOWCASE", fit(d, "SHOWCASE", 150, 10, w - 120), WHITE, 10)
    y += 190
    spaced(d, w / 2, y, "8 PM · COMEDY CLUB · FREE", fit(d, "8 PM · COMEDY CLUB · FREE", 60, 6, w - 140), WHITE, 6)
    y += 110 if story else 96
    for text, size, col in [("A NEW CURATOR EVERY WEEK", 46, WHITE), ("PICKS THREE COMICS.", 46, WHITE)]:
        spaced(d, w / 2, y, text, fit(d, text, size, 4, w - 140), col, 4)
        y += size + 22
    y += 16
    d.text((w / 2, y), "The comics get paid. You get in free.", font=R(34), fill=GRAY, anchor="ma")
    y = h - (260 if story else 120)
    spaced(d, w / 2, y, "WANT STAGE TIME? SIGN UP AT THE BAR 6–7 PM", fit(d, "WANT STAGE TIME? SIGN UP AT THE BAR 6–7 PM", 38, 4, w - 140), PALE, 4)
    spaced(d, w / 2, y + 54, "FIRST-TIMERS ARE GUARANTEED A SPOT", fit(d, "FIRST-TIMERS ARE GUARANTEED A SPOT", 30, 3, w - 140), WHITE, 3)
    img.save(os.path.join(HERE, name), quality=92)


tuesday(1080, 1350, "tuesday-open-mic-feed.jpg")
tuesday(1080, 1920, "tuesday-open-mic-story.jpg")
thursday(1080, 1350, "thursday-showcase-feed.jpg")
thursday(1080, 1920, "thursday-showcase-story.jpg")
