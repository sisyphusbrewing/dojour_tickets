import os
import smtplib
import ssl
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

# Force Gmail Port 465 direct SSL to avoid cloud runner disconnects
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
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
