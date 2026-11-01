"""
Sisyphus - after a headliner's last show, email them their opted-in buyer list.

Runs every morning (Actions > "Headliner mailing lists"). For each show in
show_agents whose final date on the website was yesterday (Central), it builds
the buyer list from Shopify + Dojour (buyer_list.py), keeps only buyers who
opted in to emails at checkout, and emails the CSV to the show's contact,
cc booking@. Manual run: give a show name (and optionally a different
address) to send one list now.
"""
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

import buyer_list
from maintain_shows import Shopify
from show_dates import parse_show_datetime, CENTRAL_TZ

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
CC = [a for a in (os.environ.get("CC_EMAIL") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
ONLY_SHOW = (os.environ.get("SHOW_QUERY") or "").strip()
OVERRIDE_TO = (os.environ.get("TO_EMAIL") or "").strip()


def show_agents():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/show_agents?select=show_title,agent_name,agent_email",
                     headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}, timeout=30)
    r.raise_for_status()
    return [a for a in r.json() if a.get("show_title") and a.get("agent_email")]


def show_dates(shop, title):
    """Every showtime on the website for products named like this show (any status)."""
    found = shop.gql("""query($q: String!) { products(first: 20, query: $q) {
        nodes { title variants(first: 100) { nodes { title
          metafield(namespace: "custom", key: "show_start") { value } } } } } }""",
                     {"q": f'title:"{title}"'})["products"]["nodes"]
    dates = []
    for p in found:
        if title.lower() not in p["title"].lower():
            continue
        for v in p["variants"]["nodes"]:
            raw = (v.get("metafield") or {}).get("value")
            d = None
            if raw:
                try:
                    d = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(CENTRAL_TZ)
                except ValueError:
                    d = None
            d = d or parse_show_datetime(v["title"].split(" / ")[0], require_time=True)
            if d:
                dates.append(d)
    return sorted(dates)


def send(to, show, rows, first, last):
    recipients = [a.strip() for a in to.replace(";", ",").split(",") if a.strip()]
    span = first.strftime("%b %-d") if first.date() == last.date() else \
        f"{first.strftime('%b %-d')}-{last.strftime('%-d') if first.month == last.month else last.strftime('%b %-d')}"
    tickets = sum(r["qty"] for r in rows)
    body = (f"Hi,\n\nThanks for a great run at Sisyphus. Attached are the {len(rows)} people from your "
            f"{span} shows ({tickets} tickets) who opted in to emails at checkout, so you can add them "
            f"to your mailing list. Anyone who didn't opt in is left off.\n\n"
            f"Come back soon.\n\nSam\nSisyphus, Minneapolis\n")
    msg = MIMEMultipart()
    msg["Subject"] = f"Your Sisyphus mailing list: {show} ({span})"
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(recipients)
    msg["Cc"] = ", ".join(CC)
    msg["Reply-To"] = "sam@sisyphusbrewing.com"
    msg.attach(MIMEText(body, "plain"))
    att = MIMEApplication(buyer_list.to_csv(rows, ["name", "email", "show", "qty"]).encode("utf-8"), _subtype="csv")
    fname = f"{show.lower().replace(' ', '-')}-{first.strftime('%Y-%m-%d')}-mailing-list.csv"
    att.add_header("Content-Disposition", "attachment", filename=fname)
    msg.attach(att)
    if DRY_RUN:
        print(f"[DRY RUN] would email {fname} ({len(rows)} buyers) to {recipients}, cc {CC}")
        return
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, recipients + CC, msg.as_string())
    print(f"Sent {fname} ({len(rows)} buyers) to {recipients}")


def main():
    shop = Shopify()
    yesterday = (datetime.now(CENTRAL_TZ) - timedelta(days=1)).date()
    agents = show_agents()
    if ONLY_SHOW:
        agents = [a for a in agents if ONLY_SHOW.lower() in a["show_title"].lower()] or \
                 [{"show_title": ONLY_SHOW, "agent_email": OVERRIDE_TO}]
    seen = set()
    for a in agents:
        title = a["show_title"].strip()
        if title.lower() in seen:
            continue
        seen.add(title.lower())
        dates = show_dates(shop, title)
        if not dates:
            continue
        last = dates[-1]
        if not ONLY_SHOW and last.date() != yesterday:
            continue
        # The run = the dates within two weeks of the last show (a repeat headliner's
        # earlier visits stay out).
        run = [d for d in dates if d >= last - timedelta(days=14)]
        first = run[0]
        rows = [r for r in buyer_list.build(title, since=first.strftime("%Y-%m-%d"))
                if r["marketing_ok"] == "yes" and r["email"]]
        # Website rows carry no year; keep only nights in this run.
        nights = {d.strftime("%b %-d") for d in run}
        rows = [r for r in rows if any(re.search(rf"\b{n}\b", r["show"].replace(",", "")) for n in nights)]
        to = OVERRIDE_TO or a["agent_email"]
        if not rows or not to:
            print(f"{title}: nothing to send ({len(rows)} opted-in buyers, to={to!r})")
            continue
        send(to, title, rows, first, last)


if __name__ == "__main__":
    if not (SUPABASE_KEY or ONLY_SHOW):
        sys.exit("SUPABASE_SERVICE_ROLE_KEY missing.")
    main()
