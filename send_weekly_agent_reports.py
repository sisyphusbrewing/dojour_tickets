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
FROM_NAME = "Sisyphus Brewing Box Office"
REPLY_TO = (os.environ.get("REPLY_TO_EMAIL") or FROM_EMAIL).strip()

# Set DRY_RUN=1 to print what would be sent without emailing anyone.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

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


def build_email_html(agent_email, comedian_name, shows, total_sold, total_comps=0):
    comedian_name = html.escape(comedian_name)
    rows_html = ""
    for s in shows:
        comp_cell = (f'<td style="padding: 10px 12px; text-align: center; color: #475569;">{s["comp_tickets"]}</td>'
                     if total_comps else "")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{html.escape(s['show_date'])}</td>
          <td style="padding: 10px 12px; text-align: center; color: #475569;">{s['website_tickets']}</td>
          <td style="padding: 10px 12px; text-align: center; color: #475569;">{s['dojour_tickets']}</td>
          {comp_cell}
          <td style="padding: 10px 12px; text-align: right; font-weight: 700; color: #0f172a;">{s['total']}</td>
        </tr>
        """

    comp_header = '<th style="text-align: center;">Comps</th>' if total_comps else ""
    comp_note = (f'<p style="font-size: 12px; color: #64748b; margin-top: 12px;">'
                 f'Plus {total_comps} comp ticket{"s" if total_comps != 1 else ""}, not included in tickets sold.</p>'
                 if total_comps else "")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; }}
        .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.04); }}
        .header {{ background-color: #0f172a; padding: 24px; color: #ffffff; }}
        .title {{ font-size: 20px; font-weight: 800; margin: 0; color: #fbbf24; }}
        .subtitle {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
        .content {{ padding: 24px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }}
        th {{ background-color: #f1f5f9; padding: 10px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }}
        .total-box {{ background-color: #fef3c7; border: 1px solid #fde68a; border-radius: 8px; padding: 16px; margin-top: 20px; text-align: right; }}
        .footer {{ padding: 16px 24px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h1 class="title">Weekly Ticket Count Update</h1>
          <div class="subtitle">{comedian_name} • Sisyphus Brewing</div>
        </div>
        <div class="content">
          <p style="margin-top: 0; color: #334155; font-size: 14px; line-height: 1.5;">
            Hi,
            <br><br>
            Here is the consolidated weekly ticket count for <strong>{comedian_name}</strong> at Sisyphus Brewing as of {datetime.now(CENTRAL_TZ).strftime('%B %-d, %Y')}:
          </p>

          <table>
            <thead>
              <tr>
                <th>Show Date & Time</th>
                <th style="text-align: center;">Website</th>
                <th style="text-align: center;">Dojour</th>
                {comp_header}
                <th style="text-align: right;">Total Sold</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>

          <div class="total-box">
            <span style="font-size: 12px; text-transform: uppercase; font-weight: 700; color: #92400e;">Total Tickets Sold</span>
            <div style="font-size: 26px; font-weight: 900; color: #78350f; margin-top: 2px;">{total_sold}</div>
          </div>
          {comp_note}
        </div>
        <div class="footer">
          Sisyphus Brewing • 712 Ontario Ave W, Minneapolis, MN<br>
          Questions? Reply directly to this email.
        </div>
      </div>
    </body>
    </html>
    """

def build_email_text(comedian_name, shows, total_sold, total_comps=0):
    lines = [f"Hi,", "", f"Here is the weekly ticket count for {comedian_name} at Sisyphus Brewing "
             f"as of {datetime.now(CENTRAL_TZ).strftime('%B %-d, %Y')}:", ""]
    for s in shows:
        comp = f", {s['comp_tickets']} comps" if s["comp_tickets"] else ""
        lines.append(f"- {s['show_date']}: {s['total']} sold (Website {s['website_tickets']}, Dojour {s['dojour_tickets']}{comp})")
    lines += ["", f"Total tickets sold: {total_sold}"]
    if total_comps:
        lines.append(f"Plus {total_comps} comp tickets (not included in tickets sold).")
    lines += ["", "Questions? Reply directly to this email.", "", "Sisyphus Brewing", "712 Ontario Ave W, Minneapolis, MN"]
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
            subject = f"Weekly Ticket Count: {comedian_name} ({len(shows)} {show_word}) - Sisyphus Brewing"
            html_body = build_email_html(agent_email, comedian_name, shows, run_total, run_comps)
            text_body = build_email_text(comedian_name, shows, run_total, run_comps)

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
