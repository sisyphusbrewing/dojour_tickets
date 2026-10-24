"""
Sisyphus - emails for the pay sheet (payouts/index.html).

Run by the "Pay sheet emails" action, which the pay sheet starts right after
a manager taps Paid or "Email them the link", and every morning as a
backstop. Sends two kinds of short email, each once:

  - get-paid links: payees a manager asked to invite (invite_wanted_at set,
    invited_at empty) get their getpaid/?t=<token> link, plus what we owe them.
  - receipts: paid payout lines with receipt_wanted and no receipt_sent_at,
    one email per person listing what was just sent.

    python payout_mail.py
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
REPLY_TO = "booking@sisyphusbrewing.com"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
GETPAID_URL = "https://staff.sisyphusbrewing.com/getpaid/?t="
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
SIGN_OFF = ["Sam", "Sisyphus · 712 Ontario Ave W, Minneapolis"]


def get(table, **params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=AUTH, params={"select": "*", **params}, timeout=30)
    r.raise_for_status()
    return r.json()


def stamp(table, ids, field):
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}", params={"id": f"in.({','.join(ids)})"},
                       json={field: datetime.now(timezone.utc).isoformat()},
                       headers={**AUTH, "Prefer": "return=minimal"}, timeout=30)
    r.raise_for_status()


def money(v):
    v = float(v)
    return f"${v:,.0f}" if v.is_integer() else f"${v:,.2f}"


def first_name(p):
    return (p.get("name") or "there").split()[0]


def line_text(l):
    when = ""
    if l.get("show_end"):
        when = " (" + datetime.strptime(l["show_end"], "%Y-%m-%d").strftime("%b %-d") + ")"
    bits = [f"{l['show_name']}{when}", l.get("memo") or l.get("role") or ""]
    return "  " + " · ".join(b for b in bits if b) + f": {money(l['amount'])}"


def how_paid(p, via):
    via = via or p.get("method")
    if via == "Check":
        return f"by check to {p.get('legal_name') or p['name']}"
    if via in ("Venmo", "Zelle", "PayPal", "Cash App") and p.get("handle"):
        return f"by {via} to {p['handle']}"
    return f"by {via}" if via else ""


def invite_email(p, owed):
    lines = [f"Hi {first_name(p)},", ""]
    if owed:
        total = sum(float(l["amount"]) for l in owed)
        lines += [f"We owe you {money(total)}. This is the good kind of email.", ""]
        lines += [line_text(l) for l in owed] + [""]
    lines += ["Tell us once how you want to get paid (Venmo, Zelle, check, whatever) and add a W-9:",
              GETPAID_URL + p["token"], "",
              "Thirty seconds. We use it every time after.", ""] + SIGN_OFF
    return "How do you want to get paid?", "\n".join(lines)


def receipt_email(p, paid):
    total = sum(float(l["amount"]) for l in paid)
    how = how_paid(p, paid[0].get("paid_via"))
    lines = [f"Hi {first_name(p)},", "", f"Sent you {money(total)}{' ' + how if how else ''}.", ""]
    lines += [line_text(l) for l in paid] + [""]
    if not p.get("w9_path"):
        lines += ["We still need a W-9 for taxes. Add it here when you get a minute:", GETPAID_URL + p["token"], ""]
    lines += ["Thanks for making people laugh in a brewery. Weird room. Good people.", ""] + SIGN_OFF
    return f"Paid: {money(total)} from Sisyphus", "\n".join(lines)


def send(server, to, subject, body):
    if DRY_RUN:
        print(f"[DRY RUN] To: {to}\nSubject: {subject}\n\n{body}\n{'-' * 60}")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = to
    msg["Reply-To"] = REPLY_TO
    msg.set_content(body)
    server.send_message(msg)
    print(f"Sent '{subject}' to {to}")


def main():
    payees = {p["id"]: p for p in get("payees")}
    owed = get("payouts", status="eq.owed", order="show_end.asc.nullslast")
    to_receipt = get("payouts", status="eq.paid", receipt_wanted="is.true", receipt_sent_at="is.null", order="paid_at.asc")

    invites = [p for p in payees.values() if p.get("invite_wanted_at") and not p.get("invited_at") and p.get("email")]
    receipts = {}
    for l in to_receipt:
        p = payees.get(l["payee_id"])
        if p and p.get("email"):
            receipts.setdefault(p["id"], []).append(l)

    if not invites and not receipts:
        print("No emails to send. The boulder rests.")
        return
    if not DRY_RUN and (not SMTP_USER or not SMTP_PASS):
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")

    server = None
    if not DRY_RUN:
        server = smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
    try:
        for p in invites:
            mine = [l for l in owed if l["payee_id"] == p["id"]]
            send(server, p["email"], *invite_email(p, mine))
            if not DRY_RUN:
                stamp("payees", [p["id"]], "invited_at")
        for pid, paid in receipts.items():
            send(server, payees[pid]["email"], *receipt_email(payees[pid], paid))
            if not DRY_RUN:
                stamp("payouts", [l["id"] for l in paid], "receipt_sent_at")
    finally:
        if server:
            server.quit()


if __name__ == "__main__":
    main()
