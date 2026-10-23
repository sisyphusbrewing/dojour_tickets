"""Ali Sultan Meta ad images for the added Sat Oct 24 9pm show (the other nights sold out)."""
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

REPO = "/home/user/dojour_tickets/posters"
F = lambda name, size: ImageFont.truetype(f"{REPO}/fonts/{name}.ttf", size)
BLUE, DARK, PALE, WHITE = (74, 107, 138), (40, 39, 40), (160, 185, 210), (255, 255, 255)
photo = Image.open(sys.argv[1]).convert("RGB")
badge = Image.open(f"{REPO}/assets/sisyphus-badge-dark-bg.png").convert("RGBA")
out = sys.argv[2]


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


def make(w, h, kicker, name):
    img = Image.new("RGB", (w, h), DARK)
    photo_h = int(h * (0.50 if h > w else 0.47))
    # crop photo around his face (face centered ~x=0.60, y=0.30 of source)
    sw, sh = photo.size
    scale = max(w / sw, (photo_h + 60) / sh)
    p = photo.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    cx = int(p.width * 0.60 - w / 2)
    cx = max(0, min(cx, p.width - w))
    cy = max(0, min(int(p.height * 0.02), p.height - photo_h - 60))
    img.paste(p.crop((cx, cy, cx + w, cy + photo_h + 60)), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    # darken top for kicker legibility
    for y in range(170):
        d.line([(0, y), (w, y)], fill=(0, 0, 0, int(150 * (1 - y / 170))))
    spaced(d, (64, 48), kicker, F("JosefinSans-Bold", 50), WHITE, 5)
    # tilted blue band
    band_top, band_h, tilt = photo_h - 10, 200, 26
    d.polygon([(0, band_top + tilt), (w, band_top), (w, band_top + band_h), (0, band_top + band_h + tilt)], fill=BLUE)
    d.polygon([(0, band_top + band_h + tilt), (w, band_top + band_h), (w, h), (0, h)], fill=DARK)
    nf = F("JosefinSans-Bold", 128)
    spaced(d, (w / 2, band_top + 48), name, nf, WHITE, 12, anchor="m")
    y = band_top + band_h + tilt + (40 if h > w else 22)
    spaced(d, (w / 2, y), "SATURDAY OCT 24 · 9PM", F("JosefinSans-Bold", 62 if h > w else 54), WHITE, 5, anchor="m")
    y += 92 if h > w else 76
    spaced(d, (w / 2, y), "LATE SHOW · THE REST SOLD OUT", F("JosefinSans-SemiBold", 48 if h > w else 42), PALE, 5, anchor="m")
    y += 82 if h > w else 66
    spaced(d, (w / 2, y), "TICKETS $26", F("JosefinSans-Bold", 66 if h > w else 56), WHITE, 6, anchor="m")
    # footer
    bs = 190 if h > w else 150
    b = badge.resize((bs, int(badge.height * bs / badge.width)), Image.LANCZOS)
    img.paste(b, (w - bs - 50, h - b.height - 40), b)
    fy = h - (120 if h > w else 100)
    spaced(d, (64, fy), "COMEDY CLUB & BREWERY", F("JosefinSans-Bold", 34 if h > w else 30), WHITE, 5)
    spaced(d, (64, fy + 54), "712 ONTARIO AVE W  ·  MINNEAPOLIS", F("JosefinSans-SemiBold", 30 if h > w else 26), PALE, 3)
    return img


for kind, kicker in (("sat9-tickets", "WE ADDED A SHOW."), ("sat9-remarketing", "LAST SEATS. 9PM.")):
    make(1080, 1350, kicker, "ALI SULTAN").save(f"{out}/ali-sultan-{kind}-4x5.jpg", quality=92)
    make(1080, 1080, kicker, "ALI SULTAN").save(f"{out}/ali-sultan-{kind}-1x1.jpg", quality=92)
