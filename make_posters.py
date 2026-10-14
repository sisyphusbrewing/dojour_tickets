"""
Sisyphus - show poster generator.

Makes a print-ready 11 x 17 in poster (tabloid, portrait) for every
upcoming show in the Comedy Tickets & Events collection, straight from the
website: the show's headshot, name, dates and times, price, and a QR code
to its ticket page, in the brand style (charcoal, slate-blue tilted band,
Josefin Sans).

  * 1/8 in bleed on all sides (page is 11.25 x 17.25 in, TrimBox = 11 x 17)
  * the headshot is embedded at 300 dpi for the printed size, so the only
    limit is the source photo on the website (small ones are listed in the log)
  * text, rules and the QR code are vector

It reads the public collection feed, so it needs no Shopify credentials:

    python make_posters.py                     # every upcoming show -> posters/out/
    python make_posters.py sam-jay ali-sultan  # only these product handles
    POSTER_BLEED=0 python make_posters.py      # plain 11 x 17, no bleed
    POSTER_OUT=/some/dir python make_posters.py
    POSTER_FROM=sam-jay python make_posters.py  # skip shows before this one (date order)

Every run also writes print-order.pdf: all the posters it made, in date order,
in one file for a single upload to a print shop.

Skipped on purpose: classes/workshops, and anything whose dates can't be
read (same rules as maintain_shows.py).
"""
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta

import requests
from PIL import Image, ImageFilter
try:
    import cv2                                 # optional: finds faces so the crop keeps them
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 dropped the Haar face detector
        cv2 = None
except ImportError:                            # pragma: no cover
    cv2 = None
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from show_dates import parse_show_datetime, CENTRAL_TZ
from recurring_events import parse_rule

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("POSTER_SITE", "https://www.sisyphusbrewing.com").rstrip("/")
COLLECTION_HANDLE = "comedy-and-events"
OUT_DIR = os.environ.get("POSTER_OUT") or os.path.join(HERE, "posters", "out")
BLEED = float(os.environ.get("POSTER_BLEED", "0.125")) * inch
DPI = 300
GRACE_HOURS = 12                      # a show counts as upcoming until 12 h after it starts
MAX_DATES = 6                         # more than this -> "+ N more dates" line
CLASS_PATTERN = re.compile(r"\b(class|classes|workshop|course)\b", re.IGNORECASE)

PAGE_W, PAGE_H = 11 * inch, 17 * inch

# Brand (from /menu/brand-style-notes.md, sampled from the official logo files)
CHARCOAL = HexColor("#2b2929")
CHARCOAL_RGB = (0x2b, 0x29, 0x29)
SLATE = HexColor("#4a6c86")
GRAY = HexColor("#918f90")
LIGHT_SLATE = HexColor("#a9c3d8")
WHITE = HexColor("#ffffff")
DARK = HexColor("#393636")

FONT_DIR = os.path.join(HERE, "posters", "fonts")
BADGE = os.path.join(HERE, "posters", "assets", "sisyphus-badge-dark-bg.png")
VENUE_LINE = "712 ONTARIO AVE W  ·  MINNEAPOLIS"
TAGLINE = "COMEDY CLUB & BREWERY"

# Layout styles (POSTER_STYLE). "classic" is the original bottom-up layout; "photo" gives the
# headshot about 60 % of the sheet, with a slimmer footer.
STYLES = {
    "classic": dict(photo_frac=None, fit_threshold=0.22, fit_dim=0.45, fade_in=2.1,
                    date_sizes={1: 46, 2: 42, 3: 42, 4: 40}, date_default=34, row_h=1.42,
                    tile=2.0, caption=0.5, footer_bottom=0.6, gap_footer=0.55, gap_band=0.58,
                    band_max=120, band_overlap=0.55, band_line_gap=0.32, band_pad=0.38,
                    rec_gap1=0.42, rec_gap2=0.62, price_gap=0.14),
    "photo": dict(photo_frac=0.40, fit_threshold=0.22, fit_dim=0.7, fade_in=1.6,
                  date_sizes={1: 50, 2: 46, 3: 42, 4: 36}, date_default=32, row_h=1.55,
                  tile=1.45, caption=0.62, footer_bottom=0.5, gap_footer=0.7, gap_band=0.75,
                  band_max=124, band_overlap=0.5, band_line_gap=0.5, band_pad=0.45,
                  rec_gap1=0.62, rec_gap2=0.95, price_gap=0.22),
}
STYLE_NAME = os.environ.get("POSTER_STYLE", "photo").strip().lower() or "photo"
if STYLE_NAME not in STYLES:
    sys.exit(f"POSTER_STYLE must be one of {', '.join(STYLES)}, not {STYLE_NAME!r}")
STYLE = STYLES[STYLE_NAME]


def register_fonts():
    for name in ("JosefinSans-Bold", "JosefinSans-SemiBold", "Assistant-Regular", "Assistant-SemiBold"):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, f"{name}.ttf")))


