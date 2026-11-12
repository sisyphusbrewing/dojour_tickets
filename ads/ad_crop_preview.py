"""Ad crop preview: shows how Meta (and Reddit) will crop an ad image in each placement,
so we catch cut-off faces or text BEFORE an ad goes live (Sam, Nov 11 2026, after the
Backpack Tour ad showed one comic's head cut off and the other from the eyes up).

Usage: python3 ad_crop_preview.py <image> [<image> ...] <out.png>
For each image it draws: the full image, a 4:5 feed crop, a 1:1 square crop, a 1.91:1
wide crop (link-style feed, right column, search, Reddit) and a 9:16 Stories/Reels frame.
All crops are centre crops, which is what Meta does when it has no placement-specific image.
Look at every tile. If a face or the date/time is cut in any tile, fix the image first.
"""
import sys
from PIL import Image, ImageDraw, ImageFont

RATIOS = [("full", None), ("4:5 feed", 4 / 5), ("1:1 square", 1.0), ("1.91:1 wide", 1.91), ("9:16 stories", 9 / 16)]
TILE_H = 420


def centre_crop(im, ratio):
    w, h = im.size
    if w / h > ratio:
        nw = int(h * ratio)
        return im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = int(w / ratio)
    return im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def stories(im):
    # Meta letterboxes a non-9:16 feed image on a blurred/solid background in Stories.
    canvas = Image.new("RGB", (1080, 1920), (20, 20, 20))
    s = 1080 / im.width
    r = im.resize((1080, int(im.height * s)))
    canvas.paste(r, (0, (1920 - r.height) // 2))
    # Top ~14% and bottom ~20% are covered by profile name and the CTA in Stories.
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, 1080, 270), outline=(255, 60, 60), width=8)
    d.rectangle((0, 1540, 1080, 1920), outline=(255, 60, 60), width=8)
    return canvas


def tiles(path):
    im = Image.open(path).convert("RGB")
    out = []
    for name, r in RATIOS:
        t = im if r is None else (stories(im) if r == 9 / 16 else centre_crop(im, r))
        t = t.resize((int(t.width * TILE_H / t.height), TILE_H))
        out.append((name, t))
    return out


def main():
    *imgs, out = sys.argv[1:]
    rows = [tiles(p) for p in imgs]
    W = max(sum(t.width + 20 for _, t in row) for row in rows) + 20
    H = len(rows) * (TILE_H + 60) + 20
    sheet = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
    except OSError:
        f = ImageFont.load_default()
    y = 20
    for p, row in zip(imgs, rows):
        x = 20
        for name, t in row:
            d.text((x, y), name, fill=(0, 0, 0), font=f)
            sheet.paste(t, (x, y + 30))
            x += t.width + 20
        y += TILE_H + 60
    sheet.save(out)


if __name__ == "__main__":
    main()
