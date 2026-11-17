"""Makes the printable Green Room sign for the "Say something" page.

Sam, Nov 17 2026: "Let's make some thing for the Green Room where people can
tap or go to a website if they need to report unsafe behavior". The sign has
both: a QR code (opens /safe/?via=qr) and a square spot for an NFC tag (write
https://staff.sisyphusbrewing.com/safe/?via=tag onto the tag with NFC Tools
and stick it in the middle of the squares). Nothing secret is on it.

   python3 safe/make_sign.py <out.pdf>
One letter-size page.
"""
import sys

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

QR_LINK = "https://staff.sisyphusbrewing.com/safe/?via=qr"
SHOWN_LINK = "staff.sisyphusbrewing.com/safe"
FONTS = "/usr/share/fonts/truetype/liberation/"
INK = (0.17, 0.16, 0.16)        # charcoal
SLATE = (0.29, 0.42, 0.53)      # logo slate blue
GRAY = (0.42, 0.42, 0.42)
LIGHT = (0.72, 0.72, 0.72)
RED = (0.71, 0.32, 0.25)
SQUARES = (34 * mm, 44 * mm, 54 * mm)   # real size, so any usual tag covers the middle


def qr(c, x, y, size):
    w = QrCodeWidget(QR_LINK, barLevel="M")
    x0, y0, x1, y1 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def main(out):
    pdfmetrics.registerFont(TTFont("B", FONTS + "LiberationSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("R", FONTS + "LiberationSans-Regular.ttf"))
    W, H = letter
    c = canvas.Canvas(out, pagesize=letter)
    c.setTitle("Say something - Green Room sign")
    cx = W / 2

    # Top band in the slate blue.
    c.setFillColorRGB(*SLATE)
    c.rect(0, H - 120, W, 120, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("B", 60)
    c.drawCentredString(cx, H - 82, "Say something.")

    c.setFillColorRGB(*INK)
    c.setFont("B", 26)
    c.drawCentredString(cx, H - 175, "Someone here make you feel unsafe?")
    c.setFont("R", 21)
    c.drawCentredString(cx, H - 210, "Cross a line with you, or with someone else?")
    c.drawCentredString(cx, H - 240, "Tell us. You don't have to give your name.")

    # Two ways in, side by side: the QR code and the tag.
    row_top = H - 265
    col_l, col_r = W * 0.29, W * 0.71
    qsize = 175
    c.setFont("B", 20)
    c.drawCentredString(col_l, row_top - 20, "Scan this")
    c.drawCentredString(col_r, row_top - 20, "or hold your phone here")
    box_mid = row_top - 40 - qsize / 2
    qr(c, col_l - qsize / 2, box_mid - qsize / 2, qsize)

    c.setLineWidth(1.6)
    for side, ink in zip(SQUARES, (LIGHT, GRAY, INK)):
        c.setStrokeColorRGB(*ink)
        c.roundRect(col_r - side / 2, box_mid - side / 2, side, side, 3 * mm, stroke=1, fill=0)
    c.setFillColorRGB(*LIGHT)
    c.setFont("R", 8)
    c.drawCentredString(col_r, box_mid - 3, "tag goes in the middle")
    c.setFillColorRGB(*GRAY)
    c.setFont("R", 13)
    c.drawCentredString(col_r, box_mid - SQUARES[-1] / 2 - 22, "iPhone: top of the phone. Android: the back.")

    y = box_mid - qsize / 2 - 40
    c.setFillColorRGB(*INK)
    c.setFont("R", 17)
    c.drawCentredString(cx, y, "Or go to")
    c.setFont("B", 24)
    c.drawCentredString(cx, y - 30, SHOWN_LINK)

    y -= 70
    c.setFont("R", 17)
    for line in ("It goes to Sam, to Grace, or to both. You pick.",
                 "Nothing about your phone is kept.",
                 "Leave a way to reach you if you want us to follow up."):
        c.drawCentredString(cx, y, line)
        y -= 25

    # The urgent part, at the bottom where the eye lands last and stays.
    c.setFillColorRGB(*RED)
    c.roundRect(54, 54, W - 108, 78, 14, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("B", 24)
    c.drawCentredString(cx, 101, "In danger right now? Call 911.")
    c.setFont("R", 18)
    c.drawCentredString(cx, 73, "Then tell whoever is behind the bar.")

    c.showPage()
    c.save()


if __name__ == "__main__":
    main(sys.argv[1])
