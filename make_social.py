"""
Sisyphus - social images for shows.

Makes two phone-sized images for every upcoming show, in the same brand style
as the posters (headshot, tilted slate band, Josefin Sans), from the website:

  * <handle>-feed.jpg   1080 x 1350  (Instagram / Facebook feed, 4:5)
  * <handle>-story.jpg  1080 x 1920  (stories and reels covers, 9:16; the top and
                                      bottom 250 px stay clear for the app's UI
                                      and the link sticker)

    python make_social.py                          # every upcoming show -> social/out/
    python make_social.py michael-longfellow       # only these product handles
    python make_social.py michael-longfellow --kicker "9 PM SHOWS"   # small label over the band
    SOCIAL_OUT=/some/dir python make_social.py

The shared show reading, face finding and cropping come from make_posters.py,
so a show that gets a poster gets social images, and a "poster: fit" /
"poster: cover" tag works here too. Writes manifest.json next to the images.
"""
import argparse
import json
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

import make_posters as mp
from show_dates import CENTRAL_TZ

OUT_DIR = os.environ.get("SOCIAL_OUT") or os.path.join(mp.HERE, "social", "out")
SIZES = {"feed": (1080, 1350), "story": (1080, 1920)}
WHITE = (255, 255, 255)
SLATE = (0x4a, 0x6c, 0x86)
LIGHT_SLATE = (0xa9, 0xc3, 0xd8)
GRAY = (0x91, 0x8f, 0x90)
BADGE = os.path.join(mp.HERE, "posters", "assets", "sisyphus-badge-dark-bg.png")


def font(name, size):
    return ImageFont.truetype(os.path.join(mp.FONT_DIR, f"{name}.ttf"), int(size))


def spaced_width(draw, text, f, spacing):
    return sum(draw.textlength(ch, font=f) for ch in text) + spacing * max(len(text) - 1, 0)


def draw_spaced(draw, cx, y, text, f, fill, spacing, align="center", x=None):
    """Letter-spaced text; y is the top of the caps (Josefin's cap height sits at ~0.70 em)."""
    w = spaced_width(draw, text, f, spacing)
    pos = cx - w / 2 if align == "center" else x
    for ch in text:
        draw.text((pos, y), ch, font=f, fill=fill, anchor="ls")
        pos += draw.textlength(ch, font=f) + spacing
    return w


def fit_font(draw, text, name, max_w, max_size, min_size, spacing_ratio):
    size = max_size
    while size > min_size:
        f = font(name, size)
        if spaced_width(draw, text, f, size * spacing_ratio) <= max_w:
            return f, size
        size -= 2
    return font(name, min_size), min_size


def photo(show, w, h):
    """The headshot filling w x h, cropped around the face (or shown whole over a blur for
    flyers), faded into charcoal at the bottom."""
    src = mp.fetch_image(show["image_url"])
    mode = show["photo_mode"]
    faces = mp.find_faces(src) if mode != "fit" else []
    if faces and mp.crop_window(src, w, h, faces) is None:
        top_face = [min(faces, key=lambda f: f[1])]
        faces = top_face if mp.crop_window(src, w, h, top_face) else []
    if mode == "auto":
        loss = mp.crop_loss(src, w, h)
        mode = "cover" if (faces and loss <= 0.5) or loss <= 0.06 else "fit"
    img = mp.fit_on_blur(src, w, h) if mode == "fit" else mp.cover(src, w, h, faces)
    return mp.fade_bottom(img, int(h * 0.32))


