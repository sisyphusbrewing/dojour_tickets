import os
import smtplib
import re
from datetime import datetime
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

SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT") or 465)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").replace(" ", "").strip()
FROM_EMAIL = os.environ.get("FROM_EMAIL") or SMTP_USER
FROM_NAME = "Sisyphus Brewing Box Office"

MONTH_MAP = {
    'jan': 0, 'feb': 1, 'mar': 2, 'apr': 3, 'may': 4, 'jun': 5,
    'jul': 6, 'aug': 7, 'sep': 8, 'oct': 9, 'nov': 10, 'dec': 11
}

def parse_date_to_timestamp(date_str):
    if not date_str:
        return 0
    now = datetime.now()
    m_match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', date_str, re.I)
    d_match = re.search(r'\b(\d{1,2})\b', date_str)
    y_match = re.search(r'\b(202\d)\b', date_str)
    t_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', date_str, re.I)

    if not m_match or not d_match:
        return 0

    month = MONTH_MAP[m_match.group(1).lower()[:3]]
    day = int(d_match.group(1))
    year = int(y_match.group(1)) if y_match else now.year

    hour = 19
    minute = 0
    if t_match:
        hour = int(t_match.group(1))
        minute = int(t_match.group(2)) if t_match.group(2) else 0
        ampm = t_match.group(3).upper()
        if ampm == 'PM' and hour < 12: hour += 12
        if ampm == 'AM' and hour == 12: hour = 0

    if not y_match and month < (now.month - 1) and (now.month - 1 - month) >= 8:
        year += 1

    try:
        return datetime(year, month + 1, day, hour, minute).timestamp()
    except Exception:
        return 0

def fetch_supabase(endpoint):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/{endpoint}", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch {endpoint} ({resp.status_code}): {resp.text}")
        return []
    return resp.json()

def build_email_html(agent_email, comedian_name, shows, total_sold):
    rows_html = ""
    for s in shows:
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{s['show_date']}</td>
          <td style="padding: 10px 12px; text-align: center; color: #475569;">{s['website_tickets']}</td>
          <td style="padding: 10px 12px; text-align: center; color: #475569;">{s['dojour_tickets']}</td>
          <td style="padding: 10px 12px; text-align: right; font-weight: 700; color: #0f172a;">{s['total']}</td>
        </tr>
        """

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
            Here is the consolidated weekly ticket count for <strong>{comedian_name}</strong> at Sisyphus Brewing as of {datetime.now().strftime('%B %d, %Y')}:
          </p>

          <table>
            <thead>
              <tr>
                <th>Show Date & Time</th>
                <th style="text-align: center;">Website</th>
                <th style="text-align: center;">Dojour</th>
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
        </div>
        <div class="footer">
          Sisyphus Brewing • 712 Ontario Ave W, Minneapolis, MN<br>
          Questions? Reply directly to this email.
        </div>
      </div>
    </body>
    </html>
    """

def send_email(to_email, subject, html_content):
    if not SMTP_USER or not SMTP_PASS:
        print(f"⚠️ SMTP credentials missing. Dry-run mode for {to_email}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))

    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(FROM_EMAIL, [to_email], msg.as_string())

        print(f"✓ Sent consolidated report to {to_email}")
    except smtplib.SMTPServerDisconnected as e:
        print(f"❌ Connection closed by server: {e}")
        print("👉 Reminder: Ensure you are using a 16-character Google App Password (not your normal Gmail password).")
        raise e
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        print("👉 Reminder: Check SMTP_USER and SMTP_PASS. An App Password is required when 2-Step Verification is active.")
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

    now_ts = datetime.now().timestamp()
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
                "total": 0
            }

        count = int(t.get("tickets") or 1)
        shows_map[key]["total"] += count
        if t.get("source") == "Website":
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

    for agent_email, comedian_dict in consolidated.items():
        for comedian_name, shows in comedian_dict.items():
            shows.sort(key=lambda x: x["timestamp"] or 0)
            run_total = sum(s["total"] for s in shows)

            subject = f"Weekly Ticket Count: {comedian_name} ({len(shows)} Shows) - Sisyphus Brewing"
            html_body = build_email_html(agent_email, comedian_name, shows, run_total)

            print(f"Sending email for '{comedian_name}' ({len(shows)} showtimes, {run_total} total tickets) to {agent_email}...")
            send_email(agent_email, subject, html_body)

    print("=" * 60)
    print("✓ All agent updates dispatched successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