# ---------------------------------------------------------------------------
# Reading shows from the website
# ---------------------------------------------------------------------------
def fetch_collection_products():
    """Every product in the show collection, from the public storefront feed."""
    products, page = [], 1
    while True:
        resp = requests.get(f"{SITE}/collections/{COLLECTION_HANDLE}/products.json",
                            params={"limit": 250, "page": page}, timeout=30)
        resp.raise_for_status()
        batch = resp.json().get("products", [])
        if not batch:
            return products
        products.extend(batch)
        page += 1


def date_text(product, variant):
    """The showtime part of a variant ("Sat, Oct 17 • 7:00 PM"), not the ticket type."""
    for i, opt in enumerate(product.get("options") or [], start=1):
        if (opt.get("name") or "").strip().lower() in ("date & time", "date", "showtime", "date and time"):
            return variant.get(f"option{i}") or variant["title"]
    return variant["title"].split(" / ")[0]


def ticket_type(product, variant):
    """"General Admission", "VIP / Reserved Seating", ... or "" when there is only a date."""
    date = date_text(product, variant)
    title = variant["title"]
    if title.startswith(date):
        return title[len(date):].strip(" /")
    return ""


def money(amount):
    amount = float(amount)
    if amount <= 0:
        return "FREE"
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def build_show(product, now):
    """Return the poster data for a product, or None if it isn't a datable show."""
    if CLASS_PATTERN.search(product["title"]) or (product.get("product_type") or "").lower() == "class":
        return None
    cutoff = now - timedelta(hours=GRACE_HOURS)
    times, prices = {}, {}
    for v in product.get("variants") or []:
        start = parse_show_datetime(date_text(product, v), now=now, require_time=True)
        if not start or start < cutoff:
            continue
        times.setdefault(start, []).append(v)
        kind = ticket_type(product, v) or "General Admission"
        prices.setdefault(kind, set()).add(float(v["price"]))
    if not times:
        return None

    # One line per day: "THU OCT 15 · 8:00 PM", "FRI NOV 20 · 8:00 & 10:00 PM"
    by_day = {}
    for start in sorted(times):
        by_day.setdefault(start.date(), []).append(start)
    date_lines = []
    for day, starts in sorted(by_day.items()):
        date_lines.append((starts[0].strftime("%a %b %-d").upper(), times_text(starts)))

    price_lines = []
    for kind, amounts in prices.items():
        low, high = min(amounts), max(amounts)
        text = money(low) if low == high else f"{money(low)}–{money(high)}"
        price_lines.append((kind.upper(), text))
    price_lines.sort(key=lambda kp: (kp[0] != "GENERAL ADMISSION", kp[0]))

    tags = [t.strip().lower() for t in product.get("tags") or []]
    photo_mode = "fit" if "poster: fit" in tags or "poster-fit" in tags else \
                 "cover" if "poster: cover" in tags or "poster-cover" in tags else "auto"

    image = (product.get("images") or [{}])[0]
    return {
        "party": party_layout(product["title"], tags),
        "recurring": recurring_label(product.get("tags")),
        "photo_mode": photo_mode,
        "handle": product["handle"],
        "created_at": product.get("created_at"),
        "title": product["title"].strip(),
        "url": f"{SITE}/products/{product['handle']}",
        "first_show": min(times),
        "dates": date_lines,
        "prices": price_lines,
        "image_url": image.get("src"),
        "image_size": (image.get("width"), image.get("height")),
    }


_PARTY = re.compile(r"^\s*((?:release|watch|viewing|listening|premiere)\s+party)\s*[:\-–—]\s*(.+)$",
                    re.IGNORECASE)


def party_layout(title, tags):
    """For a watch party (tagged "Watch Party", or titled "Release Party: ..."): the event kind for
    the band and the special's title for the headline, so the poster never reads as a live show."""
    m = _PARTY.match(title)
    if not m and "watch party" not in tags:
        return None
    kind = m.group(1).upper() if m else "WATCH PARTY"
    rest = m.group(2) if m else title
    parts = [p.strip() for p in re.split(r"\s*[:–—]\s*|\s+-\s+", rest, maxsplit=1) if p.strip()]
    return {"kind": kind, "headline": [p.upper() for p in parts]}


WEEKDAY_NAMES = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
ORDINAL_NAMES = {1: "1ST", 2: "2ND", 3: "3RD", 4: "4TH", -1: "LAST"}


def recurring_label(tags):
    """"EVERY THURSDAY" / "1ST WEDNESDAY OF THE MONTH" from a "recurring: ..." tag, or None."""
    rule = parse_rule(tags)
    if not rule:
        return None
    nth, weekday, hour, minute = rule
    when = datetime(2000, 1, 1, hour, minute).strftime("%-I:%M %p")
    if nth == 0:
        return (f"EVERY {WEEKDAY_NAMES[weekday]}", when)
    return (f"{ORDINAL_NAMES[nth]} {WEEKDAY_NAMES[weekday]} OF THE MONTH", when)


