import os
import html
import smtplib
import ssl
import re
from datetime import datetime, timedelta
import zoneinfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict
import requests

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
RAW_SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co"
SUPABASE_URL = RAW_SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

# Force Gmail Port 465 direct SSL to avoid cloud runner disconnects
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
FROM_NAME = "Sisyphus Box Office"
REPLY_TO = (os.environ.get("REPLY_TO_EMAIL") or FROM_EMAIL).strip()

# Set DRY_RUN=1 to print what would be sent without emailing anyone.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

# Set AGENT_TOKEN to send one agent's report now (the "Send me today's numbers"
# button on their page goes through the agent-report function to do this).
AGENT_TOKEN = (os.environ.get("AGENT_TOKEN") or "").strip()
REPORT_PAGE = "https://www.sisyphusbrewing.com/pages/report"

# GitHub runners are on UTC; show times are Minneapolis time.
CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")

MONTH_MAP = {
    'jan': 0, 'feb': 1, 'mar': 2, 'apr': 3, 'may': 4, 'jun': 5,
    'jul': 6, 'aug': 7, 'sep': 8, 'oct': 9, 'nov': 10, 'dec': 11
}

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_date_to_timestamp(date_str):
    """
    "Sat, Apr 3 • 7:00 PM" -> timestamp. When no year is written, the weekday
    decides it (Apr 3 is a Saturday in 2027, not 2026), matching the door app.
    """
    if not date_str:
        return 0
    now = datetime.now(CENTRAL_TZ)

    md = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b', date_str, re.I)
    if not md:
        return 0
    month = MONTH_MAP[md.group(1).lower()[:3]] + 1
    day = int(md.group(2))

    hour, minute = 19, 0
    tm = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', date_str, re.I)
    if tm:
        hour = int(tm.group(1)) % 12
        minute = int(tm.group(2)) if tm.group(2) else 0
        if tm.group(3).lower() == "pm":
            hour += 12

    ym = re.search(r'\b(20\d{2})\b', date_str)
    if ym:
        try:
            return datetime(int(ym.group(1)), month, day, hour, minute, tzinfo=CENTRAL_TZ).timestamp()
        except ValueError:
            return 0

    candidates = []
    for y in (now.year - 1, now.year, now.year + 1):
        try:
            candidates.append(datetime(y, month, day, hour, minute, tzinfo=CENTRAL_TZ))
        except ValueError:
            pass
    wd = re.match(r'\s*(Sun|Mon|Tue|Wed|Thu|Fri|Sat)', date_str, re.I)
    if wd:
        target = WEEKDAYS[wd.group(1).lower()]
        matching = [c for c in candidates if c.weekday() == target]
        if matching:
            candidates = matching
    if not candidates:
        return 0

    floor = now - timedelta(days=60)
    upcoming = [c for c in candidates if c >= floor]
    return (min(upcoming) if upcoming else max(candidates)).timestamp()


def fetch_supabase(endpoint):
    """GET every row for a PostgREST query, paging past Supabase's 1000-row cap."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    rows, page_size, offset = [], 1000, 0
    sep = "&" if "?" in endpoint else "?"
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{endpoint}{sep}limit={page_size}&offset={offset}"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"Failed to fetch {endpoint} ({resp.status_code}): {resp.text}")
            return rows
        page = resp.json() or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def agent_links(token):
    """The two things an agent can do from the email, as (label, url)."""
    if not token:
        return []
    return [("Send me today's numbers", f"{REPORT_PAGE}?t={token}&do=now"),
            ("Change who gets this", f"{REPORT_PAGE}?t={token}")]


BADGE_URL = "https://cdn.shopify.com/s/files/1/0310/0669/files/sisyphus-badge-bluegray-dark-bg.png?v=1791819264&width=240"
HEAD_FONT = "'Josefin Sans', 'Century Gothic', Futura, 'Trebuchet MS', Helvetica, Arial, sans-serif"
BODY_FONT = "Assistant, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def band(title):
    """The site's slate band heading, the email-safe way (no transforms)."""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin: 22px 0 10px;"><tr><td '
            f'style="background-color: #4a6c86; border-top: 2px solid #ffffff; border-bottom: 2px solid #ffffff; '
            f'padding: 8px 16px 6px; font-family: {HEAD_FONT}; font-weight: 700; font-size: 13px; letter-spacing: 3px; '
            f'text-transform: uppercase; color: #ffffff;">{html.escape(title)}</td></tr></table>')


