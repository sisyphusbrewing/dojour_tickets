"""
Sisyphus - email a comedian's advance to booking.

Run by the "Comedian advance" action after a comedian sends in
advance/index.html. Reads the row from Supabase with the service key, lays the
answers out in the same order as advance/fields.js, attaches the headshot and
sends it with the Gmail SMTP settings the other emails use.

    ADVANCE_ID=<uuid> python advance_notify.py
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
ADVANCE_ID = (os.environ.get("ADVANCE_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("ADVANCE_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
DESK_URL = "https://staff.sisyphusbrewing.com/advance/booking.html"


def sections():
    """The field list from advance/fields.js: a JS file whose value is plain JSON."""
    with open(os.path.join(HERE, "advance", "fields.js"), encoding="utf-8") as f:
        src = f.read()
    body = src[src.index("= ") + 2:]
    return json.loads(body.strip().rstrip(";"))


def fetch_advance():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/advances", params={"id": f"eq.{ADVANCE_ID}", "select": "*"},
                     headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"No advance with id {ADVANCE_ID}")
    return rows[0]


def pretty_date(d):
    if not d:
        return ""
    from datetime import date
    y, m, dd = (int(x) for x in d.split("-"))
    return date(y, m, dd).strftime("%a %b %-d")


def main():
    if not ADVANCE_ID:
        sys.exit("ADVANCE_ID is required")
    a = fetch_advance()
    data = a.get("data") or {}
    headshot_url = f"{SUPABASE_URL}/storage/v1/object/public/advance/{a['headshot_path']}" if a.get("headshot_path") else ""

    who = data.get("stage_name") or a.get("act_name") or a.get("show_name")
    when = " ".join(x for x in (pretty_date(a.get("show_date")), a.get("show_time") or "") if x)
    lines = [f"{who} sent in the advance for {a['show_name']}" + (f" ({when})" if when else "") + ".",
             f"Desk: {DESK_URL}#/a/{a['id']}", ""]
    for s in sections():
        rows = []
        for f in s["fields"]:
            if f.get("type") == "file":
                if headshot_url:
                    rows.append(f"  {f['label']}: {headshot_url} (attached)")
                continue
            v = data.get(f["k"])
            if v in (None, ""):
                continue
            v = str(v).strip()
            rows.append(f"  {f['label']}: " + ("\n    " + v.replace("\n", "\n    ") if "\n" in v else v))
        if rows:
            lines += [s["title"].upper()] + rows + [""]
    lines += ["Sisyphus · 712 Ontario Ave W, Minneapolis"]

    msg = EmailMessage()
    msg["Subject"] = f"Advance in: {who}" + (f" · {when}" if when else "")
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    if data.get("email"):
        msg["Reply-To"] = data["email"]
    msg.set_content("\n".join(lines))

    if headshot_url:
        try:
            r = requests.get(headshot_url, timeout=60)
            r.raise_for_status()
            if len(r.content) <= 20 * 1024 * 1024:
                ctype = r.headers.get("Content-Type", "application/octet-stream").split(";")[0]
                maintype, _, subtype = ctype.partition("/")
                msg.add_attachment(r.content, maintype=maintype or "application", subtype=subtype or "octet-stream",
                                   filename=os.path.basename(a["headshot_path"]))
        except Exception as e:  # the link is in the body either way
            print(f"Could not attach headshot: {e}")

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
