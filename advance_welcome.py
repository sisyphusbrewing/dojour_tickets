"""
Sisyphus - the welcome email a comedian gets when they are booked.

The "Comedian welcome" action runs this from the booking desk's "Send the
welcome" button. It reads the advance from Supabase with the service key and
sends the comedian (advances.contact_email) a short "you're booked" note
from Sam whose button opens their trip: the advance, one quick stop at a
time (advance/trip.html, on the site at /pages/advance?s=<token>).

    ADVANCE_ID=<uuid> python advance_welcome.py
    WELCOME_TO=someone@example.com ...   preview: send to this address instead,
                                         no Bcc, and leave welcome_sent_at alone
    DRY_RUN=1 ...                        write the HTML to welcome-preview.html
"""
import html
import os
import smtplib
import ssl
import sys
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
ADVANCE_ID = (os.environ.get("ADVANCE_ID") or "").strip()
WELCOME_TO = (os.environ.get("WELCOME_TO") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
BOOKING = "booking@sisyphusbrewing.com"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

TRIP_URL = "https://www.sisyphusbrewing.com/pages/advance?s="
BADGE_URL = "https://cdn.shopify.com/s/files/1/0310/0669/files/sisyphus-badge-bluegray-dark-bg.png?v=1791819264&width=240"

BG, CARD, LINE, SLATE, SLATE_LIGHT, GRAY, PAPER = "#2b2929", "#393636", "#4a4646", "#4a6c86", "#a9c3d8", "#918f90", "#f4f1ea"
HEAD = "'Josefin Sans','Century Gothic',Futura,Arial,sans-serif"
BODY = "'Assistant',-apple-system,'Segoe UI',Roboto,Arial,sans-serif"


def fetch():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/advances", params={"id": f"eq.{ADVANCE_ID}", "select": "*"},
                     headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"No advance with id {ADVANCE_ID}")
    return rows[0]


def mark_sent():
    requests.patch(f"{SUPABASE_URL}/rest/v1/advances", params={"id": f"eq.{ADVANCE_ID}"},
                   headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                            "Content-Type": "application/json", "Prefer": "return=minimal"},
                   json={"welcome_sent_at": datetime.now(timezone.utc).isoformat()}, timeout=30).raise_for_status()


def show_day(d):
    return date.fromisoformat(d) if d else None


def date_range(start, end):
    """'Thursday, October 22' or, for a run, 'Thu–Sat, October 22–24'."""
    if not start:
        return ""
    if not end or end <= start:
        return start.strftime("%A, %B %-d")
    days = f"{start:%a}–{end:%a}"
    if start.month == end.month:
        return f"{days}, {start:%B %-d}–{end:%-d}"
    return f"{days}, {start:%b %-d} – {end:%b %-d}"


def short_range(start, end):
    """For the subject line: 'Oct 22' or 'Oct 22–24'."""
    if not end or end <= start:
        return start.strftime("%b %-d")
    return f"{start:%b %-d}–{end:%-d}" if start.month == end.month else f"{start:%b %-d} – {end:%b %-d}"


