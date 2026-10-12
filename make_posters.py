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


def band_layout(title, font="JosefinSans-Bold"):
    """(lines, font size, band height) for a show name: one big line, or two when it is long."""
    max_w = PAGE_W - 1.3 * inch
    lines = [title.upper()]
    size = fit_size(lines[0], font, max_w, 120, 60, 0.06)
    if text_width(lines[0], font, size, size * 0.06) > max_w:
        lines = [l.upper() for l in split_title(title)]
        size = min(fit_size(line, font, max_w, 84, 28, 0.06) for line in lines)
    line_h = size * 1.08
    pad = size * 0.42
    band_h = pad * 2 + line_h * len(lines) - size * 0.18
    return lines, size, band_h


def draw_band(c, bottom_y, lines, size, band_h, font="JosefinSans-Bold", angle=-1.5):
    """The tilted slate band from the logo, with the show name in it. Its bottom edge sits at
    bottom_y (at the page centre); a long name wraps to two lines and the band grows upward."""
    spacing = size * 0.06
    line_h = size * 1.08
    pad = size * 0.42
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
    # Josefin Sans caps sit high: nudge so the caps are centred in the band.
    cap = size * 0.70
    y = band_h / 2 - pad - cap
    for line in lines:
        draw_text(c, 0, y, line, font, size, WHITE, spacing, align="center")
        y -= line_h
    c.restoreState()


def draw_recurring(c, top_y, bottom_y, label, dates):
    """"EVERY THURSDAY · 8:00 PM" with the next few dates under it, centred in the block."""
    headline, when = label
    size = fit_size(headline, "JosefinSans-Bold", PAGE_W - 1.5 * inch, 54, 30, 0.08)
    block_h = size * 0.7 + size * 1.25 + size * 1.15 + 17
    y = (top_y + bottom_y) / 2 + block_h / 2 - size * 0.7
    draw_text(c, PAGE_W / 2, y, headline, "JosefinSans-Bold", size, WHITE, size * 0.08, align="center")
    y -= size * 1.25
    draw_text(c, PAGE_W / 2, y, when, "JosefinSans-SemiBold", size * 0.8, LIGHT_SLATE, size * 0.08,
              align="center")
    y -= size * 1.15
    nxt = "  ·  ".join(d.split(" ", 1)[1] for d, _ in dates[:5])
    draw_text(c, PAGE_W / 2, y, f"NEXT UP:  {nxt}", "JosefinSans-SemiBold", 17, GRAY, 2, align="center")