def build_email_html(agent_email, comedian_name, shows, total_sold, total_comps=0, token=""):
    """The weekly (or on-demand) count, styled like sisyphusbrewing.com: charcoal, slate blue, band headings."""
    comedian_name = html.escape(comedian_name)
    cell = 'padding: 10px 12px; font-size: 15px; color: #ffffff; border-bottom: 1px solid #4a4646;'
    rows_html = ""
    for s in shows:
        comp_cell = f'<td style="{cell} text-align: center; color: #d9d6d6;">{s["comp_tickets"]}</td>' if total_comps else ""
        day, _, time = s["show_date"].partition("•")
        when_cell = (f'<span style="white-space: nowrap;">{html.escape(day.strip())}</span>'
                     + (f'<br><span style="white-space: nowrap; font-weight: 400; color: #a9c3d8;">{html.escape(time.strip())}</span>' if time.strip() else ""))
        rows_html += (f'<tr><td style="{cell} font-weight: 600;">{when_cell}</td>'
                      f'<td style="{cell} text-align: center; color: #d9d6d6;">{s["website_tickets"]}</td>'
                      f'<td style="{cell} text-align: center; color: #d9d6d6;">{s["dojour_tickets"]}</td>'
                      f'{comp_cell}'
                      f'<td style="{cell} text-align: right; font-weight: 700;">{s["total"]}</td></tr>')

    th = (f'padding: 0 12px 8px; font-family: {HEAD_FONT}; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; '
          f'text-transform: uppercase; color: #a9c3d8; border-bottom: 1px solid #4a4646;')
    comp_header = f'<th style="{th} text-align: center;">Comps</th>' if total_comps else ""
    comp_note = (f'<p style="margin: 10px 0 0; font-size: 13px; color: #918f90;">Plus {total_comps} comp '
                 f'ticket{"s" if total_comps != 1 else ""}, not counted as sold.</p>' if total_comps else "")

    links = agent_links(token)
    buttons = ""
    for i, (label, url) in enumerate(links):
        primary = i == 0
        buttons += (f'<a href="{html.escape(url)}" style="display: inline-block; margin: 8px 8px 0 0; padding: 12px 18px 10px; '
                    f'border-radius: 10px; background-color: {"#4a6c86" if primary else "#2b2929"}; '
                    f'color: #ffffff; border: 1px solid {"#4a6c86" if primary else "#918f90"}; font-family: {HEAD_FONT}; '
                    f'font-weight: 700; font-size: 13px; letter-spacing: 1px; text-transform: uppercase; text-decoration: none;">'
                    f'{html.escape(label)}</a>')
    buttons_block = ""
    if buttons:
        buttons_block = (band("Need something") +
                         f'<p style="margin: 0; font-size: 15px; color: #d9d6d6;">Numbers sooner than Monday, or a different inbox for these? Help yourself.</p>'
                         f'{buttons}'
                         f'<p style="margin: 12px 0 0; font-size: 12px; color: #918f90;">These links are yours alone. Please do not forward them.</p>')

    when = datetime.now(CENTRAL_TZ).strftime('%B %-d, %Y at %-I:%M %p').replace(" AM", " am").replace(" PM", " pm")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Ticket count: {comedian_name}</title></head>
