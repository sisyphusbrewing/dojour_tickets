"""
Sisyphus - email booking when supplies run low.

Run by the "Low supplies" action: right after a manager saves a low count on
the supply sheet (supplies/index.html, staff hub > Supplies), and every
morning as a backstop. Finds counted items at or under their "low at" line
that nobody has been told about yet, emails one list grouped by store, and
stamps low_alerted_at so the same dip is only emailed once. The table resets
low_alerted_at itself when the count goes back up.

    python supply_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it (and stamps nothing)
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("SUPPLY_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
PAGE_URL = "https://staff.sisyphusbrewing.com/supplies/"
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def fetch_low():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/supply_items", headers=AUTH, timeout=30, params={
        "select": "*", "active": "is.true", "on_hand": "not.is.null", "low_alerted_at": "is.null",
        "order": "vendor.asc.nullslast,sort.asc,name.asc"})
    r.raise_for_status()
    return [i for i in r.json() if float(i["on_hand"]) <= float(i["low_at"])]


def num(v):
    v = float(v)
    return str(int(v)) if v.is_integer() else str(v)


def build(items):
    lines = [f"Running low on {len(items)} thing{'s' if len(items) != 1 else ''}.", ""]
    by_vendor = {}
    for it in items:
        by_vendor.setdefault(it.get("vendor") or "Anywhere", []).append(it)
    for vendor, rows in by_vendor.items():
        lines.append(vendor.upper())
        for it in rows:
            unit = f" {it['unit']}" if it.get("unit") else ""
            left = "none left" if float(it["on_hand"]) == 0 else f"{num(it['on_hand'])}{unit} left"
            who = f", counted by {it['counted_by'].split('@')[0]}" if it.get("counted_by") else ""
            lines.append(f"  {it['name']}: {left} (low at {num(it['low_at'])}{who})")
            if it.get("url"):
                lines.append(f"    {it['url']}")
        lines.append("")
    lines += [f"The whole sheet: {PAGE_URL}", "", "Sisyphus · 712 Ontario Ave W, Minneapolis"]
    first = items[0]["name"]
    more = f" + {len(items) - 1} more" if len(items) > 1 else ""
    return f"Low supplies: {first}{more}", "\n".join(lines)


def stamp(items):
    ids = ",".join(i["id"] for i in items)
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/supply_items", params={"id": f"in.({ids})"},
                       json={"low_alerted_at": datetime.now(timezone.utc).isoformat()},
                       headers={**AUTH, "Prefer": "return=minimal"}, timeout=30)
    r.raise_for_status()


def main():
    items = fetch_low()
    if not items:
        print("Nothing low. The boulder rests.")
        return
    subject, body = build(items)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    msg.set_content(body)

    if DRY_RUN:
        print(f"[DRY RUN] To: {TO}\nSubject: {subject}\n")
        print(body)
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    stamp(items)
    print(f"Sent '{subject}' to {', '.join(TO)}")


if __name__ == "__main__":
    main()