def band(canvas, center_y, title, kicker=None):
    """The tilted slate band from the logo with the show name, drawn across the canvas."""
    W = canvas.size[0]
    probe = ImageDraw.Draw(canvas)
    max_w = W - 120
    lines = [title.upper()]
    f, size = fit_font(probe, lines[0], "JosefinSans-Bold", max_w, 112, 64, 0.06)
    if spaced_width(probe, lines[0], f, size * 0.06) > max_w:
        lines = [l.upper() for l in mp.split_title(title)]
        size = min(fit_font(probe, l, "JosefinSans-Bold", max_w, 84, 34, 0.06)[1] for l in lines)
        f = font("JosefinSans-Bold", size)
    cap = size * mp.CAP
    gap = size * 0.42
    pad = size * 0.42
    band_h = int(2 * pad + cap * len(lines) + gap * (len(lines) - 1))

    layer = Image.new("RGBA", (W + 400, band_h + 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    top = 30
    d.rectangle([0, top, layer.size[0], top + band_h], fill=SLATE + (255,))
    for y in (top - 12, top + band_h + 12):
        d.line([0, y, layer.size[0], y], fill=WHITE + (255,), width=4)
    y = top + pad + cap
    for line in lines:
        draw_spaced(d, layer.size[0] / 2, y, line, f, WHITE, size * 0.06)
        y += cap + gap
    layer = layer.rotate(1.5, resample=Image.BICUBIC, expand=True)
    canvas.paste(layer, (int((W - layer.size[0]) / 2), int(center_y - layer.size[1] / 2)), layer)

    if kicker:
        kf = font("JosefinSans-Bold", 34)
        kd = ImageDraw.Draw(canvas)
        text = kicker.upper()
        tw = spaced_width(kd, text, kf, 34 * 0.12)
        x0, y0 = 60, int(center_y - band_h / 2 - 96)
        kd.rectangle([x0, y0, x0 + tw + 44, y0 + 58], fill=WHITE)
        draw_spaced(kd, 0, y0 + 16 + 34 * mp.CAP, text, kf, mp.CHARCOAL_RGB, 34 * 0.12, align="left", x=x0 + 22)
    return center_y + band_h / 2 + 30


def dates_block(draw, W, top, bottom, dates, max_lines, size=50):
    """"FRI NOV 6 · 7:00 & 9:00 PM" lines between the band and the footer, shrunk to fit."""
    shown = dates[:max_lines]
    more = len(dates) - len(shown)
    rows = len(shown) + (0.7 if more else 0)
    size = int(min(size, (bottom - top) / (rows * 1.45 + 0.2)))
    probe = font(mp.DATE_FONT, size)
    widest = max(spaced_width(draw, f"{day}   ·   {times}", probe, size * 0.04) for day, times in shown)
    if widest > W - 120:                       # long lines ("1ST WEDNESDAY OF THE MONTH") shrink to fit
        size = int(size * (W - 120) / widest)
    f = font(mp.DATE_FONT, size)
    y = top + size * mp.CAP
    for day, times in shown:
        day_w = spaced_width(draw, day, f, size * 0.04)
        time_w = spaced_width(draw, times, f, size * 0.04)
        dot = "   ·   "
        dot_w = draw.textlength(dot, font=f)
        x = (W - (day_w + dot_w + time_w)) / 2
        draw_spaced(draw, 0, y, day, f, WHITE, size * 0.04, align="left", x=x)
        draw.text((x + day_w, y), dot, font=f, fill=GRAY, anchor="ls")
        draw_spaced(draw, 0, y, times, f, LIGHT_SLATE, size * 0.04, align="left", x=x + day_w + dot_w)
        y += size * 1.45
    if more:
        mf = font("JosefinSans-SemiBold", int(size * 0.6))
        draw_spaced(draw, W / 2, y - size * 0.3, f"+ {more} MORE DATE{'S' if more > 1 else ''}", mf, GRAY,
                    size * 0.05)


def footer(canvas, bottom, show):
    """Website and price on one line at the left, the badge on the right."""
    W = canvas.size[0]
    d = ImageDraw.Draw(canvas)
    price = show["prices"][0][1] if show["prices"] else ""
    price = "FREE · RSVP" if price == "FREE" else f"TICKETS {price}" if price else ""
    lf = font("JosefinSans-Bold", 32)
    w = draw_spaced(d, 0, bottom, "SISYPHUSBREWING.COM", lf, WHITE, 32 * 0.06, align="left", x=60)
    if price:
        draw_spaced(d, 0, bottom, "  ·  " + price, lf, LIGHT_SLATE, 32 * 0.06, align="left", x=60 + w)
    badge = Image.open(BADGE).convert("RGBA")
    badge.thumbnail((120, 120))
    canvas.paste(badge, (W - 60 - badge.size[0], int(bottom - badge.size[1] + 28)), badge)


def render(show, kind, path, kicker=None):
    W, H = SIZES[kind]
    canvas = Image.new("RGB", (W, H), mp.CHARCOAL_RGB)
    if kind == "feed":
        photo_h, band_y, max_lines, bottom = 800, 790, 4, H - 60
    else:
        photo_h, band_y, max_lines, bottom = 1150, 1140, 4, H - 300
    canvas.paste(photo(show, W, photo_h), (0, 0))
    below = band(canvas, band_y, show["title"], kicker) + 30
    d = ImageDraw.Draw(canvas)
    dates = show["dates"]
    if show.get("recurring"):                # "EVERY THURSDAY · 8:00 PM", then the next date
        dates = [show["recurring"], ("NEXT UP", dates[0][0])]
    dates_block(d, W, below, bottom - 110, dates, max_lines)
    footer(canvas, bottom, show)
    canvas.save(path, "JPEG", quality=90, optimize=True, progressive=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("handles", nargs="*")
    ap.add_argument("--kicker", help="small label over the band, e.g. '9 PM SHOWS' or 'TONIGHT'")
    args = ap.parse_args()
    wanted = {h.strip().lower() for h in args.handles if h.strip()}
    now = datetime.now(CENTRAL_TZ)
    os.makedirs(OUT_DIR, exist_ok=True)

    shows = [s for s in (mp.build_show(p, now) for p in mp.fetch_collection_products()) if s]
    shows = [s for s in shows if s.get("image_url") and (not wanted or s["handle"] in wanted)]
    shows.sort(key=lambda s: s["first_show"])
    manifest, failures = [], []
    for show in shows:
        files = {}
        try:
            for kind in SIZES:
                name = f"{show['handle']}-{kind}.jpg"
                render(show, kind, os.path.join(OUT_DIR, name), args.kicker)
                files[kind] = name
        except Exception as exc:                       # keep going; report at the end
            failures.append((show["handle"], str(exc)))
            print(f"  FAILED {show['handle']}: {exc}")
            continue
        print(f"  {show['handle']}: {', '.join(files.values())}")
        manifest.append({"handle": show["handle"], "title": show["title"], "url": show["url"],
                         "first_show": show["first_show"].isoformat(), "dates": show["dates"],
                         "prices": show["prices"], "files": files})
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump({"generated_at": now.isoformat(), "shows": manifest}, f, indent=2)
    if failures:
        raise SystemExit(f"{len(failures)} show(s) failed: {failures}")


if __name__ == "__main__":
    main()
