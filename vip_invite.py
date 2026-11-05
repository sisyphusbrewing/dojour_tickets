"""
VIP welcome emails: every VIP / Reserved Seating buyer gets a link to the
four-question table form (staff.sisyphusbrewing.com/vip/?t=<token>).

  invite    the day before the show, from 10 AM Central (or as soon as the
            sale is on the door list if they buy after that; runs hourly)
  reminder  the morning of the show (after 9 AM Central), only if they
            haven't answered and the invite went out before today

Answers land in public.vip_prefs and show on the door list, the manager
page's VIP card (snack totals) and manager/tents.html (table tents).

Live since Sam's OK on Nov 5 2026; the repo variable VIP_EMAILS_LIVE=off
turns it back into a dry run that prints who would get what.
PREVIEW_TO=<address> sends one sample invite (with a working test link) to
that address and nobody else.
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape

import requests

from show_dates import CENTRAL_TZ, parse_show_datetime

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
FROM_NAME = "Sisyphus Box Office"
# On since Nov 5 2026 (Sam). Set the repo variable VIP_EMAILS_LIVE to "off" to pause.
LIVE = (os.environ.get("VIP_EMAILS_LIVE") or "").strip().lower() != "off"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes") or not LIVE
PREVIEW_TO = (os.environ.get("PREVIEW_TO") or "").strip()
FORM_URL = "https://staff.sisyphusbrewing.com/vip/?t="
PREVIEW_ID = "preview_vip_form"


def is_vip_row(row):
    import re
    return (re.search(r"vip|premium|reserved", row.get("ticket_type") or "", re.I)
            and not re.match(r"shopify sales", row.get("guest_name") or "", re.I)
            and "@" in (row.get("email") or ""))


def first_name(name):
    part = (name or "").strip().split(" ")[0]
    return part[:1].upper() + part[1:] if part else ""


def pretty_when(show_date):
    # "Fri, Nov 6 • 7:00 PM" -> "Fri, Nov 6 at 7:00 PM"
    return " at ".join(p.strip() for p in str(show_date).split("•"))


# ---------------------------------------------------------------- the email

def build_email(kind, name, show_title, show_date, seats, token):
    link = FORM_URL + token
    hi = f"Hi {escape(name)}," if name else "Hi,"
    when = escape(pretty_when(show_date))
    title = escape(show_title)
    seat_word = "seat" if seats == 1 else "seats"
    if kind == "invite":
        subject = f"Your VIP table for {show_title}"
        paras = [
            hi,
            f"You bought VIP for <b>{title}</b> on {when}. Thank you. That gets you {seats} reserved {seat_word} "
            "and a little table tent with your name on it, and while we're at it we'd like to get the rest of the night right too.",
            "So, four quick questions. What name goes on the tent, whether you're celebrating anything, "
            "how close to the comedian you're brave enough to sit, and salty or sweet snacks. "
            "It takes about 20 seconds, which is less time than it takes us to find a Sharpie.",
        ]
        after = ("When you get here, tell the door your name and someone will walk you to your table. "
                 "If you want to change an answer later, the same link works.")
        button = "Set up my table"
    else:
        subject = f"Tonight: your VIP table for {show_title}"
        paras = [
            hi,
            f"<b>{title}</b> is tonight, {when}, and your table is waiting. "
            "We just don't know what to write on the tent yet, or whether you're a front row person.",
            "Twenty seconds and we stop guessing:",
        ]
        after = "Tell the door your name when you get here and someone will walk you to your seats."
        button = "Set up my table"

    p = '<p style="margin:0 0 16px;font-size:16px;line-height:1.55;color:#2b2929">'
    html = (
        '<div style="font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:8px 4px">'
        + "".join(p + x + "</p>" for x in paras)
        + '<p style="margin:22px 0 24px"><a href="' + link + '" style="background:#4a6c86;color:#ffffff;text-decoration:none;'
        'font-weight:bold;font-size:16px;padding:14px 24px;border-radius:10px;display:inline-block">' + button + "</a></p>"
        + p + after + "</p>"
        + p + "See you soon.<br>Sisyphus</p>"
        + '<p style="margin:24px 0 0;font-size:13px;color:#918f90">Sisyphus · 712 Ontario Ave W, Minneapolis · '
        'Questions? Just reply to this email.</p></div>'
    )
    text = "\n\n".join(x.replace("<b>", "").replace("</b>", "") for x in paras)
    text += f"\n\n{button}: {link}\n\n{after}\n\nSee you soon.\nSisyphus\n"
    return subject, text, html


def send(to, subject, text, html):
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    msg["Subject"] = subject
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = to
    msg["Reply-To"] = FROM_EMAIL
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [to], msg.as_string())


# ---------------------------------------------------------------- Supabase

def sb(method, path, **kw):
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    headers.update(kw.pop("headers", {}))
    r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=headers, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def fetch_vip_rows():
    rows, offset = [], 0
    while True:
        page = sb("GET", "tickets?select=unique_id,show_date,show_title,guest_name,email,tickets,ticket_type"
                         "&ticket_type=not.is.null&order=unique_id"
                         f"&limit=1000&offset={offset}")
        rows += page
        if len(page) < 1000:
            return [r for r in rows if is_vip_row(r)]
        offset += 1000


def mark(unique_ids, field):
    ids = ",".join('"' + u.replace('"', "") + '"' for u in unique_ids)
    sb("PATCH", f"vip_prefs?unique_id=in.({ids})", json={field: datetime.now(timezone.utc).isoformat()},
       headers={"Prefer": "return=minimal"})


def preview(to):
    """One sample invite with a working link to a test row on the next VIP show."""
    rows = upcoming(fetch_vip_rows())
    if rows:
        r = rows[0][1]
        title, date = r["show_title"], r["show_date"]
    else:
        title, date = "Michael Longfellow", "Fri, Nov 6 • 7:00 PM"
    sb("POST", "vip_prefs?on_conflict=unique_id",
       json=[{"unique_id": PREVIEW_ID, "show_date": date, "show_title": title}],
       headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
    token = sb("GET", f"vip_prefs?select=token&unique_id=eq.{PREVIEW_ID}")[0]["token"]
    for kind in ("invite", "reminder"):
        subject, text, html = build_email(kind, "Sam", title, date, 2, token)
        print(f"--- {kind} -> {to}\nSubject: {subject}\n\n{text}")
        send(to, "[Preview] " + subject, text, html)
    print("Preview sent (invite + reminder). The test row is ignored by the door list.")


def upcoming(rows):
    now = datetime.now(CENTRAL_TZ)
    out = []
    for r in rows:
        when = parse_show_datetime(r["show_date"], now=now)
        if when and when > now:
            out.append((when, r))
    out.sort(key=lambda x: x[0])
    return out


def main():
    if not SUPABASE_KEY:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY missing.")
    # Sam (Nov 5 2026): VIP emails come from the box office, never sam@.
    if FROM_EMAIL.lower() != "ticketing@sisyphusbrewing.com" and not DRY_RUN:
        sys.exit(f"Sender is {FROM_EMAIL}, not ticketing@sisyphusbrewing.com; not sending.")
    if PREVIEW_TO:
        if "@" not in PREVIEW_TO:
            sys.exit("PREVIEW_TO is not an email address.")
        preview(PREVIEW_TO)
        return

    now = datetime.now(CENTRAL_TZ)
    rows = upcoming(fetch_vip_rows())
    if not rows:
        print("No upcoming VIP orders.")
        return

    # Make sure every VIP line has a form row (and token).
    sb("POST", "vip_prefs?on_conflict=unique_id",
       json=[{"unique_id": r["unique_id"], "show_date": r["show_date"], "show_title": r["show_title"]} for _, r in rows],
       headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})
    prefs = {}
    ids = [r["unique_id"] for _, r in rows]
    for i in range(0, len(ids), 100):
        chunk = ",".join('"' + u.replace('"', "") + '"' for u in ids[i:i + 100])
        for p in sb("GET", f"vip_prefs?select=unique_id,token,invited_at,reminded_at,answered_at&unique_id=in.({chunk})"):
            prefs[p["unique_id"]] = p

    # One email per buyer per showtime, even if their order has several VIP lines.
    groups = {}
    for when, r in rows:
        key = (r["email"].strip().lower(), r["show_date"], r["show_title"])
        groups.setdefault(key, {"when": when, "rows": []})["rows"].append(r)

    sent = {"invite": 0, "reminder": 0}
    for (email, show_date, show_title), g in groups.items():
        ps = [prefs[r["unique_id"]] for r in g["rows"] if r["unique_id"] in prefs]
        if not ps:
            continue
        lead = g["rows"][0]
        token = prefs[lead["unique_id"]]["token"]
        seats = sum(int(r.get("tickets") or 1) for r in g["rows"])
        answered = any(p.get("answered_at") for p in ps)
        invited = [p["invited_at"] for p in ps if p.get("invited_at")]
        show_day = g["when"].date() == now.date()

        kind = None
        # Invite the day before the show (from 10 AM Central), or right away if they buy later than that.
        days_out = (g["when"].date() - now.date()).days
        if (not invited and not answered and g["when"] - now > timedelta(hours=2)
                and (days_out <= 0 or (days_out == 1 and now.hour >= 10))):
            kind = "invite"
        elif (invited and not answered and show_day and now.hour >= 9
              and not any(p.get("reminded_at") for p in ps)
              and datetime.fromisoformat(min(invited)).astimezone(CENTRAL_TZ).date() < now.date()):
            kind = "reminder"
        if not kind:
            continue

        subject, text, html = build_email(kind, first_name(lead.get("guest_name")), show_title, show_date, seats, token)
        print(f"{'WOULD SEND' if DRY_RUN else 'SEND'} {kind}: {show_title} / {show_date} / {seats} seats / {email[:2]}***")
        if DRY_RUN:
            continue
        try:
            send(email, subject, text, html)
        except Exception as e:  # keep going; one bad address shouldn't stop the rest
            print(f"  failed: {e}")
            continue
        mark([r["unique_id"] for r in g["rows"]], "invited_at" if kind == "invite" else "reminded_at")
        sent[kind] += 1

    mode = "dry run (VIP_EMAILS_LIVE is not on)" if DRY_RUN else "live"
    print(f"Done, {mode}: {sent['invite']} invites, {sent['reminder']} reminders sent.")


if __name__ == "__main__":
    main()
