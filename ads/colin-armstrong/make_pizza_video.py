"""Colin Armstrong pizza-joke video ads (4:5, 1080x1350): show info band at the BOTTOM (Colin's ask, Nov 17 2026) in the same
gold-band style as the Providence image ads, the clip (uncut, with its own captions) below.
Usage: python3 make_pizza_video.py <fonts_dir> <clip.mov> <out_dir>  (needs ffmpeg + Pillow)"""
import os, sys, subprocess
from PIL import Image, ImageDraw, ImageFont
FONTS, CLIP, OUT = sys.argv[1:4]
F = lambda n, s: ImageFont.truetype(f"{FONTS}/{n}.ttf", s)
DARK, GOLD, WHITE = (24, 22, 20), (214, 178, 96), (255, 255, 255)
W, H, TOP = 1080, 1350, 300
SCALE, SRC_Y = 1.1, 0            # clip 720x1280 -> 792 wide; captions land ~y 1000-1140, clear of 1:1 crop and Stories UI

def spaced(d, cx, y, t, f, fill, sp):
    ws = [d.textlength(c, font=f) for c in t]; x = cx - (sum(ws) + sp * (len(t) - 1)) / 2
    for c, w in zip(t, ws): d.text((x, y), c, font=f, fill=fill); x += w + sp

def fit(d, t, n, s, sp, mw):
    while s > 20:
        f = F(n, s)
        if sum(d.textlength(c, font=f) for c in t) + sp * (len(t) - 1) <= mw: return f
        s -= 2
    return F(n, s)

SLATE = (74, 108, 134)   # Sisyphus logo blue
TILT = 2.5               # degrees; band and name lean together (Sam, Nov 17 2026: name matches the slope)

def tilted_band(text, font, sp, w, h, fill, ink):
    """A band with its words drawn level, then the whole thing rotated so the text follows the band.
    w=None sizes the band to the words plus padding."""
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = sum(tmp.textlength(c, font=font) for c in text) + sp * (len(text) - 1)
    w = w or int(tw + 44)
    lay = Image.new("RGBA", (w, h), fill + (255,)); d = ImageDraw.Draw(lay)
    asc, desc = font.getmetrics()
    spaced(d, w / 2, (h - asc - desc) / 2 + 4, text, font, ink, sp)
    return lay.rotate(TILT, resample=Image.BICUBIC, expand=True)

def overlay(_, line2, line3, path):
    # bottom strip: name band + date/town kept between y 1035 and 1210 so a 1:1 centre crop
    # (keeps 135-1215) and the Stories bottom bar (covers below ~1250) leave them visible
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.rectangle((0, H - TOP, W, H), fill=DARK + (255,))
    name = tilted_band("COLIN ARMSTRONG", F("JosefinSans-Bold", 72), 8, 1180, 84, GOLD, DARK)
    img.alpha_composite(name, ((W - name.width) // 2, 1100 - name.height // 2))
    d = ImageDraw.Draw(img)
    spaced(d, W / 2, 1166, line2, fit(d, line2, "JosefinSans-Bold", 40, 4, W - 80), WHITE + (255,), 4)
    spaced(d, W / 2, 1252, line3, fit(d, line3, "JosefinSans-Bold", 34, 5, W - 120), GOLD + (255,), 5)
    img.save(path)

for slug, l2, l3 in [("providence", "WED DEC 2 · 7 PM · EAST PROVIDENCE", "COMEDY CONNECTION · TICKETS $23.99"),
                      ("morris-plains", "FRI NOV 20 · 8 PM · MORRIS PLAINS NJ", "THE DOJO OF COMEDY · TICKETS FROM $25")]:
    ov = os.path.join(OUT, f"_ov-{slug}.png"); overlay(None, l2, l3, ov)
    vw = int(720 * SCALE); vh = H - TOP
    fc = (f"[0:v]scale={vw}:-2,crop={vw}:{vh}:0:{int(SRC_Y*SCALE)}[v];"
          f"color=c=0x0b0b12:s={W}x{H}:r=24000/1001[bg];[bg][v]overlay={(W-vw)//2}:0:shortest=1[b];[b][1:v]overlay=0:0[o]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", CLIP, "-i", ov, "-filter_complex", fc, "-map", "[o]", "-map", "0:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", os.path.join(OUT, f"colin-armstrong-pizza-{slug}-4x5.mp4")], check=True)
    os.remove(ov)
