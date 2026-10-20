"""
Sisyphus - email a Sam's Tank pitch to booking.

Run by the "Sam's Tank pitch" action after someone pitches a show on
tank/index.html (sisyphusbrewing.com/pages/sams-tank). Reads the row from
Supabase with the service key, lays the answers out in the order of
tank/fields.js and sends it with the Gmail SMTP settings the other emails use.
Videos are too big to attach, so an uploaded one comes as a 30-day link.
Reply-To is the person pitching, so hitting reply answers them.

    PITCH_ID=<uuid> python tank_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it
"""
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
PITCH_ID = (os.environ.get("PITCH_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("TANK_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
REVIEW_URL = "https://staff.sisyphusbrewing.com/tank/review.html"
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def sections():
    """The question list from tank/fields.js: a JS file whose value is plain JSON."""
    with open(os.path.join(HERE, "tank", "fields.js"), encoding="utf-8") as f:
        src = f.read()
    return json.loads(src[src.index("TANK_SECTIONS = ") + 16:].strip().rstrip(";"))


def fetch_pitch():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/tank_pitches", params={"id": f"eq.{PITCH_ID}", "select": "*"},
                     headers=AUTH, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"No pitch with id {PITCH_ID}")
    return rows[0]


def video_link(path):
    """A 30-day signed link to an uploaded video in the private "tank" bucket."""
    r = requests.post(f"{SUPABASE_URL}/storage/v1/object/sign/tank/{path}", json={"expiresIn": 30 * 24 * 3600},
                      headers=AUTH, timeout=30)
    r.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1{r.json()['signedURL']}"


def main():
    if not PITCH_ID:
        sys.exit("PITCH_ID is required")
    p = fetch_pitch()
    data = p.get("data") or {}

    video = p.get("video_url")
    if p.get("video_path"):
        try:
            video = video_link(p["video_path"])
        except Exception as e:
            print(f"Could not sign the video link: {e}")
            video = f"(uploaded, in the Supabase 'tank' bucket at {p['video_path']})"

    lines = [f"{p['name']} pitched {p['show_name']} for Sam's Tank.", "", f"WATCH THE PITCH: {video}", ""]
    for s in sections():
        rows = []
        for f in s["fields"]:
            if f["k"] in ("video", "video_url"):
                continue
            v = data.get(f["k"])
            if v in (None, ""):
                continue
            v = str(v).strip()
            rows.append(f"  {f['label']}: " + ("\n    " + v.replace("\n", "\n    ") if "\n" in v else v))
        if rows:
            lines += [s["title"].upper()] + rows + [""]
    lines += [f"Every pitch, with notes and a winner pick: {REVIEW_URL}", "Hit reply to answer them.", "",
              "Sisyphus · 712 Ontario Ave W, Minneapolis"]

    msg = EmailMessage()
    msg["Subject"] = f"Sam's Tank pitch: {p['show_name']} · {p['name']}"
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    msg["Reply-To"] = p["email"]
    msg.set_content("\n".join(lines))

    if DRY_RUN:
        print(f"[DRY RUN] To: {TO}\nReply-To: {p['email']}\nSubject: {msg['Subject']}\n")
        print("\n".join(lines))
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"Sent '{msg['Subject']}' to {', '.join(TO)}")


if __name__ == "__main__":
    main()
