"""
Sisyphus - email a "Venmo me for this show" request to booking.

Run by the "Pay request" action after a comic sends payme/index.html. Reads
the row from Supabase with the service key and sends a short email with the
Gmail SMTP settings the other emails use. Approve or dismiss it on the pay
sheet. Reply-To is the comic when they left an email.

    REQUEST_ID=<uuid> python pay_request_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
REQUEST_ID = (os.environ.get("REQUEST_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("PAY_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SHEET_URL = "https://staff.sisyphusbrewing.com/payouts/"
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def money(v):
    v = float(v)
    return f"${v:,.0f}" if v.is_integer() else f"${v:,.2f}"


def main():
    if not REQUEST_ID:
        sys.exit("REQUEST_ID is required")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/pay_requests", params={"id": f"eq.{REQUEST_ID}", "select": "*"},
                     headers=AUTH, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"No pay request with id {REQUEST_ID}")
    q = rows[0]

    show = q["show_name"] + (f" ({q['show_dates']})" if q.get("show_dates") else "")
    lines = [f"{q['name']} wants to be paid for {show}.", "",
             f"  Did: {q['role']}",
             f"  Told: {money(q['amount'])}" if q.get("amount") else "  Told: (didn't say)",
             f"  Venmo: {q['handle']}"]
    if q.get("phone"):
        lines.append(f"  Phone: {q['phone']}")
    if q.get("email"):
        lines.append(f"  Email: {q['email']}")
    if q.get("note"):
        lines += ["", "  " + q["note"].strip().replace("\n", "\n  ")]
    lines += ["", f"Approve it and pay it on the pay sheet: {SHEET_URL}", "",
              "Sisyphus · 712 Ontario Ave W, Minneapolis"]

    msg = EmailMessage()
    msg["Subject"] = f"Pay request: {q['name']} · {q['show_name']}" + (f" · {money(q['amount'])}" if q.get("amount") else "")
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    if q.get("email"):
        msg["Reply-To"] = q["email"]
    msg.set_content("\n".join(lines))

    if DRY_RUN:
        print(f"[DRY RUN] To: {TO}\nSubject: {msg['Subject']}\n")
        print("\n".join(lines))
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"Sent '{msg['Subject']}' to {', '.join(TO)}")


if __name__ == "__main__":
    main()