def times_text(starts):
    """["8:00 PM"] -> "8:00 PM";  ["8:00 PM", "10:00 PM"] -> "8:00 & 10:00 PM"."""
    parts = [s.strftime("%-I:%M %p") for s in starts]
    if len(parts) > 1 and len({p[-2:] for p in parts}) == 1:
        suffix = parts[0][-3:]
        return " & ".join(p[:-3] for p in parts) + suffix
    return " & ".join(parts)


# ---------------------------------------------------------------------------
# The headshot
# ---------------------------------------------------------------------------
def fetch_image(url):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        base = Image.new("RGBA", img.size, CHARCOAL_RGB + (255,))
        img = Image.alpha_composite(base, img)
    return img.convert("RGB")


def find_faces(img):
    """Face boxes (left, top, right, bottom) as shares of the image, biggest first; [] without
    OpenCV. Tiny faces, faces in the lower half (cartoons on flyers) and faces much smaller than
    the biggest one (backgrounds, stars) are ignored."""
    if cv2 is None:
        return []
    import numpy as np
    small = img.copy()
    small.thumbnail((800, 800))
    sx, sy = img.size[0] / small.size[0], img.size[1] / small.size[1]
    gray = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY)
    edges = small.convert("L").resize((160, max(1, round(160 * small.size[1] / small.size[0]))))
    edges = edges.filter(ImageFilter.FIND_EDGES)
    if sum(1 for v in edges.getdata() if v > 60) / (edges.size[0] * edges.size[1]) > 0.2:
        return []                              # busy with lettering: a flyer, shown whole
    gray = cv2.equalizeHist(gray)
    boxes = []
    for k, name in enumerate(("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml",
                              "haarcascade_profileface.xml")):
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for x, y, fw, fh in casc.detectMultiScale(gray, 1.08, 4, minSize=(40, 40)):
            l, t = x * sx / img.size[0], y * sy / img.size[1]
            r, b = (x + fw) * sx / img.size[0], (y + fh) * sy / img.size[1]
            if r - l >= 0.06 and t < 0.45:
                boxes.append(((l, t, r, b), k))
    merged = []                                # merge overlapping boxes, biggest first
    for box, k in sorted(boxes, key=lambda b: -(b[0][2] - b[0][0])):
        for i, (m, ks) in enumerate(merged):
            if box[0] < m[2] and box[2] > m[0] and box[1] < m[3] and box[3] > m[1]:
                merged[i] = ((min(box[0], m[0]), min(box[1], m[1]), max(box[2], m[2]), max(box[3], m[3])),
                             ks | {k})
                break
        else:
            merged.append((box, {k}))
    # a real face: two detectors agree, or one finds a big face high in the frame
    merged = [m for m, ks in merged if len(ks) >= 2 or (m[2] - m[0] >= 0.2 and m[1] < 0.4)]
    if merged:
        biggest = merged[0][2] - merged[0][0]
        merged = [b for b in merged if b[2] - b[0] >= 0.45 * biggest]
    return merged


def crop_window(img, w, h, faces=None, focus_y=0.28):
    """The (left, top, right, bottom) source window of a cover crop to the w:h panel, placed so
    the faces keep some headroom, or None when the faces would not fit in one window."""
    sw, sh = img.size
    target = w / h
    if sw / sh > target:                       # too wide: trim the sides
        cw, ch = int(round(sh * target)), sh
        cx = (min(f[0] for f in faces) + max(f[2] for f in faces)) / 2 * sw if faces else sw / 2
        left = int(round(min(max(cx - cw / 2, 0), sw - cw)))
        top = 0
    else:                                      # too tall: keep the part with the face, else the top
        cw, ch = sw, int(round(sw / target))
        left = 0
        if faces:
            face_top = min(f[1] for f in faces) * sh
            top = int(round(min(max(face_top - 0.16 * ch, 0), sh - ch)))
        else:
            top = int(round((sh - ch) * focus_y))
    if faces:
        fl, ft = min(f[0] for f in faces) * sw, min(f[1] for f in faces) * sh
        fr, fb = max(f[2] for f in faces) * sw, max(f[3] for f in faces) * sh
        if fl < left - 1 or fr > left + cw + 1 or ft < top - 1 or fb > top + ch + 1:
            return None
    return left, top, left + cw, top + ch


def cover(img, w, h, faces=None, focus_y=0.28):
    """Crop to the target aspect (around the faces when known, else keeping the upper part) and resize."""
    window = crop_window(img, w, h, faces, focus_y) or crop_window(img, w, h, None, focus_y)
    return img.crop(window).resize((w, h), Image.LANCZOS)


