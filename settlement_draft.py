"""
Sisyphus - settlement draft, emailed the morning after a run's last night.

Run by the "Settlement draft" action every morning. Finds shows whose last
website night (Supabase show_nights) was last night, counts every ticket
(website + Dojour, same counting as the "Show sales report" action), works
out the door and the $3-a-ticket host/feature pool, and emails Sam a draft
so nobody has to build the numbers by hand. It's a starting point, not the
artist copy: walk-ups, comps at the door and the lineup still get added.

Money rules (Sam, Oct 2026): comedians get 100% of the door. Every paid
ticket puts $3 in the host/feature pool ($1 host, $2 feature), Dojour
tickets too; free comp-code tickets add $0. Website prices include the $3
since Oct 10. Card processing and sales tax are not taken out.

Skipped: recurring house shows (tagged "recurring: ...") and shows tagged
"no-settlement".

    python settlement_draft.py                 last night's finished runs
    SHOW_QUERY="Michael Longfellow" ...        one show, any date
    DRY_RUN=1 ...                              print instead of sending
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage

import requests

import recurring_events
from sales_report import shopify_sales, dojour_sales
from maintain_shows import Shopify
from show_dates import CENTRAL_TZ, parse_show_datetime

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("SETTLEMENT_EMAIL_TO") or "sam@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
SHOW_QUERY = (os.environ.get("SHOW_QUERY") or "").strip()
FEE = 3
HOST_SHARE, FEATURE_SHARE = 1, 2


def finished_last_night():
    """Titles whose latest saved night started yesterday (Central)."""
    today = datetime.now(CENTRAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (today - timedelta(days=60)).isoformat()
    r = requests.get(f"{SUPABASE_URL}/rest/v1/show_nights", timeout=30,
                     headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
                     params={"select": "title,starts_at", "starts_at": f"gte.{since}", "limit": "5000"})
    r.raise_for_status()
    last = {}
    for row in r.json():
        dt = datetime.fromisoformat(row["starts_at"]).astimezone(CENTRAL_TZ)
        if row["title"] not in last or dt > last[row["title"]]:
            last[row["title"]] = dt
    yesterday = today - timedelta(days=1)
    return sorted(t for t, dt in last.items() if yesterday <= dt < today)


def skipped(title):
    found = Shopify().gql("""query($q: String!) { products(first: 5, query: $q) {
        nodes { title tags } } }""", {"q": f'title:"{title}"'})["products"]["nodes"]
    for p in found:
        if p["title"].strip() == title:
            tags = p.get("tags") or []
            return recurring_events.has_recurring_tag(tags) or "no-settlement" in [t.lower() for t in tags]
    return False


def by_night(rows):
    """Rows in show order (Thu before Fri), not alphabetical."""
    def key(kv):
        dt = parse_show_datetime(str(kv[0][1]))
        return (dt is None, dt.isoformat() if dt else str(kv[0][1]))
    return sorted(rows.items(), key=key)


def money(x):
    return f"${x:,.2f}"


def draft(title):
    _, web = shopify_sales(title)
    try:
        dj, dj_note = dojour_sales(title), ""
    except Exception as e:  # Dojour login can lapse; the website half is still useful
        dj, dj_note = {}, f"Dojour couldn't be read ({e}); its tickets are missing below."

    lines, tickets, door, pool_tix = [], 0, 0.0, 0
    lines.append("WEBSITE")
    for (_, night), r in by_night(web):
        paid = r["tickets"] - r["comps"]
        d = r["gross"] - FEE * paid
        tickets += r["tickets"]; door += d; pool_tix += paid
        comp = f", {r['comps']} free" if r["comps"] else ""
        lines.append(f"  {night}: {r['tickets']} tickets{comp}, door {money(d)}")
    if not web:
        lines.append("  none")
    lines.append("DOJOUR")
    for (_, night), r in by_night(dj):
        d = r["revenue"] - FEE * r["tickets"]
        tickets += r["tickets"]; door += d; pool_tix += r["tickets"]
        lines.append(f"  {night}: {r['tickets']} tickets, door {money(d)}")
    if not dj:
        lines.append(f"  {dj_note or 'none'}")

    pool = FEE * pool_tix
    head = [
        f"{title}: settlement draft",
        "",
        f"Tickets: {tickets}",
        f"Door to the headliner: {money(door)}",
        f"Host/feature pool: {money(pool)} (host {money(HOST_SHARE * pool_tix)}, feature {money(FEATURE_SHARE * pool_tix)})",
        "",
    ]
    tail = [
        "",
        "Still to add by hand: walk-ups, door comps, the lineup per night, and any",
        "Dojour holds (a hold shows as tickets with no money). Card fees and sales",
        "tax are not taken out. Reply with changes and Claude will build the",
        "artist copy.",
        "",
        "Pay sheet: https://staff.sisyphusbrewing.com/payouts/",
    ]
    return "\n".join(head + lines + tail)


def send(subject, body):
    if DRY_RUN:
        print(f"[DRY RUN] To: {TO}\nSubject: {subject}\n\n{body}\n")
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Sisyphus <{FROM_EMAIL}>", ", ".join(TO)
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"Sent '{subject}' to {', '.join(TO)}")


def main():
    titles = [SHOW_QUERY] if SHOW_QUERY else finished_last_night()
    if not titles:
        print("No runs ended last night.")
        return
    for title in titles:
        if not SHOW_QUERY and skipped(title):
            print(f"Skipped {title} (recurring or no-settlement)")
            continue
        send(f"Settlement draft: {title}", draft(title))


if __name__ == "__main__":
    main()
