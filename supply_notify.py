"""
Sisyphus - email booking when supplies run low, and send reorder emails.

Run by the "Low supplies" action: right after a manager saves a low count on
the supply sheet (supplies/index.html, staff hub > Supplies), and every
morning as a backstop. Finds counted items at or under their "low at" line
that nobody has been told about yet, emails one list grouped by store, and
stamps low_alerted_at so the same dip is only emailed once. The table resets
low_alerted_at itself when the count goes back up.

It also sends the orders managers placed with the Reorder buttons on the
same page (Sam, Nov 17 2026: "it would be nice to have buttons to order stuff
like that"). The page writes a row to supply_orders with the finished email
and starts this action; each waiting order goes to its vendor with sam@ and
booking@ copied and replies going to Sam, then is marked sent (or failed,
with the reason, so the page can show it).

    python supply_notify.py
    DRY_RUN=1 ...   prints the emails instead of sending them (and stamps nothing)
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
ORDER_CC = ["sam@sisyphusbrewing.com", "booking@sisyphusbrewing.com"]
ORDER_REPLY_TO = "sam@sisyphusbrewing.com"
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


def fetch_orders():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/supply_orders", headers=AUTH, timeout=30, params={
        "select": "id,to_email,subject,body,supply_reorders(label)", "status": "eq.queued", "order": "ordered_at.asc"})
    r.raise_for_status()
    return r.json()


def order_message(order):
    """The email a vendor gets for one order: the text the page showed, from
    the club's sending address, with Sam and booking@ copied so the order is
    on record in both inboxes and the vendor's reply reaches Sam."""
    msg = EmailMessage()
    msg["Subject"] = order["subject"]
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = order["to_email"]
    cc = [a for a in ORDER_CC if a.lower() not in (order["to_email"].lower(), FROM_EMAIL.lower())]
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Reply-To"] = ORDER_REPLY_TO
    msg.set_content(order["body"])
    return msg


def mark(order_id, status, error=None):
    patch = {"status": status, "error": error}
    if status == "sent":
        patch["sent_at"] = datetime.now(timezone.utc).isoformat()
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/supply_orders", params={"id": f"eq.{order_id}", "status": "eq.queued"},
                       json=patch, headers={**AUTH, "Prefer": "return=minimal"}, timeout=30)
    r.raise_for_status()


def send_orders():
    orders = fetch_orders()
    if not orders:
        print("No orders waiting.")
        return
    # The log is public: say which button, never who or to what address.
    for order in orders:
        label = (order.get("supply_reorders") or {}).get("label") or "order"
        msg = order_message(order)
        if DRY_RUN:
            print(f"[DRY RUN] {label} order:\n{order['body']}\n")
            continue
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        except Exception as e:  # keep going; the page shows the failure
            mark(order["id"], "failed", f"{type(e).__name__}: {e}"[:300])
            print(f"{label} order failed: {type(e).__name__}")
            continue
        mark(order["id"], "sent")
        print(f"Sent the {label} order.")


def main():
    if not DRY_RUN and (not SMTP_USER or not SMTP_PASS):
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    send_orders()
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
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    stamp(items)
    print(f"Sent '{subject}' to {', '.join(TO)}")


if __name__ == "__main__":
    main()
