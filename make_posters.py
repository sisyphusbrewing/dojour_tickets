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


def cover(img, w, h, focus_y=0.28):
    """Crop to the target aspect (keeping the upper part, where faces are) and resize."""
    sw, sh = img.size
    target = w / h
    if sw / sh > target:                       # too wide: trim the sides
        cw = int(round(sh * target))
        left = (sw - cw) // 2
        img = img.crop((left, 0, left + cw, sh))
    else:                                      # too tall: keep the top part
        ch = int(round(sw / target))
        top = int(round((sh - ch) * focus_y))
        img = img.crop((0, top, sw, top + ch))
    return img.resize((w, h), Image.LANCZOS)


def fit_on_blur(img, w, h):
    """Whole image, centred, over a blurred and darkened copy of itself (for flyers and odd shapes)."""
    bg = cover(img, w, h, focus_y=0.5).filter(ImageFilter.GaussianBlur(w / 40))
    bg = Image.blend(bg, Image.new("RGB", (w, h), CHARCOAL_RGB), 0.45)
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

    Headshots are cropped to fill ("cover", keeping the top where the face is). Images that a
    crop would cut badly - flyers, very tall or very wide pictures - are shown whole over a
    blurred copy ("fit"). A "poster: fit" / "poster: cover" tag on the product forces either.
    Returns (image, source size, effective dpi, mode used).
    """
    src = fetch_image(url)
    w = int(round(width_pt / inch * DPI))
    h = int(round(height_pt / inch * DPI))
    if mode == "auto":
        mode = "fit" if crop_loss(src, w, h) > 0.22 else "cover"
    if mode == "fit":
        img = fit_on_blur(src, w, h)
        scale = min(w / src.size[0], h / src.size[1])
        effective_dpi = DPI / scale
        fade = 1.1 * inch
    else:
        img = cover(src, w, h)
        effective_dpi = min(src.size[0] / (w / DPI), src.size[1] / (h / DPI)) \
            if crop_loss(src, w, h) == 0 else \
            (src.size[0] / (w / DPI) if src.size[0] / src.size[1] <= w / h else src.size[1] / (h / DPI))
        fade = 2.1 * inch
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
    """Break a long title into two lines at a natural point."""
    for sep in (": ", " - ", " – ", " & ", " and "):
        if sep in title:
            a, b = title.split(sep, 1)
            if sep == ": ":
                return [a + ":", b]
            if sep in (" - ", " – "):
                return [a, b]
            return [a, sep.strip() + " " + b]
    words = title.split()
    mid = len(words) // 2 + len(words) % 2
    return [" ".join(words[:mid]), " ".join(words[mid:])]


CAP = 0.702                                   # Josefin Sans cap height (share of the font size)
MARGIN = 0.75 * inch
DATE_FONT = "JosefinSans-SemiBold"
DATE_SPACING = 0.04                           # letter spacing, share of the font size


def band_layout(title, font="JosefinSans-Bold"):
    """(lines, font size, band height) for a show name: one big line, or two when it is long."""
    max_w = PAGE_W - 2 * MARGIN
    lines = [title.upper()]
    size = fit_size(lines[0], font, max_w, 120, 60, 0.06)
    if text_width(lines[0], font, size, size * 0.06) > max_w:
        lines = [l.upper() for l in split_title(title)]
        size = min(fit_size(line, font, max_w, 84, 28, 0.06) for line in lines)
    line_gap = size * 0.32                     # space between the two lines' caps
    pad = size * 0.38                          # band padding above and below the caps
    band_h = 2 * pad + size * CAP * len(lines) + line_gap * (len(lines) - 1)
    return lines, size, band_h


def draw_band(c, bottom_y, lines, size, band_h, font="JosefinSans-Bold", angle=-1.5):
    """The tilted slate band from the logo, with the show name in it. Its bottom edge sits at
    bottom_y (at the page centre); a long name wraps to two lines and the band grows upward."""
    spacing = size * 0.06
    line_gap = size * 0.32
    pad = size * 0.38
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
        size = {1: 46, 2: 42, 3: 42, 4: 40}.get(rows, 34)
        while size > 18:
            total = sum(_date_table(col, size)[3] for col in columns) + col_gap * (cols - 1)
            if total <= PAGE_W - 2 * MARGIN:
                break
            size -= 1
        if best is None or size > best[0] + 2:
            best = (size, cols, rows, columns)
    size, cols, rows, columns = best
    row_h = size * 1.42
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
    gap1, gap2 = size * 0.42, size * 0.62
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
    big = 80 if len(main_text) <= 4 else 62
    label, small = 15, 16
    gap = 0.14 * inch
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
    tile = 2.0 * inch
    caption_h = 0.5 * inch
    tile_y = bottom_y + caption_h
    qr_x = MARGIN
    draw_qr(c, qr_x, tile_y, tile, url)
    badge_w = tile * (920 / 875)
    badge_x = PAGE_W - MARGIN - badge_w
    c.drawImage(BADGE, badge_x, tile_y, badge_w, tile, mask="auto")

    line1, line2 = bottom_y + 0.24 * inch, bottom_y
    free = len(prices) == 1 and prices[0][1] == "FREE"
    draw_text(c, qr_x + tile / 2, line1, "SCAN TO RSVP" if free else "SCAN FOR TICKETS",
              "JosefinSans-SemiBold", 14, WHITE, 2.5, align="center")
    draw_text(c, qr_x + tile / 2, line2, "sisyphusbrewing.com", "Assistant-Regular", 12, GRAY, 0.5,
              align="center")
    draw_text(c, badge_x + badge_w / 2, line1, TAGLINE, "JosefinSans-SemiBold", 14, WHITE, 2.5,
              align="center")
    draw_text(c, badge_x + badge_w / 2, line2, VENUE_LINE, "Assistant-Regular", 11, GRAY, 1,
              align="center")

    draw_prices(c, (qr_x + tile + badge_x) / 2, tile_y + tile / 2, prices)
    return tile_y + tile


# ---------------------------------------------------------------------------
# The poster
# ---------------------------------------------------------------------------
def render_poster(show, path):
    """Layout runs from the bottom up: footer, dates, name band, and the photo fills the rest."""
    footer_bottom = 0.6 * inch
    footer_top = footer_bottom + 0.5 * inch + 2.0 * inch
    gap_footer = 0.55 * inch                     # footer -> dates
    gap_band = 0.58 * inch                       # dates -> band (the tilt adds up to 0.15 in at the edges)

    party = show.get("party")
    if show["recurring"]:
        block_h, draw_block = recurring_block(show["recurring"], show["dates"])
    else:
        block_h, draw_block = dates_block(show["dates"])
    if party:
        block_h, draw_block = note_block("A SCREENING OF THE SPECIAL  ·  NOT A LIVE PERFORMANCE",
                                         (block_h, draw_block))
    block_top = footer_top + gap_footer + block_h
    band_bottom = block_top + gap_band
    band_lines, band_size, band_h = band_layout(party["kind"] if party else show["title"])
    photo_bottom = band_bottom + band_h - 0.55 * inch   # the band overlaps the faded photo foot

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
        img, src_size, eff_dpi, mode = headshot_panel(show["image_url"], photo_w, photo_h, show["photo_mode"])
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
