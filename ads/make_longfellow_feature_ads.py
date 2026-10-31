"""Longfellow ads that spotlight the feature, Mike Lester: 4:5 and 1:1.

Usage: python3 ads/make_longfellow_feature_ads.py <out_dir>
Mike's photo is cut from the Fargo venue flyer (his current look).
"""
import os
import sys
from PIL import Image, ImageDraw

out = sys.argv[1]
from make_michael_longfellow_ads import F, BLUE, DARK, PALE, WHITE, photo, badge, spaced, fit  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
flyer = Image.open(os.path.join(HERE, "michael-longfellow", "mike-lester-venue-flyer.jpg")).convert("RGB")
mike = flyer.crop((300, 160, 615, 660))  # Mike's head, square-cornered (he asked for no oval)


def make(w, h, kicker):
    tall = h > w
    img = Image.new("RGB", (w, h), DARK)
    photo_h = int(h * (0.48 if tall else 0.44))
    sw, sh = photo.size
    scale = max(w / sw, (photo_h + 60) / sh) * (1.32 if tall else 1.2)
    p = photo.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    cx = max(0, min(int(p.width * 0.36 - w / 2), p.width - w))
    img.paste(p.crop((cx, 0, cx + w, photo_h + 60)), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(170):
        d.line([(0, y), (w, y)], fill=(0, 0, 0, int(150 * (1 - y / 170))))
    spaced(d, (w / 2, 48), kicker, fit(d, kicker, "JosefinSans-Bold", 50, 5, w - 110), WHITE, 5, anchor="m")
    band_top, band_h, tilt = photo_h - 10, 230, 26
    d.polygon([(0, band_top + tilt), (w, band_top), (w, band_top + band_h), (0, band_top + band_h + tilt)], fill=BLUE)
    d.polygon([(0, band_top + band_h + tilt), (w, band_top + band_h), (w, h), (0, h)], fill=DARK)
    nf = F("JosefinSans-Bold", 92)
    spaced(d, (w / 2, band_top + 30), "MICHAEL", nf, WHITE, 10, anchor="m")
    spaced(d, (w / 2, band_top + 124), "LONGFELLOW", nf, WHITE, 10, anchor="m")
    # Mike cameo, left, with his name beside it
    ch = 300 if tall else 230
    s = ch / mike.height
    m = mike.resize((int(mike.width * s), ch), Image.LANCZOS)
    my = band_top + band_h + tilt + 24
    mx = 64
    img.paste(m, (mx, my))
    d.rectangle((mx - 4, my - 4, mx + m.width + 3, my + m.height + 3), outline=PALE, width=4)
    tx, ty = mx + m.width + 36, my + (30 if tall else 14)
    d.text((tx, ty), "WITH", font=F("JosefinSans-SemiBold", 40 if tall else 32), fill=PALE)
    d.text((tx, ty + (52 if tall else 40)), "MIKE LESTER", font=F("JosefinSans-Bold", 74 if tall else 58), fill=WHITE)
    d.text((tx, ty + (140 if tall else 108)), "NOV 5–8 · SIX SHOWS", font=F("JosefinSans-Bold", 46 if tall else 36), fill=WHITE)
    d.text((tx, ty + (200 if tall else 154)), "TICKETS $28", font=F("JosefinSans-SemiBold", 42 if tall else 32), fill=PALE)
    if tall:
        bs = 170
        b = badge.resize((bs, int(badge.height * bs / badge.width)), Image.LANCZOS)
        img.paste(b, (w - bs - 50, h - b.height - 36), b)
        spaced(d, (64, h - 110), "COMEDY CLUB & BREWERY", F("JosefinSans-Bold", 32), WHITE, 5)
        spaced(d, (64, h - 60), "712 ONTARIO AVE W  ·  MINNEAPOLIS", F("JosefinSans-SemiBold", 28), PALE, 3)
    return img


k = "COME FOR SNL. STAY FOR THE EXTERMINATOR."
make(1080, 1350, k).save(f"{out}/longfellow-mike-lester-4x5.jpg", quality=92)
make(1080, 1080, k).save(f"{out}/longfellow-mike-lester-1x1.jpg", quality=92)