<body style="margin: 0; padding: 24px 12px; background-color: #393636; font-family: {BODY_FONT};">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; margin: 0 auto; background-color: #2b2929; border: 1px solid #4a4646; border-radius: 14px;">
    <tr><td style="padding: 24px 24px 18px; border-bottom: 1px solid #4a4646;">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="padding-right: 16px; vertical-align: middle;"><img src="{BADGE_URL}" width="72" height="72" alt="Sisyphus" style="display: block; width: 72px; height: 72px; border: 0;"></td>
        <td style="vertical-align: middle;">
          <div style="font-family: {HEAD_FONT}; font-weight: 700; font-size: 22px; letter-spacing: 2px; text-transform: uppercase; color: #ffffff; line-height: 1.1;">Ticket count</div>
          <div style="margin-top: 4px; font-size: 14px; color: #a9c3d8;">{comedian_name} &middot; Sisyphus, Minneapolis</div>
        </td>
      </tr></table>
    </td></tr>
    <tr><td style="padding: 8px 24px 24px;">
      <p style="margin: 14px 0 0; font-size: 16px; line-height: 1.5; color: #ffffff;">Hi,<br><br>Here is where <strong>{comedian_name}</strong> stands as of {when}.</p>
      {band("The numbers")}
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
        <thead><tr>
          <th style="{th} text-align: left;">Show</th>
          <th style="{th} text-align: center;">Website</th>
          <th style="{th} text-align: center;">Dojour</th>
          {comp_header}
          <th style="{th} text-align: right;">Sold</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 16px;"><tr>
        <td style="background-color: #4a6c86; border-radius: 10px; padding: 14px 18px; text-align: right;">
          <div style="font-family: {HEAD_FONT}; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: #ffffff;">Total sold</div>
          <div style="font-family: {HEAD_FONT}; font-size: 32px; font-weight: 700; color: #ffffff; line-height: 1.1; margin-top: 2px;">{total_sold}</div>
        </td>
      </tr></table>
      {comp_note}
      <p style="margin: 10px 0 0; font-size: 12px; color: #918f90;">Website sales are live as of this email. Dojour sales update once a day.</p>
      {buttons_block}
    </td></tr>
    <tr><td style="padding: 16px 24px 20px; border-top: 1px solid #4a4646; font-size: 12px; line-height: 1.6; color: #918f90; text-align: center;">
      Sisyphus &middot; 712 Ontario Ave W, Minneapolis, MN &middot; Reply to this email with questions.<br>
      <span style="font-style: italic;">&laquo; Il faut imaginer Sisyphe heureux. &raquo;</span>
    </td></tr>
  </table>