def dates_layout(shown, avail):
    """(columns, rows, font size): one or two columns, whichever lets the dates print biggest."""
    best = None
    for cols in (1, 2):
        rows = -(-len(shown) // cols)
        col_w = (PAGE_W - 1.5 * inch) / cols - 0.3 * inch
        size = 48
        while size > 16:
            widest = max(text_width(f"{d}  ·  {t}", "JosefinSans-SemiBold", size, size * 0.08)
                         for d, t in shown)
            if widest <= col_w and rows * size * 1.45 <= avail:
                break
            size -= 1
        if best is None or size > best[2]:
            best = (cols, rows, size)
    return best


def draw_dates(c, top_y, bottom_y, dates):
    """Date lines, biggest size that fits, in one or two columns."""
    shown = dates[:MAX_DATES]
    extra = len(dates) - len(shown)
    avail = top_y - bottom_y - (0.5 * inch if extra else 0)
    cols, rows, size = dates_layout(shown, avail)
    col_w = (PAGE_W - 1.5 * inch) / cols
    row_h = size * 1.45
    block_h = rows * row_h
    y = top_y - (avail - block_h) / 2 - size * 0.72
    for i, (day, times) in enumerate(shown):
        col, row = divmod(i, rows) if cols == 2 else (0, i)
        cx = 0.75 * inch + col_w * (col + 0.5)
        yy = y - row * row_h
        day_w = text_width(day, "JosefinSans-SemiBold", size, size * 0.08)
        dot_w = text_width("  ·  ", "JosefinSans-SemiBold", size, size * 0.08)
        time_w = text_width(times, "JosefinSans-SemiBold", size, size * 0.08)
        x = cx - (day_w + dot_w + time_w) / 2
        draw_text(c, x, yy, day, "JosefinSans-SemiBold", size, WHITE, size * 0.08)
        draw_text(c, x + day_w, yy, "  ·  ", "JosefinSans-SemiBold", size, GRAY, size * 0.08)
        draw_text(c, x + day_w + dot_w, yy, times, "JosefinSans-SemiBold", size, LIGHT_SLATE, size * 0.08)
    if extra:
        draw_text(c, PAGE_W / 2, y - rows * row_h + size * 0.2,
                  f"+ {extra} MORE DATES AT SISYPHUSBREWING.COM", "JosefinSans-SemiBold", 18, GRAY, 2,
                  align="center")


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


def draw_prices(c, cx, top_y, bottom_y, prices):
    """Price block centred between the QR code and the badge."""
    gap = 0.12 * inch
    main_kind, main_text = prices[0]
    others = prices[1:]
    big = 78 if len(main_text) <= 4 else 60
    label_h, big_h, other_h = 16, big * 0.72, 17
    total = label_h + gap + big_h + sum(other_h + gap for _ in others)
    y = (top_y + bottom_y) / 2 + total / 2
    draw_text(c, cx, y - label_h, "TICKETS" if len(prices) == 1 else main_kind, "JosefinSans-SemiBold", 16,
              GRAY, 2.5, align="center")
    y -= label_h + gap + big_h
    draw_text(c, cx, y, main_text, "JosefinSans-Bold", big, WHITE, 0, align="center")
    for kind, text in others:
        y -= other_h + gap
        draw_text(c, cx, y, f"{kind}  {text}", "JosefinSans-SemiBold", 17, LIGHT_SLATE, 1.5, align="center")


# ---------------------------------------------------------------------------
# The poster
# ---------------------------------------------------------------------------
def render_poster(show, path):
    band_bottom = 6.1 * inch                     # the tilt swings ±0.15 in at the page edges
    band_lines, band_size, band_h = band_layout(show["title"])
    photo_bottom = band_bottom + band_h - 0.55 * inch   # the band overlaps the faded photo foot
    dates_top, dates_bottom = 5.75 * inch, 3.25 * inch
    footer_top, footer_bottom = 2.95 * inch, 0.6 * inch

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

    # Headshot: full width, from the top edge (plus bleed) down to the band
    warnings = []
    photo_w = PAGE_W + 2 * BLEED
    photo_h = PAGE_H + BLEED - photo_bottom
    if show["image_url"]:
        img, src_size, eff_dpi, mode = headshot_panel(show["image_url"], photo_w, photo_h, show["photo_mode"])
        c.drawImage(img, -BLEED, photo_bottom, photo_w, photo_h)
        show["image_dpi"] = round(eff_dpi)
        show["photo_mode"] = mode
        if eff_dpi < 150:
            warnings.append(f"headshot is only {src_size[0]}x{src_size[1]} px "
                            f"(~{eff_dpi:.0f} dpi on the poster) - it will print soft")
    else:
        warnings.append("no image on the product")

    # Name band
    draw_band(c, band_bottom, band_lines, band_size, band_h)

    # Dates
    if show["recurring"]:
        draw_recurring(c, dates_top, dates_bottom, show["recurring"], show["dates"])
    else:
        draw_dates(c, dates_top, dates_bottom, show["dates"])

    # Footer: QR (left), price (middle), badge + address (right)
    qr_size = footer_top - footer_bottom - 0.45 * inch
    qr_x = 0.75 * inch
    draw_qr(c, qr_x, footer_bottom + 0.45 * inch, qr_size, show["url"])
    draw_text(c, qr_x + qr_size / 2, footer_bottom + 0.2 * inch, "SCAN FOR TICKETS", "JosefinSans-SemiBold", 14,
              WHITE, 2.5, align="center")
    draw_text(c, qr_x + qr_size / 2, footer_bottom, "sisyphusbrewing.com", "Assistant-Regular", 12, GRAY,
              0.5, align="center")

    badge_w = 2.3 * inch
    badge_h = badge_w * (875 / 920)
    badge_x = PAGE_W - 0.75 * inch - badge_w
    c.drawImage(BADGE, badge_x, footer_bottom + 0.45 * inch + (qr_size - badge_h) / 2, badge_w, badge_h,
                mask="auto")
    draw_text(c, badge_x + badge_w / 2, footer_bottom + 0.2 * inch, TAGLINE, "JosefinSans-SemiBold", 13,
              WHITE, 2.5, align="center")
    draw_text(c, badge_x + badge_w / 2, footer_bottom, VENUE_LINE, "Assistant-Regular", 11, GRAY, 1,
              align="center")

    draw_prices(c, (qr_x + qr_size + badge_x) / 2, footer_top, footer_bottom, show["prices"])

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

    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"generated_at": now.isoformat(), "posters": manifest}, f, indent=2)
    with open(os.path.join(OUT_DIR, "RELEASE_NOTES.md"), "w") as f:
        f.write(f"Print-ready 11 x 17 in posters (1/8 in bleed) for every upcoming show, "
                f"regenerated {now.strftime('%b %-d, %Y %-I:%M %p')} Central from sisyphusbrewing.com.\n\n")
        repo = os.environ.get("GITHUB_REPOSITORY")
        for m in manifest:
            flag = "  ⚠️ low-res headshot" if m["warnings"] else ""
            name = f"[{m['title']}](https://github.com/{repo}/releases/download/posters/{m['file']})" \
                if repo else m["title"]
            f.write(f"- **{name}** — {'; '.join(f'{d} {t}' for d, t in m['dates'])}{flag}\n")
    if failures:
        sys.exit(f"{len(failures)} poster(s) failed: {failures}")


if __name__ == "__main__":
    main()
