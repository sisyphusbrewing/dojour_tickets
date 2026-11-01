"""One-page ad report for the Michael Longfellow run (Nov 5-8 2026), for Sam. Letter size, PNG + PDF.

Usage: python3 ads/make_longfellow_report.py <out_base>   (writes <out_base>.png and .pdf)
Numbers are filled in below from Meta (Adspirer), Reddit Ads, Shopify UTM sales and the Supabase tickets table.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "..", "posters")
F = lambda name, size: ImageFont.truetype(f"{P}/fonts/{name}.ttf", size)
BLUE, DARK, PALE, WHITE, GRAY, INK, LINE = (74, 107, 138), (40, 39, 40), (160, 185, 210), (255, 255, 255), (110, 114, 120), (30, 30, 32), (215, 220, 228)

AS_OF = "Nov 1, 2026, 3 PM CT"
SHOWS = [("Thu 8 PM", 27, 23), ("Fri 7 PM", 57, 23), ("Fri 9 PM", 22, 4), ("Sat 7 PM", 56, 33), ("Sat 9 PM", 16, 7), ("Sun 6 PM", 28, 6)]  # website, Dojour
CAP = 90
META = dict(spend=83.73, orders=15, tix=37, sales=1216.72, meta_purch=None)
REDDIT = dict(spend=37.54, impr=2939, clicks=52, tix=0)
SOURCES = [("Google search", 82), ("Facebook/Instagram ads", 37), ("Sisyphus website", 35), ("Direct / typed in", 31),
           ("Other (DDG, Android, Linktree, IG organic)", 21)]

W, H = 1700, 2200
img = Image.new("RGB", (W, H), WHITE)
d = ImageDraw.Draw(img)
M = 110
d.rectangle([0, 0, W, 230], fill=DARK)
d.text((M, 50), "MICHAEL LONGFELLOW · NOV 5–8", font=F("JosefinSans-Bold", 70), fill=WHITE)
d.text((M, 142), f"Ad report  ·  with Mike Lester  ·  as of {AS_OF}", font=F("Assistant-SemiBold", 40), fill=PALE)
badge = Image.open(f"{P}/assets/sisyphus-badge-dark-bg.png").convert("RGBA")
b = badge.resize((170, int(badge.height * 170 / badge.width)), Image.LANCZOS)
img.paste(b, (W - M - 170, (230 - b.height) // 2), b)

web = sum(s[1] for s in SHOWS); dj = sum(s[2] for s in SHOWS); tot = web + dj
ad_spend = META["spend"] + REDDIT["spend"]
y = 290
tiles = [(f"{tot}", f"tickets sold of {CAP * len(SHOWS)}"), (f"${ad_spend:,.0f}", "total ad spend"),
         (f"{META['tix']}", "tickets traced to ads"), (f"{META['sales'] / META['spend']:.1f}x", "Meta return on spend")]
tw = (W - 2 * M - 3 * 40) / 4
for i, (big, small) in enumerate(tiles):
    x = M + i * (tw + 40)
    d.rounded_rectangle([x, y, x + tw, y + 210], 18, fill=(242, 245, 249))
    d.text((x + 30, y + 22), big, font=F("JosefinSans-Bold", 92), fill=BLUE)
    d.text((x + 32, y + 140), small, font=F("Assistant-SemiBold", 32), fill=INK)
y += 260


def h(t):
    global y
    d.text((M, y), t, font=F("JosefinSans-Bold", 44), fill=DARK)
    y += 64
    d.line([(M, y), (W - M, y)], fill=LINE, width=3)
    y += 22


def row(cols, xs, font, fill=INK):
    global y
    for c, x in zip(cols, xs):
        anchor = "ra" if x > M + 400 else "la"
        d.text((x, y), c, font=font, fill=fill, anchor=anchor)
    y += 50


h("Ticket sales by show (website + Dojour)")
xs = [M, M + 700, M + 950, M + 1200, W - M]
row(["Show", "Website", "Dojour", "Total", "Full"], xs, F("Assistant-SemiBold", 34), GRAY)
for name, w_, dj_ in SHOWS:
    t = w_ + dj_
    row([name, str(w_), str(dj_), str(t), f"{round(100 * t / CAP)}%"], xs, F("Assistant-Regular", 36))
row(["All six", str(web), str(dj), str(tot), f"{round(100 * tot / (CAP * len(SHOWS)))}%"], xs, F("Assistant-SemiBold", 36), DARK)
y += 12

h("Ads by channel")
xs = [M, M + 520, M + 800, M + 1080, W - M]
row(["Channel", "Spent", "Tickets", "Sales", "Per ticket"], xs, F("Assistant-SemiBold", 34), GRAY)
row(["Meta (Facebook + IG)", f"${META['spend']:.2f}", str(META["tix"]), f"${META['sales']:,.0f}", f"${META['spend'] / META['tix']:.2f}"], xs, F("Assistant-Regular", 36))
row(["Reddit (test)", f"${REDDIT['spend']:.2f}", "0", "$0", "—"], xs, F("Assistant-Regular", 36))
row(["Total", f"${ad_spend:.2f}", str(META["tix"]), f"${META['sales']:,.0f}", f"${ad_spend / META['tix']:.2f}"], xs, F("Assistant-SemiBold", 36), DARK)
y += 12

h("Where website tickets came from (Shopify)")
for name, n in SOURCES:
    d.text((M, y), name, font=F("Assistant-Regular", 36), fill=INK)
    bw = int((W - 2 * M - 760) * n / SOURCES[0][1])
    d.rounded_rectangle([M + 640, y + 8, M + 640 + bw, y + 40], 8, fill=BLUE if "ads" in name else PALE)
    d.text((M + 660 + bw, y), str(n), font=F("Assistant-SemiBold", 36), fill=INK)
    y += 54
y += 12

h("What to know")
notes = [
    "Meta: three ads to Twin Cities 21+ who like stand-up and SNL, plus a remarketing ad to site visitors",
    "  and past buyers. Every link is tagged, so only sales traced straight to an ad are counted.",
    "Mike Lester photo + video ads went live Nov 1; the \"still have room\" ad is paused.",
    f"Reddit: {REDDIT['impr']:,} views, {REDDIT['clicks']} clicks, no sales; no spend since Oct 31 (~$62 unspent).",
    "Weak spots: Fri 9 and Sat 9 are under a third full; Sun 6 is at 38%. Sat 7 is basically full.",
    "Meta ads end Sun Nov 8, 5:30 PM.",
]
for ln in notes:
    d.text((M, y), ln, font=F("Assistant-Regular", 34), fill=INK)
    y += 50
d.text((M, H - 60), "Sources: Meta Ads (thru Oct 31), Reddit Ads, Shopify UTM orders, Dojour via the tickets table.", font=F("Assistant-Regular", 28), fill=GRAY)
out = sys.argv[1]
img.save(out + ".png")
img.save(out + ".pdf", resolution=200)