</body>
</html>
"""


def build_email_text(comedian_name, shows, total_sold, total_comps=0, token=""):
    lines = [f"Hi,", "", f"Here is where {comedian_name} at Sisyphus stands "
             f"as of {datetime.now(CENTRAL_TZ).strftime('%B %-d, %Y')}:", ""]
    for s in shows:
        comp = f", {s['comp_tickets']} comps" if s["comp_tickets"] else ""
        lines.append(f"- {s['show_date']}: {s['total']} sold (Website {s['website_tickets']}, Dojour {s['dojour_tickets']}{comp})")
    lines += ["", f"Total tickets sold: {total_sold}"]
    if total_comps:
        lines.append(f"Plus {total_comps} comp tickets (not included in tickets sold).")
    for label, url in agent_links(token):
        lines += ["", f"{label}: {url}"]
    lines += ["", "Questions? Reply directly to this email.", "", "Sisyphus", "712 Ontario Ave W, Minneapolis, MN"]
    return "\n".join(lines)


def send_email(to_email, subject, html_content, text_content=""):
    if not DRY_RUN and (not SMTP_USER or not SMTP_PASS):
        raise RuntimeError("SMTP credentials missing (SMTP_USER / SMTP_PASS).")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO
    if text_content:
        msg.attach(MIMEText(text_content, "plain"))   # plain first, HTML last = preferred
    msg.attach(MIMEText(html_content, "html"))

    if DRY_RUN:
        print(f"[DRY RUN] Would send '{subject}' to {to_email}")
        print(text_content)
        return

    print(f"Connecting to {SMTP_HOST}:465 via direct SSL...")
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=context, timeout=30) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        print(f"✓ Sent consolidated report to {to_email}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        print("👉 Verification needed: Ensure SMTP_PASS is a 16-character Google App Password (not your primary Gmail password).")
        raise e
    except smtplib.SMTPServerDisconnected as e:
        print(f"❌ Connection disconnected: {e}")
        raise e
    except Exception as e:
        print(f"❌ Unexpected SMTP Error on Port 465: {e}")
        raise e

def main():
    print("=" * 60)
    print("SISYPHUS BREWING • WEEKLY AGENT TICKET REPORT DISPATCHER")
    print("=" * 60)

    # 1. Fetch agent directory
    agent_records = fetch_supabase("show_agents?select=*")
    if AGENT_TOKEN:
        agent_records = [r for r in agent_records if r.get("token") == AGENT_TOKEN]
        print(f"On-demand report for one agent ({len(agent_records)} record).")
    token_map = {r["show_title"].strip(): r.get("token") or "" for r in agent_records}
    agent_map = {r["show_title"].strip(): r["agent_email"].strip() for r in agent_records if r.get("agent_email")}
    print(f"Loaded {len(agent_map)} agent email assignment(s) from Supabase.")

    # 2. Fetch all ticket sales
    tickets = fetch_supabase("tickets?select=show_date,show_title,tickets,source")
    if not tickets:
        print("No ticket data found.")
        return

    now_ts = datetime.now(CENTRAL_TZ).timestamp()
    GRACE_PERIOD = 12 * 60 * 60

    shows_map = {}
    for t in tickets:
        date_str = (t.get("show_date") or "").strip()
        title_str = (t.get("show_title") or "").strip()
        if not date_str or not title_str:
            continue

        ts = parse_date_to_timestamp(date_str)
        if ts and ts < (now_ts - GRACE_PERIOD):
            continue

        key = (title_str, date_str)
        if key not in shows_map:
            shows_map[key] = {
                "show_title": title_str,
                "show_date": date_str,
                "timestamp": ts,
                "website_tickets": 0,
                "dojour_tickets": 0,
                "comp_tickets": 0,
                "total": 0
            }

        count = int(t.get("tickets") or 1)
        source = t.get("source")
        if source == "Comp":
            shows_map[key]["comp_tickets"] += count     # comps are not "sold"
            continue
        shows_map[key]["total"] += count
        if source == "Website":
            shows_map[key]["website_tickets"] += count
        else:
            shows_map[key]["dojour_tickets"] += count

    # 3. Consolidate by Agent -> Comedian -> Shows
    consolidated = defaultdict(lambda: defaultdict(list))

    for (title_str, date_str), sdata in shows_map.items():
        agent_email = agent_map.get(title_str)
        if not agent_email:
            continue
        consolidated[agent_email][title_str].append(sdata)

    if not consolidated:
        print("No upcoming shows found with assigned agent emails.")
        return

    print(f"Preparing consolidated reports for {len(consolidated)} agent(s)...")

    failures = []
    for agent_email, comedian_dict in consolidated.items():
        for comedian_name, shows in comedian_dict.items():
            shows.sort(key=lambda x: x["timestamp"] or 0)
            run_total = sum(s["total"] for s in shows)
            run_comps = sum(s["comp_tickets"] for s in shows)

            show_word = "Show" if len(shows) == 1 else "Shows"
            when = "Today's" if AGENT_TOKEN else "Weekly"
            subject = f"{when} Ticket Count: {comedian_name} ({len(shows)} {show_word}) - Sisyphus"
            token = token_map.get(comedian_name, "")
            html_body = build_email_html(agent_email, comedian_name, shows, run_total, run_comps, token)
            text_body = build_email_text(comedian_name, shows, run_total, run_comps, token)

            print(f"Sending email for '{comedian_name}' ({len(shows)} showtimes, {run_total} sold) to {agent_email}...")
            try:
                send_email(agent_email, subject, html_body, text_body)
            except Exception as e:
                # Keep going so one bad address doesn't block every other agent.
                failures.append((comedian_name, agent_email, str(e)))

    print("=" * 60)
    if failures:
        print(f"⚠️ {len(failures)} email(s) failed:")
        for name, addr, err in failures:
            print(f"   - {name} -> {addr}: {err}")
        print("=" * 60)
        raise SystemExit(1)   # marks the GitHub Action as failed so you get notified
    print("✓ All agent updates dispatched successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
