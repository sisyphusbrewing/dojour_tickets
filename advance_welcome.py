"""
Sisyphus - the welcome email a comedian gets when they are booked.

The "Comedian welcome" action runs this from the booking desk's "Send the
welcome" button. It reads the advance from Supabase with the service key and
sends the comedian (advances.contact_email) an excited, kid-going-to-Disney
email whose big button opens their trip: the advance, one playful stop at a
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

NIGHT, NIGHT2, SLATE, SLATE_LIGHT, GOLD, CREAM = "#16222e", "#24384a", "#4a6c86", "#a9c3d8", "#f5c451", "#fff3cf"
FUN = "'Fredoka','Arial Rounded MT Bold','Trebuchet MS',Arial,sans-serif"
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


def build(a):
    esc = html.escape
    first = (a.get("contact_name") or "").split(" ")[0]
    day = show_day(a.get("show_date"))
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    sleeps = (day - today).days if day else None
    when = " · ".join(x for x in (day.strftime("%A, %B %-d") if day else "", a.get("show_time") or "") if x) or "Date to come"
    url = TRIP_URL + a["token"]

    if sleeps is None or sleeps < 0:
        count = ""
    elif sleeps == 0:
        count = "It's tonight!"
    else:
        count = f"{sleeps} sleep{'s' if sleeps != 1 else ''} until showtime"

    perks = [("🍿", "A green room stocked with whatever you tell us"),
             ("🍺", "Beer we brew ourselves, on tap all night"),
             ("🛡️", "Security the way you like it"),
             ("🎁", "Guest sets to hand out to your funny friends"),
             ("💸", "100% of the door. Still true.")]
    perk_rows = "".join(
        f'<tr><td style="padding:6px 0;width:40px;font-size:26px;line-height:1;vertical-align:middle">{e}</td>'
        f'<td style="padding:6px 0;font-family:{BODY};font-size:17px;font-weight:600;color:#ffffff;vertical-align:middle">{esc(t)}</td></tr>'
        for e, t in perks)
    count_row = (f'<tr><td style="border-top:2px dashed #d8c48e;padding:14px 0 0;font-family:{FUN};font-size:26px;font-weight:700;color:{SLATE}">'
                 f'{esc(count)}</td></tr>') if count else ""

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@600;700&family=Assistant:wght@400;600;700&display=swap" rel="stylesheet">
<title>You're coming to Sisyphus</title></head>
<body style="margin:0;padding:0;background:{NIGHT}">
<div style="display:none;max-height:0;overflow:hidden">Pack your bags. Welcome to the Disney World of Comedy. 🎉</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{NIGHT}">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:{NIGHT2};border-radius:22px">
  <tr><td align="center" style="padding:28px 24px 0;font-size:22px;letter-spacing:10px;color:{GOLD}">✦ ✧ ✦ ✧ ✦</td></tr>
  <tr><td align="center" style="padding:14px 24px 0"><img src="{BADGE_URL}" width="96" alt="Sisyphus" style="display:block;border:0;width:96px;height:auto"></td></tr>
  <tr><td align="center" style="padding:18px 24px 0;font-family:{FUN};font-size:20px;font-weight:600;color:{SLATE_LIGHT}">{esc('Pack your bags, ' + first + '!' if first else 'Pack your bags!')}</td></tr>
  <tr><td align="center" style="padding:6px 24px 0;font-family:{FUN};font-size:38px;line-height:1.1;font-weight:700;color:{GOLD}">You're coming to Sisyphus! 🎉</td></tr>
  <tr><td align="center" style="padding:12px 30px 0;font-family:{BODY};font-size:18px;line-height:1.45;color:#dbe5ee">Welcome to the Disney World of Comedy. Congratulations. You earned this.</td></tr>
  <tr><td style="padding:24px 24px 0">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CREAM};border-radius:18px">
      <tr><td style="padding:20px 22px 18px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="font-family:{BODY};font-size:12px;font-weight:700;letter-spacing:4px;text-transform:uppercase;color:{SLATE}">Admit one comedian · and a few friends</td></tr>
          <tr><td style="padding:8px 0 2px;font-family:{FUN};font-size:32px;line-height:1.1;font-weight:700;color:#2b2929">{esc(a['show_name'])}</td></tr>
          <tr><td style="font-family:{BODY};font-size:17px;font-weight:700;color:#2b2929">{esc(when)}</td></tr>
          <tr><td style="padding:2px 0 14px;font-family:{BODY};font-size:15px;color:#5d5959">712 Ontario Ave W, Minneapolis</td></tr>
          {count_row}
        </table>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:26px 30px 0;font-family:{FUN};font-size:22px;font-weight:600;color:#ffffff">Here's what's waiting for you</td></tr>
  <tr><td style="padding:8px 30px 0"><table role="presentation" cellpadding="0" cellspacing="0">{perk_rows}</table></td></tr>
  <tr><td style="padding:22px 30px 0;font-family:{BODY};font-size:17px;line-height:1.5;color:#dbe5ee">
    Before you get here, we plan your whole night: the poster, the green room, security, your guest list and how you get paid.
    It's a quick trip up the hill. Tap, tap, done.</td></tr>
  <tr><td align="center" style="padding:26px 24px 6px">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr><td align="center" bgcolor="{GOLD}" style="border-radius:999px;border-bottom:5px solid #a87d12">
      <a href="{esc(url)}" style="display:inline-block;padding:18px 38px;font-family:{FUN};font-size:21px;font-weight:700;color:#2a2208;text-decoration:none;border-radius:999px">Plan my trip 🎢</a>
    </td></tr></table>
  </td></tr>
  <tr><td align="center" style="padding:8px 30px 0;font-family:{BODY};font-size:14px;color:{SLATE_LIGHT}">It saves as you go. Skip anything you like.</td></tr>
  <tr><td style="padding:28px 30px 0;font-family:{BODY};font-size:17px;line-height:1.5;color:#ffffff">See you at the top of the hill,<br><b>Grace &amp; Sam</b></td></tr>
  <tr><td style="padding:6px 30px 0;font-family:{BODY};font-size:14px;line-height:1.5;color:{SLATE_LIGHT}">Questions? Just reply. It comes straight to us.</td></tr>
  <tr><td align="center" style="padding:28px 24px 0;font-size:18px;letter-spacing:10px;color:{GOLD}">✧ ✦ ✧</td></tr>
  <tr><td align="center" style="padding:10px 24px 26px;font-family:Georgia,serif;font-style:italic;font-size:15px;color:{SLATE_LIGHT}">Il faut imaginer Sisyphe heureux.</td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
  <tr><td align="center" style="padding:14px 24px 0;font-family:{BODY};font-size:13px;line-height:1.5;color:#8ea3b5">
    Sisyphus · Comedy &amp; Beer · 712 Ontario Ave W, Minneapolis<br>
    <a href="{esc(url)}" style="color:#8ea3b5">{esc(url)}</a></td></tr>
</table>
</td></tr></table>
</body></html>"""

    text = "\n".join([
        f"Pack your bags{', ' + first if first else ''}! You're coming to Sisyphus!",
        "",
        "Welcome to the Disney World of Comedy. Congratulations. You earned this.",
        "",
        f"{a['show_name']}",
        when,
        "712 Ontario Ave W, Minneapolis",
        count,
        "",
        "Waiting for you: a green room stocked with whatever you tell us, beer we brew ourselves,",
        "security the way you like it, guest sets for your funny friends, and 100% of the door.",
        "",
        "Plan your trip (the poster, the green room, security, guest list, getting paid):",
        url,
        "",
        "See you at the top of the hill,",
        "Grace & Sam",
        "Sisyphus · 712 Ontario Ave W, Minneapolis",
    ])
    subject = f"🎉 You're coming to Sisyphus{', ' + first if first else ''}!"
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
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
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
