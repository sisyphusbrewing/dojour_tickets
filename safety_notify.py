"""
Sisyphus - email a report of unsafe behavior from the Green Room.

Sam, Nov 17 2026: "Let's make some thing for the Green Room where people can
tap or go to a website if they need to report unsafe behavior". Someone fills
in safe/index.html (from the tag in the Green Room, the QR code on the sign,
or the link), the "job-applied" Supabase function starts the "Safety report"
action, and this script emails the report.

Who gets it is the reporter's pick, so someone can report about either of us:
    both   Sam (sam@) and Grace (booking@)
    sam    only Sam
    grace  only Grace
Set the SAFETY_SAM_TO / SAFETY_GRACE_TO repo variables to change the addresses.

Reports can be anonymous. When the reporter left an email address, Reply-To
is that address, so answering the email reaches them.

    REPORT_ID=<uuid> python safety_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it (on your own
                    machine only: this repo's Actions logs are public, so the
                    workflow never sets it and a real run prints nothing about
                    the report)
"""
import os
import re
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
REPORT_ID = (os.environ.get("REPORT_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def addresses(value, fallback):
    return [a.strip() for a in (value or fallback).split(",") if a.strip()]


SAM_TO = addresses(os.environ.get("SAFETY_SAM_TO"), "sam@sisyphusbrewing.com")
GRACE_TO = addresses(os.environ.get("SAFETY_GRACE_TO"), "booking@sisyphusbrewing.com")
EMAIL_RE = re.compile(r"[^@\s<>,;]+@[^@\s<>,;]+\.[A-Za-z]{2,}")


def recipients(send_to, sam=None, grace=None):
    """Who reads it, from the reporter's pick. Anything unexpected goes to both."""
    sam = SAM_TO if sam is None else sam
    grace = GRACE_TO if grace is None else grace
    if send_to == "sam":
        return list(sam)
    if send_to == "grace":
        return list(grace)
    return list(dict.fromkeys(sam + grace))


def day_words(value):
    """'2026-11-17' -> 'Tue, Nov 17'."""
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{d:%a}, {d:%b} {d.day}"


def compose(r):
    """The subject and lines of the email for one safety_reports row."""
    anonymous = not (r.get("name") or "").strip()
    who_sent = "Anonymous" if anonymous else r["name"].strip()
    subject = "Safety report from the Green Room" + (" (anonymous)" if anonymous else f" from {who_sent}")
    readers = {"sam": "only Sam", "grace": "only Grace"}.get(r.get("send_to"), "Sam and Grace")

    lines = ["Someone used the Green Room safety page to report something.", ""]
    lines += ["What happened:", "", "  " + (r.get("what") or "").strip().replace("\n", "\n  "), ""]
    if r.get("happened_on"):
        lines.append(f"  When: {day_words(r['happened_on'])}")
    if r.get("place"):
        lines.append(f"  Where: {r['place']}")
    if r.get("who"):
        lines.append("  Who was involved: " + r["who"].strip().replace("\n", "\n    "))
    lines.append(f"  Sent by: {who_sent}")
    if r.get("contact"):
        lines.append(f"  How to reach them: {r['contact']}")
    elif not anonymous:
        lines.append("  They left no way to reach them.")
    lines += ["", f"They asked for this to go to {readers}.", ""]
    if r.get("contact") and EMAIL_RE.search(r["contact"]):
        lines.append("Replying to this email reaches them.")
    elif anonymous:
        lines.append("This was sent anonymously. Nothing about the phone it came from was kept, so there is no way to write back.")
    lines += ["", "Sisyphus · 712 Ontario Ave W, Minneapolis"]
    return subject, lines


def build_message(r):
    subject, lines = compose(r)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(recipients(r.get("send_to")))
    msg["X-Priority"] = "1"
    msg["Importance"] = "high"
    found = EMAIL_RE.search(r.get("contact") or "")
    if found:
        msg["Reply-To"] = found.group(0)
    msg.set_content("\n".join(lines))
    return msg


def main():
    if not REPORT_ID:
        sys.exit("REPORT_ID is required")
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/safety_reports", params={"id": f"eq.{REPORT_ID}", "select": "*"},
                        headers=AUTH, timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        sys.exit("No safety report with that id")
    msg = build_message(rows[0])

    if DRY_RUN:
        print(msg)
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    # Nothing about the report or who it went to: this prints into a public log.
    print("Sent the safety report email.")


if __name__ == "__main__":
    main()
