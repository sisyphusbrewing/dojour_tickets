"""Longfellow feature video ad: Mike Lester's teeth clip with a show banner and an end card.

Usage: python3 ads/make_longfellow_feature_video.py <clip.mp4> <out_dir>
Clip: Mike's own vertical stand-up clip (1080x1920) from the "Mike Lester clips for ads" Drive folder.
"""
import os
import subprocess
import sys
from PIL import Image, ImageDraw

from make_michael_longfellow_ads import F, BLUE, DARK, PALE, WHITE, photo, badge, spaced, fit

clip, out = sys.argv[1], sys.argv[2]
W, H = 1080, 1920
os.makedirs(out, exist_ok=True)

# Banner over the top of the clip (his captions sit low, so the top is clear)
bar = Image.new("RGBA", (W, 190), DARK + (235,))
d = ImageDraw.Draw(bar)
spaced(d, (W / 2, 26), "MICHAEL LONGFELLOW", fit(d, "MICHAEL LONGFELLOW", "JosefinSans-Bold", 68, 4, W - 160), WHITE, 4, "m")
spaced(d, (W / 2, 112), "WITH MIKE LESTER · NOV 5–8", fit(d, "WITH MIKE LESTER · NOV 5–8", "JosefinSans-Bold", 46, 3, W - 200), PALE, 3, "m")
bar.save(f"{out}/banner.png")

# End card: Longfellow photo, both names, dates, price, badge
card = Image.new("RGB", (W, H), DARK)
sw, sh = photo.size
s = max(W / sw, 1100 / sh) * 1.25
p = photo.resize((int(sw * s), int(sh * s)), Image.LANCZOS)
cx = max(0, min(int(p.width * 0.36 - W / 2), p.width - W))
card.paste(p.crop((cx, 0, cx + W, 1100)), (0, 0))
d = ImageDraw.Draw(card)
y = 1170
for text, name, size, col, sp in [
    ("COME FOR SNL.", "JosefinSans-Bold", 58, PALE, 3),
    ("STAY FOR THE EXTERMINATOR.", "JosefinSans-Bold", 58, PALE, 3),
    ("MICHAEL LONGFELLOW", "JosefinSans-Bold", 110, WHITE, 4),
    ("WITH MIKE LESTER", "JosefinSans-Bold", 80, WHITE, 4),
    ("THU–SUN · NOV 5–8 · TICKETS $28", "JosefinSans-Bold", 56, PALE, 3),
]:
    f = fit(d, text, name, size, sp, W - 120)
    spaced(d, (W / 2, y), text, f, col, sp, "m")
    y += int(f.size * 1.35)
b = badge.resize((220, int(badge.height * 220 / badge.width)), Image.LANCZOS)
card.paste(b, ((W - b.width) // 2, H - b.height - 60), b)
card.save(f"{out}/endcard.png")

dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip]))
subprocess.run([
    "ffmpeg", "-v", "error", "-y", "-i", clip, "-i", f"{out}/banner.png", "-loop", "1", "-t", "3", "-i", f"{out}/endcard.png",
    "-f", "lavfi", "-t", "3", "-i", "anullsrc=r=48000:cl=stereo",
    "-filter_complex",
    f"[0:v]scale={W}:{H},setsar=1,fps=30[v0];[v0][1:v]overlay=0:0[vb];[2:v]scale={W}:{H},setsar=1,fps=30,fade=in:0:10[ve];"
    f"[0:a]aresample=48000,aformat=channel_layouts=stereo,afade=out:st={dur - 0.6}:d=0.6[a0];"
    "[vb][a0][ve][3:a]concat=n=2:v=1:a=1[v][a]",
    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", f"{out}/longfellow-mike-lester-9x16.mp4",
], check=True)
