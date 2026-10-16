"""
Send one plain-text email to a customer from the box office mailbox.

Run from Actions > "Email a customer" (workflow_dispatch). Uses the same
SMTP secrets as the agent reports. Sends from FROM_EMAIL (the
ticketing@ box office address) with Reply-To set to it, so answers land there.

DRY_RUN=1 prints the message and checks the sender without sending.
"""
import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText
from email.utils import formataddr

SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
FROM_NAME = os.environ.get("FROM_NAME") or "Sisyphus Box Office"
EXPECTED_FROM = (os.environ.get("EXPECTED_FROM") or "").strip().lower()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

TO = (os.environ.get("EMAIL_TO") or "").strip()
SUBJECT = (os.environ.get("EMAIL_SUBJECT") or "").strip()
BODY = (os.environ.get("EMAIL_BODY") or "").replace("\\n", "\n").strip()


def main():
    if not TO or "@" not in TO or not SUBJECT or not BODY:
        sys.exit("Need EMAIL_TO, EMAIL_SUBJECT and EMAIL_BODY.")
    if EXPECTED_FROM and FROM_EMAIL.lower() != EXPECTED_FROM:
        sys.exit(f"Sender mailbox is not {EXPECTED_FROM}; not sending.")

    msg = MIMEText(BODY + "\n", "plain", "utf-8")
    msg["Subject"] = SUBJECT
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = TO
    msg["Reply-To"] = FROM_EMAIL

    print(f"To: {TO}\nSubject: {SUBJECT}\n\n{BODY}\n")
    print(f"Sender is expected mailbox: {FROM_EMAIL.lower() == EXPECTED_FROM if EXPECTED_FROM else 'not checked'}")
    if DRY_RUN:
        print("DRY_RUN: not sent.")
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing.")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [TO, FROM_EMAIL], msg.as_string())
    print("Sent (a copy went to the box office mailbox).")


if __name__ == "__main__":
    main()