def build(a):
    """The email, in Sam's voice: short, first person, one dry joke."""
    esc = html.escape
    first = (a.get("contact_name") or "").split(" ")[0]
    day = show_day(a.get("show_date"))
    last = show_day(a.get("show_end_date"))
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    days = (day - today).days if day else None
    when = date_range(day, last) or "Date to come"
    url = TRIP_URL + a["token"]
    count = "" if days is None or days < 0 else "Tonight." if days == 0 else "Tomorrow." if days == 1 else f"{days} days out"
    hey = f"Hey {first}," if first else "Hey there,"
    stretch = "weekend" if day and last and last > day else "night"

    def p(text, top=16, size=17, color="#ffffff"):
        return (f'<tr><td style="padding:{top}px 30px 0;font-family:{BODY};font-size:{size}px;line-height:1.5;color:{color}">{text}</td></tr>')

    perks = ["A green room stocked how you like it", "Security handled your way",
             "Guest sets for your funny friends", "100% of the door. Since day one."]
    perk_rows = "".join(
        f'<tr><td style="padding:9px 0;border-top:1px solid {LINE};font-family:{BODY};font-size:16px;font-weight:600;color:#ffffff">{esc(t)}</td></tr>'
        for t in perks)
    count_row = (f'<tr><td style="border-top:1px dashed #c9c3b6;padding:12px 0 0;font-family:{HEAD};font-size:20px;font-weight:700;'
                 f'letter-spacing:1px;text-transform:uppercase;color:{SLATE}">{esc(count)}</td></tr>') if count else ""

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@600;700&family=Assistant:wght@400;600;700&display=swap" rel="stylesheet">
<title>You're booked at Sisyphus</title></head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden">Congrats. A few quick questions before the show.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:{CARD};border-radius:16px">
  <tr><td align="center" style="padding:26px 24px 0"><img src="{BADGE_URL}" width="88" alt="Sisyphus" style="display:block;border:0;width:88px;height:auto"></td></tr>
  <tr><td style="padding:22px 30px 0">
    <span style="display:inline-block;background:{SLATE};color:#ffffff;padding:8px 16px 5px;font-family:{HEAD};font-weight:700;font-size:13px;letter-spacing:3px;text-transform:uppercase">You're booked</span>
  </td></tr>
  {p(esc(hey), 20)}
  {p("Congrats, you're playing Sisyphus, “The Disney World of Comedy.” (Smaller. Way better beer.)", 10)}
  <tr><td style="padding:20px 30px 0">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};border-radius:12px">
      <tr><td style="padding:18px 20px 16px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="font-family:{HEAD};font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:{SLATE}">Admit one comedian</td></tr>
          <tr><td style="padding:8px 0 2px;font-family:{HEAD};font-size:28px;line-height:1.1;font-weight:700;text-transform:uppercase;color:#2b2929">{esc(a['show_name'])}</td></tr>
          <tr><td style="font-family:{BODY};font-size:17px;font-weight:700;color:#2b2929">{esc(when)}</td></tr>
          <tr><td style="padding:2px 0 12px;font-family:{BODY};font-size:15px;color:#5d5959">712 Ontario Ave W, Minneapolis</td></tr>
          {count_row}
        </table>
      </td></tr>
    </table>
  </td></tr>
  {p(f"I just want to make sure your {stretch} goes according to plan: the green room, security, your guests and how you want to get paid. Just a few quick questions - mostly tapping, very little typing.", 22)}
  <tr><td style="padding:22px 30px 4px">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr><td align="center" bgcolor="{SLATE}" style="border-radius:10px">
      <a href="{esc(url)}" style="display:inline-block;padding:16px 30px 13px;font-family:{HEAD};font-size:16px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ffffff;text-decoration:none;border-radius:10px">Plan your night</a>
    </td></tr></table>
  </td></tr>
  <tr><td style="padding:24px 30px 0;font-family:{HEAD};font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:{SLATE_LIGHT}">What you get</td></tr>
  <tr><td style="padding:8px 30px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{perk_rows}</table></td></tr>
  {p("Questions? Just reply.", 20, 16, "#d9d6d6")}
  {p("See you at the show. Cheers!<br>-Sam", 16)}
  <tr><td align="center" style="padding:28px 24px 26px;font-family:Georgia,serif;font-style:italic;font-size:15px;color:{SLATE_LIGHT}">Il faut imaginer Sisyphe heureux.</td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
  <tr><td align="center" style="padding:14px 24px 0;font-family:{BODY};font-size:13px;line-height:1.5;color:{GRAY}">
    Sisyphus · Comedy &amp; Beer · 712 Ontario Ave W, Minneapolis<br>
    <a href="{esc(url)}" style="color:{GRAY}">{esc(url)}</a></td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = "\n".join(x for x in [
        hey,
        "",
        "Congrats, you're playing Sisyphus, “The Disney World of Comedy.” (Smaller. Way better beer.)",
        "",
        a["show_name"],
        when,
        "712 Ontario Ave W, Minneapolis",
        count,
        "",
        f"I just want to make sure your {stretch} goes according to plan: the green room, security, your guests",
        "and how you want to get paid. Just a few quick questions - mostly tapping, very little typing:",
        url,
        "",
        "What you get: a green room stocked how you like it, security handled your way,",
        "guest sets for your funny friends, and 100% of the door. Since day one.",
        "",
        "Questions? Just reply.",
        "",
        "See you at the show. Cheers!",
        "-Sam",
    ] if x is not None)
    subject = f"You're booked at Sisyphus: {a['show_name']}" + (f", {short_range(day, last)}" if day else "")
    return subject, body, text


def main():
    if not ADVANCE_ID:
        sys.exit("ADVANCE_ID is required")
    a = fetch()
    to = WELCOME_TO or (a.get("contact_email") or "").strip()
    if not to:
        sys.exit(f"No email on the advance for {a['show_name']}. Add one on the booking desk.")
    recipients = [x.strip() for x in to.replace(";", ",").split(",") if x.strip()]
    subject, body, text = build(a)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Sam at Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = BOOKING
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(body, "html"))
    bcc = [] if WELCOME_TO else [BOOKING]

    if DRY_RUN:
        with open("welcome-preview.html", "w", encoding="utf-8") as f:
            f.write(body)
        print(f"[DRY RUN] '{subject}' to {recipients} (bcc {bcc}); HTML in welcome-preview.html")
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, recipients + bcc, msg.as_string())
    print(f"Sent '{subject}' to {', '.join(recipients)}" + (" (preview)" if WELCOME_TO else ""))
    if not WELCOME_TO:
        mark_sent()


if __name__ == "__main__":
    main()
