"""
Sisyphus - email a comic's notes on the comics pitch to booking.

Run by the "Comic feedback" action after a comic fills in the last screen of
comics/index.html: either "How should we get in touch?" from a card Sam handed
out (data.kind "booking"), or the roast on a ?c=<name> link. Reads the row
from Supabase with the service key, lays the answers out in the order of
comics/feedback.js and sends it with the Gmail SMTP settings the other emails
use. Also lists how far every named link has got (comic_views).

    FEEDBACK_ID=<uuid> python comic_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it
"""
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
FEEDBACK_ID = (os.environ.get("FEEDBACK_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
AD_REVIEW_TO = ["sam@sisyphusbrewing.com"]  # ad reviews (rate/index.html) go to Sam, not the booking inbox
TO = [a.strip() for a in (os.environ.get("COMIC_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SCREENS = 7
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def questions():
    """The question list from comics/feedback.js: a JS file whose value is plain JSON."""
    with open(os.path.join(HERE, "comics", "feedback.js"), encoding="utf-8") as f:
        src = f.read()
    return json.loads(src[src.index("COMIC_FEEDBACK = ") + 17:].strip().rstrip(";"))


def get(table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", params=params, headers=AUTH, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    if not FEEDBACK_ID:
        sys.exit("FEEDBACK_ID is required")
    rows = get("comic_feedback", {"id": f"eq.{FEEDBACK_ID}", "select": "*"})
    if not rows:
        sys.exit(f"No feedback with id {FEEDBACK_ID}")
    fb = rows[0]
    data = fb.get("data") or {}
    who = fb.get("name") or fb.get("tag") or "A comic"

    if data.get("kind") == "booking":
        return send(*booking(data, who))
    if data.get("kind") == "ad_review":
        return send(*ad_review(data), to=AD_REVIEW_TO)

    lines = [f"{who} roasted the comics pitch.", ""]
    for q in questions():
        if q["k"] == "name":
            continue
        v = data.get(q["k"])
        if isinstance(v, list):
            v = ", ".join(v)
        v = str(v or "").strip() or "-"
        lines.append(q["label"].upper())
        lines.append("  " + v.replace("\n", "\n  "))
        lines.append("")

    views = get("comic_views", {"select": "*", "order": "last_seen.desc"})
    if views:
        lines.append(f"WHO HAS OPENED THEIR LINK (screen reached, of {SCREENS})")
        for v in views:
            lines.append(f"  {v['tag']}: screen {v['max_screen']}, opened {v['opens']}x, last {v['last_seen'][:16].replace('T', ' ')} UTC")
        lines.append("")
    lines += ["Sisyphus · 712 Ontario Ave W, Minneapolis"]
    send(f"Comic notes on the pitch: {who}", lines)


def booking(data, who):
    """A comic wants a weekend: who to get in touch with, and how."""
    via = {"nfc": "tapped the card", "qr": "scanned the card"}.get(data.get("via") or "", "opened the comics page")
    how = data.get("how") or "-"
    lines = [f"{who} {via} and wants a weekend.", "", "GET IN TOUCH: " + how]
    for k, label in (("contact", "Email or phone"), ("agent", "Agent"), ("agent_email", "Agent's email"), ("other", "How")):
        if data.get(k):
            lines.append(f"{label}: " + str(data[k]).replace("\n", "\n  "))
    lines += ["", "Sisyphus · 712 Ontario Ave W, Minneapolis"]
    return f"Booking: {who} wants a weekend ({how.lower()})", lines


def ad_review(data):
    """A comic rated how we ran their ads (rate/index.html)."""
    who = data.get("name") or "A comic"
    lines = [f"{who} inspected the Ad Factory.", ""]
    for k, label in (("copy", "The words"), ("photos", "The pictures"), ("emails", "The emails"),
                     ("say", "Who's driving"), ("worth", "Worth it"), ("notes", "Anything else")):
        v = str(data.get(k) or "").strip() or "-"
        lines += [label.upper(), "  " + v.replace("\n", "\n  "), ""]
    return f"Ad review: {who} rated the ad help", lines


def send(subject, lines, to=None):
    to = to or TO
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(to)
    msg.set_content("\n".join(lines))

    if DRY_RUN:
        print(f"[DRY RUN] To: {to}\nSubject: {msg['Subject']}\n")
        print("\n".join(lines))
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"Sent '{msg['Subject']}' to {', '.join(to)}")


if __name__ == "__main__":
    main()