def fit_on_blur(img, w, h):
    """Whole image, centred, over a blurred and darkened copy of itself (for flyers and odd shapes)."""
    bg = cover(img, w, h, focus_y=0.5).filter(ImageFilter.GaussianBlur(w / 25))
    bg = Image.blend(bg, Image.new("RGB", (w, h), CHARCOAL_RGB), STYLE["fit_dim"])
    sw, sh = img.size
    scale = min(w / sw, h / sh)
    fg = img.resize((int(round(sw * scale)), int(round(sh * scale))), Image.LANCZOS)
    bg.paste(fg, ((w - fg.size[0]) // 2, (h - fg.size[1]) // 2))
    return bg


def crop_loss(img, w, h):
    """Share of the image a cover crop would throw away."""
    sw, sh = img.size
    kept = min(sw / sh, w / h) / max(sw / sh, w / h)
    return 1 - kept


def fade_bottom(img, fade_px, power=1.7):
    """Blend the bottom `fade_px` rows into the charcoal background."""
    w, h = img.size
    grad = Image.linear_gradient("L").resize((w, fade_px))          # 0 at top -> 255 at bottom
    grad = grad.point(lambda v: int(255 * (v / 255) ** power))
    mask = Image.new("L", (w, h), 0)
    mask.paste(grad, (0, h - fade_px))
    bg = Image.new("RGB", (w, h), CHARCOAL_RGB)
    return Image.composite(bg, img, mask)


def headshot_panel(url, width_pt, height_pt, mode="auto"):
    """The photo filling the panel, faded into the charcoal at the bottom, as a JPEG ImageReader.

    Headshots are cropped to fill ("cover"), placed around the face when OpenCV finds one, else
    keeping the top. Images with no face that a crop would cut badly - flyers, very tall or wide
    pictures - are shown whole over a blurred copy ("fit"). A "poster: fit" / "poster: cover" tag
    on the product forces either. Returns (image, source size, effective dpi, mode used).
    """
    src = fetch_image(url)
    w = int(round(width_pt / inch * DPI))
    h = int(round(height_pt / inch * DPI))
    faces = find_faces(src) if mode != "fit" else []
    if faces and crop_window(src, w, h, faces) is None:
        top_face = [min(faces, key=lambda f: f[1])]  # keep the highest face (hands, shirts fool it)
        faces = top_face if crop_window(src, w, h, top_face) else []
    if mode == "auto":
        loss = crop_loss(src, w, h)
        mode = "cover" if (faces and loss <= 0.5) or loss <= (STYLE["fit_threshold"] if cv2 is None else 0.06) \
            else "fit"
    if mode == "fit":
        img = fit_on_blur(src, w, h)
        scale = min(w / src.size[0], h / src.size[1])
        effective_dpi = DPI / scale
        fade = 1.1 * inch
    else:
        img = cover(src, w, h, faces)
        left, top, right, bottom = crop_window(src, w, h, faces) or crop_window(src, w, h)
        effective_dpi = (right - left) / (w / DPI)
        fade = STYLE["fade_in"] * inch
    if effective_dpi < 150:                     # heavy upscale: soften the pixel edges a touch
        img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = fade_bottom(img, int(round(fade / inch * DPI)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    buf.seek(0)
    return ImageReader(buf), src.size, effective_dpi, mode


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def text_width(text, font, size, spacing):
    return pdfmetrics.stringWidth(text, font, size) + spacing * max(len(text) - 1, 0)


def draw_text(c, x, y, text, font, size, color, spacing=0.0, align="left"):
    width = text_width(text, font, size, spacing)
    if align == "center":
        x -= width / 2
    elif align == "right":
        x -= width
    t = c.beginText(x, y)
    t.setFont(font, size)
    t.setCharSpace(spacing)
    t.setFillColor(color)
    t.textOut(text)
    c.drawText(t)
    return width


def fit_size(text, font, max_width, max_size, min_size, spacing_ratio):
    """Largest font size (down to min_size) at which the text fits max_width."""
    size = max_size
    while size > min_size and text_width(text, font, size, size * spacing_ratio) > max_width:
        size -= 2
    return size


def split_title(title):
    """Break a long title into two lines of similar width, preferring a natural break
    (after a colon or dash, before "&" / "and") when it is nearly as balanced."""
    words = title.split()
    if len(words) < 2:
        return [title, ""]
    best, best_w = None, None
    natural, natural_w = None, None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        width = max(len(a), len(b))
        if best_w is None or width < best_w:
            best, best_w = (a, b), width
        if words[k - 1][-1] in ":-–" or words[k].lower() in ("&", "and", "-", "–", "with", "w/", "present", "presents"):
            if natural_w is None or width < natural_w:
                natural, natural_w = (a, b), width
    a, b = natural if natural and natural_w <= best_w * 1.3 else best
    a = a.rstrip(" -–")
    b = b.lstrip("-– ").strip()
    return [a, b]


CAP = 0.702                                   # Josefin Sans cap height (share of the font size)
MARGIN = 0.75 * inch
DATE_FONT = "JosefinSans-SemiBold"
DATE_SPACING = 0.04                           # letter spacing, share of the font size


def band_layout(title, font="JosefinSans-Bold"):
    """(lines, font size, band height) for a show name: one big line, or two when it is long."""
    max_w = PAGE_W - 2 * MARGIN
    lines = [title.upper()]
    size = fit_size(lines[0], font, max_w, STYLE["band_max"], 60, 0.06)
    if text_width(lines[0], font, size, size * 0.06) > max_w:
        lines = [l.upper() for l in split_title(title)]
        size = min(fit_size(line, font, max_w, 84, 28, 0.06) for line in lines)
    line_gap = size * STYLE["band_line_gap"]   # space between the two lines' caps
    pad = size * STYLE["band_pad"]             # band padding above and below the caps
    band_h = 2 * pad + size * CAP * len(lines) + line_gap * (len(lines) - 1)
    return lines, size, band_h


def draw_band(c, bottom_y, lines, size, band_h, font="JosefinSans-Bold", angle=-1.5):
    """The tilted slate band from the logo, with the show name in it. Its bottom edge sits at
    bottom_y (at the page centre); a long name wraps to two lines and the band grows upward."""
    spacing = size * 0.06
    line_gap = size * STYLE["band_line_gap"]
    pad = size * STYLE["band_pad"]
    half = PAGE_W / 2 + 1.6 * inch               # long enough to cover the page when tilted

    c.saveState()
    c.translate(PAGE_W / 2, bottom_y + band_h / 2)
    c.rotate(angle)
    c.setFillColor(SLATE)
    c.rect(-half, -band_h / 2, 2 * half, band_h, stroke=0, fill=1)
    c.setStrokeColor(WHITE)
    c.setLineWidth(3)
    gap = 0.11 * inch
    for sign in (1, -1):
        y = sign * (band_h / 2 + gap)
        c.line(-half, y, half, y)
    y = band_h / 2 - pad - size * CAP            # baseline of the first line: caps centred exactly
    for line in lines:
        draw_text(c, 0, y, line, font, size, WHITE, spacing, align="center")
        y -= size * CAP + line_gap
    c.restoreState()


def texture_panel(url, width_pt, height_pt):
    """The listing image blurred beyond recognition and sunk into the charcoal: a backdrop for a
    typographic poster (watch parties), faded at the foot like the headshot panel."""
    src = fetch_image(url)
    w = int(round(width_pt / inch * DPI))
    h = int(round(height_pt / inch * DPI))
    img = cover(src, w, h, focus_y=0.5).filter(ImageFilter.GaussianBlur(w / 12))
    img = Image.blend(Image.new("RGB", (w, h), CHARCOAL_RGB), img, 0.28)
    img = fade_bottom(img, int(round(1.5 * inch / inch * DPI)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    buf.seek(0)
    return ImageReader(buf)


def draw_party_hero(c, bottom_y, party):
    """Big type where the headshot would be: the special's title, framed as a screening."""
    top = PAGE_H
    label = "FREE WATCH PARTY  ·  TAPROOM BIG SCREEN"
    lsize = fit_size(label, "JosefinSans-SemiBold", PAGE_W - 2 * MARGIN, 21, 14, 0.18)
    draw_text(c, PAGE_W / 2, top - 1.15 * inch, label, "JosefinSans-SemiBold", lsize, LIGHT_SLATE,
              lsize * 0.18, align="center")
    lines = party["headline"]
    max_w = PAGE_W - 2 * MARGIN
    sizes = [fit_size(lines[0], "JosefinSans-Bold", max_w, 150, 60, 0.04)]
    for line in lines[1:]:
        sizes.append(fit_size(line, "JosefinSans-Bold", max_w, 104, 48, 0.04))
    sub = "THE NEW SPECIAL, ON RELEASE NIGHT, WITH BEER BREWED RIGHT HERE"
    ssize = fit_size(sub, "JosefinSans-SemiBold", PAGE_W - 2 * MARGIN, 20, 13, 0.14)
    gap = 0.3 * inch
    block = sum(s * CAP for s in sizes) + gap * len(sizes) + ssize * CAP
    y = (top - 1.5 * inch + bottom_y + 0.3 * inch) / 2 + block / 2
    for line, size in zip(lines, sizes):
        y -= size * CAP
        draw_text(c, PAGE_W / 2, y, line, "JosefinSans-Bold", size, WHITE, size * 0.04, align="center")
        y -= gap
    y -= ssize * CAP
    draw_text(c, PAGE_W / 2, y, sub, "JosefinSans-SemiBold", ssize, GRAY, ssize * 0.14, align="center")


def note_block(note, inner):
    """A one-line note in gray above another block. Returns (height, draw)."""
    inner_h, draw_inner = inner
    note_h, gap = 18 * CAP, 0.42 * inch

    def draw(c, top_y):
        draw_text(c, PAGE_W / 2, top_y - note_h, note, "JosefinSans-SemiBold", 18, LIGHT_SLATE, 2.5,
                  align="center")
        draw_inner(c, top_y - note_h - gap)

    return note_h + gap + inner_h, draw


# --- the dates block: measured first, then drawn at a given top ---------------
def _date_table(rows, size):
    """Column widths for an aligned day | · | time table at a font size."""
    sp = size * DATE_SPACING
    day_w = max(text_width(d, DATE_FONT, size, sp) for d, _ in rows)
    time_w = max(text_width(t, DATE_FONT, size, sp) for _, t in rows)
    dot_w = size * 0.9
    return day_w, dot_w, time_w, day_w + dot_w + time_w


def dates_block(dates):
    """Returns (height, draw(c, top_y)) for the list of (day, times) lines.

    One aligned column, or two side by side when that lets the dates print bigger.
    More than six dates: the first six and a "+ N more dates" line. Days are white,
    times light slate, and the day and time columns line up so the eye runs straight down.
    """
    shown = dates[:MAX_DATES]
    extra = len(dates) - len(shown)
    col_gap = 0.6 * inch
    best = None
    for cols in (1, 2):
        if cols == 2 and len(shown) < 4:
            continue
        rows = -(-len(shown) // cols)
        columns = [shown[i * rows:(i + 1) * rows] for i in range(cols)]
        size = STYLE["date_sizes"].get(rows, STYLE["date_default"])
        while size > 18:
            total = sum(_date_table(col, size)[3] for col in columns) + col_gap * (cols - 1)
            if total <= PAGE_W - 2 * MARGIN:
                break
            size -= 1
        if best is None or size > best[0] + 2:
            best = (size, cols, rows, columns)
    size, cols, rows, columns = best
    row_h = size * STYLE["row_h"]
    extra_h = 0.42 * inch if extra else 0
    height = size * CAP + row_h * (rows - 1) + extra_h

    def draw(c, top_y):
        sp = size * DATE_SPACING
        widths = [_date_table(col, size) for col in columns]
        total = sum(w[3] for w in widths) + col_gap * (cols - 1)
        x = (PAGE_W - total) / 2
        for col, (day_w, dot_w, time_w, _) in zip(columns, widths):
            y = top_y - size * CAP
            for day, times in col:
                draw_text(c, x + day_w, y, day, DATE_FONT, size, WHITE, sp, align="right")
                draw_text(c, x + day_w + dot_w / 2, y, "·", DATE_FONT, size, GRAY, 0, align="center")
                draw_text(c, x + day_w + dot_w, y, times, DATE_FONT, size, LIGHT_SLATE, sp)
                y -= row_h
            x += day_w + dot_w + time_w + col_gap
        if extra:
            y = top_y - height + 0.02 * inch
            draw_text(c, PAGE_W / 2, y, f"+ {extra} MORE DATES AT SISYPHUSBREWING.COM",
                      "JosefinSans-SemiBold", 17, GRAY, 2, align="center")

    return height, draw


def recurring_block(label, dates):
    """Returns (height, draw) for "EVERY THURSDAY / 8:00 PM / next up: ..."."""
    headline, when = label
    size = fit_size(headline, "JosefinSans-Bold", PAGE_W - 2 * MARGIN, 52, 30, 0.08)
    when_size = size * 0.78
    gap1, gap2 = size * STYLE["rec_gap1"], size * STYLE["rec_gap2"]
    height = size * CAP + gap1 + when_size * CAP + gap2 + 17 * CAP

    def draw(c, top_y):
        y = top_y - size * CAP
        draw_text(c, PAGE_W / 2, y, headline, "JosefinSans-Bold", size, WHITE, size * 0.08, align="center")
        y -= gap1 + when_size * CAP
        draw_text(c, PAGE_W / 2, y, when, "JosefinSans-SemiBold", when_size, LIGHT_SLATE, size * 0.08,
                  align="center")
        y -= gap2 + 17 * CAP
        nxt = "  ·  ".join(d.split(" ", 1)[1] for d, _ in dates[:5])
        draw_text(c, PAGE_W / 2, y, f"NEXT UP:  {nxt}", "JosefinSans-SemiBold", 17, GRAY, 2, align="center")

    return height, draw


# --- the footer ----------------------------------------------------------------
def draw_qr(c, x, y, size, url):
    """White tile with the QR code (dark modules so phones read it off the charcoal)."""
    pad = size * 0.08
    c.setFillColor(WHITE)
    c.roundRect(x, y, size, size, size * 0.06, stroke=0, fill=1)
    widget = qr.QrCodeWidget(url, barLevel="M", barBorder=0, barFillColor=DARK)
    bx0, by0, bx1, by1 = widget.getBounds()
    inner = size - 2 * pad
    d = Drawing(inner, inner, transform=[inner / (bx1 - bx0), 0, 0, inner / (by1 - by0), 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x + pad, y + pad)


def draw_prices(c, cx, cy, prices):
    """Price block, centred on cy (the middle of the QR tile)."""
    main_kind, main_text = prices[0]
    others = prices[1:]
    big = (80 if len(main_text) <= 4 else 62) * min(1.0, STYLE["tile"] / 1.8)
    label, small = 15, 16
    gap = STYLE["price_gap"] * inch
    total = label * CAP + gap + big * CAP + sum(gap + small * CAP for _ in others)
    y = cy + total / 2 - label * CAP
    top_label = main_kind if len(prices) > 1 else ("ADMISSION" if main_text == "FREE" else "TICKETS")
    draw_text(c, cx, y, top_label, "JosefinSans-SemiBold", label,
              GRAY, 2.5, align="center")
    y -= gap + big * CAP
    draw_text(c, cx, y, main_text, "JosefinSans-Bold", big, WHITE, 0, align="center")
    for kind, text in others:
        y -= gap + small * CAP
        draw_text(c, cx, y, f"{kind}  {text}", "JosefinSans-SemiBold", small, LIGHT_SLATE, 1.5,
                  align="center")


def draw_footer(c, bottom_y, url, prices):
    """QR tile (left), price (middle), badge (right), captions on shared baselines. Returns its top."""
    tile = STYLE["tile"] * inch
    caption_h = STYLE["caption"] * inch
    tile_y = bottom_y + caption_h
    qr_x = MARGIN
    draw_qr(c, qr_x, tile_y, tile, url)
    badge_w = tile * (920 / 875)
    badge_x = PAGE_W - MARGIN - badge_w
    c.drawImage(BADGE, badge_x, tile_y, badge_w, tile, mask="auto")

    free = len(prices) == 1 and prices[0][1] == "FREE"
    scan = "SCAN TO RSVP" if free else "SCAN FOR TICKETS"
    if caption_h >= 0.5 * inch:
        if STYLE_NAME == "classic":
            line1, line2 = bottom_y + 0.24 * inch, bottom_y
            lx, rx, la, ra = qr_x + tile / 2, badge_x + badge_w / 2, "center", "center"
        else:                                 # captions flush with the page margins, clear of the tiles
            line1 = tile_y - 0.3 * inch
            line2 = line1 - 0.26 * inch
            lx, rx, la, ra = qr_x, PAGE_W - MARGIN, "left", "right"
        draw_text(c, lx, line1, scan, "JosefinSans-SemiBold", 14, WHITE, 2.5, align=la)
        draw_text(c, lx, line2, "sisyphusbrewing.com", "Assistant-Regular", 12, GRAY, 0.5, align=la)
        draw_text(c, rx, line1, TAGLINE, "JosefinSans-SemiBold", 14, WHITE, 2.5, align=ra)
        draw_text(c, rx, line2, VENUE_LINE, "Assistant-Regular", 11, GRAY, 1, align=ra)
    else:                                     # slim footer: one caption line under each tile
        line1 = tile_y - 0.22 * inch
        draw_text(c, qr_x + tile / 2, line1, scan, "JosefinSans-SemiBold", 12, WHITE, 2, align="center")
        draw_text(c, badge_x + badge_w / 2, line1, TAGLINE, "JosefinSans-SemiBold", 12, WHITE, 2,
                  align="center")
        draw_text(c, PAGE_W / 2, line1, VENUE_LINE, "Assistant-Regular", 11, GRAY, 1, align="center")

    draw_prices(c, (qr_x + tile + badge_x) / 2, tile_y + tile / 2, prices)
    return tile_y + tile


# ---------------------------------------------------------------------------
# The poster
# ---------------------------------------------------------------------------
def render_poster(show, path):
    """Layout runs from the bottom up: footer, dates, name band, and the photo fills the rest.
    In the "photo" style the band is pinned around 40 % up the sheet (lower only when the dates
    need the room), so the headshot gets the top 60 %."""
    footer_bottom = STYLE["footer_bottom"] * inch
    footer_top = footer_bottom + (STYLE["caption"] + STYLE["tile"]) * inch
    gap_footer = STYLE["gap_footer"] * inch         # footer -> dates
    gap_band = STYLE["gap_band"] * inch             # dates -> band (the tilt adds up to 0.15 in at the edges)

    party = show.get("party")
    if show["recurring"]:
        block_h, draw_block = recurring_block(show["recurring"], show["dates"])
    else:
        block_h, draw_block = dates_block(show["dates"])
    if party:
        block_h, draw_block = note_block("A SCREENING OF THE SPECIAL  ·  NOT A LIVE PERFORMANCE",
                                         (block_h, draw_block))
    band_lines, band_size, band_h = band_layout(party["kind"] if party else show["title"])
    block_top = footer_top + gap_footer + block_h
    band_bottom = block_top + gap_band
    if STYLE["photo_frac"] and not party:
        # pin the band's centre at the style's height unless the dates push it up, then centre
        # the dates in the room between the band and the footer
        band_bottom = max(band_bottom, STYLE["photo_frac"] * PAGE_H - band_h / 2)
        room_top, room_bottom = band_bottom - 0.15 * inch, footer_top
        block_top = max((room_top + room_bottom + block_h) / 2, footer_top + gap_footer + block_h)
    photo_bottom = band_bottom + band_h * STYLE["band_overlap"]   # the band overlaps the faded photo foot

    c = canvas.Canvas(path, pagesize=(PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED))
    c.setTitle(f"{show['title']} at Sisyphus")
    c.setAuthor("Sisyphus")
    c.setSubject(show["url"])
    if BLEED:
        c.setTrimBox([BLEED, BLEED, BLEED + PAGE_W, BLEED + PAGE_H])
        c.setBleedBox([0, 0, PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED])
    c.translate(BLEED, BLEED)

    # Background
    c.setFillColor(CHARCOAL)
    c.rect(-BLEED, -BLEED, PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED, stroke=0, fill=1)

    # Headshot: full width, from the top edge (plus bleed) down into the band
    warnings = []
    photo_w = PAGE_W + 2 * BLEED
    photo_h = PAGE_H + BLEED - photo_bottom
    if party:
        if show["image_url"]:
            c.drawImage(texture_panel(show["image_url"], photo_w, photo_h), -BLEED, photo_bottom,
                        photo_w, photo_h)
        draw_party_hero(c, photo_bottom, party)
        show["photo_mode"] = "texture"
    elif show["image_url"]:
        img, src_size, eff_dpi, mode = headshot_panel(show["image_url"], photo_w, photo_h,
                                                       show["photo_mode"])
        c.drawImage(img, -BLEED, photo_bottom, photo_w, photo_h)
        show["image_dpi"] = round(eff_dpi)
        show["photo_mode"] = mode
        if eff_dpi < 150:
            warnings.append(f"headshot is only {src_size[0]}x{src_size[1]} px "
                            f"(~{eff_dpi:.0f} dpi on the poster) - it will print soft")
    else:
        warnings.append("no image on the product")

    draw_band(c, band_bottom, band_lines, band_size, band_h)
    draw_block(c, block_top)
    draw_footer(c, footer_bottom, show["url"], show["prices"])

    c.showPage()
    c.save()
    return warnings


def main():
    wanted = {h.strip().lower() for h in sys.argv[1:] if h.strip()}
    now = datetime.now(CENTRAL_TZ)
    register_fonts()
    os.makedirs(OUT_DIR, exist_ok=True)

    products = fetch_collection_products()
    shows = [s for s in (build_show(p, now) for p in products) if s]
    shows.sort(key=lambda s: s["first_show"])
    start = os.environ.get("POSTER_FROM", "").strip().lower()
    if start:
        handles = [s["handle"] for s in shows]
        if start not in handles:
            sys.exit(f"POSTER_FROM={start!r} is not an upcoming show. Upcoming: {', '.join(handles)}")
        shows = shows[handles.index(start):]
    if wanted:
        missing = wanted - {s["handle"] for s in shows}
        if missing:
            print(f"Not upcoming shows (skipped): {', '.join(sorted(missing))}")
        shows = [s for s in shows if s["handle"] in wanted]
    print(f"{len(products)} products in the collection, {len(shows)} posters to make -> {OUT_DIR}")

    manifest, failures = [], []
    for show in shows:
        path = os.path.join(OUT_DIR, f"{show['handle']}.pdf")
        try:
            warnings = render_poster(show, path)
        except Exception as exc:                       # keep going; report at the end
            failures.append((show["handle"], str(exc)))
            print(f"  FAILED {show['handle']}: {exc}")
            continue
        dates = "; ".join(f"{d} {t}" for d, t in show["dates"])
        print(f"  {show['handle']}.pdf  {show['title']}  [{dates}]")
        for w in warnings:
            print(f"    warning: {w}")
        manifest.append({"handle": show["handle"], "title": show["title"], "url": show["url"],
                         "created_at": show.get("created_at"),
                         "first_show": show["first_show"].isoformat(), "dates": show["dates"],
                         "prices": show["prices"], "image_url": show["image_url"],
                         "image_dpi": show.get("image_dpi"), "photo_mode": show["photo_mode"],
                         "warnings": warnings,
                         "file": os.path.basename(path)})

    if manifest:
        from pypdf import PdfWriter
        writer = PdfWriter()
        for m in manifest:
            writer.append(os.path.join(OUT_DIR, m["file"]))
        writer.add_metadata({"/Title": "Sisyphus show posters - print order"})
        with open(os.path.join(OUT_DIR, "print-order.pdf"), "wb") as f:
            writer.write(f)
        print(f"  print-order.pdf  {len(manifest)} posters in date order")

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"generated_at": now.isoformat(), "posters": manifest}, f, indent=2)
    with open(os.path.join(OUT_DIR, "RELEASE_NOTES.md"), "w") as f:
        f.write(f"Print-ready 11 x 17 in posters (1/8 in bleed) for every upcoming show, "
                f"regenerated {now.strftime('%b %-d, %Y %-I:%M %p')} Central from sisyphusbrewing.com.\n\n")
        repo = os.environ.get("GITHUB_REPOSITORY")
        if repo:
            f.write(f"**[print-order.pdf](https://github.com/{repo}/releases/download/posters/print-order.pdf)** "
                    f"has all {len(manifest)} posters in one file, in date order, for a single print upload.\n\n")
        for m in manifest:
            flag = "  ⚠️ low-res headshot" if m["warnings"] else ""
            name = f"[{m['title']}](https://github.com/{repo}/releases/download/posters/{m['file']})" \
                if repo else m["title"]
            f.write(f"- **{name}** — {'; '.join(f'{d} {t}' for d, t in m['dates'])}{flag}\n")
    if failures:
        sys.exit(f"{len(failures)} poster(s) failed: {failures}")


if __name__ == "__main__":
    main()
