"""
Sisyphus - email a job application to booking.

Run by the "Job application" action after someone applies on jobs/index.html
(sisyphusbrewing.com/pages/jobs). Reads the row from Supabase with the service
key, lays the answers out in the order of jobs/fields.js, attaches the résumé
from the private "jobs" bucket and sends it with the Gmail SMTP settings the
other emails use. Reply-To is the applicant, so hitting reply answers them.

    APPLICATION_ID=<uuid> python job_notify.py
    DRY_RUN=1 ...   prints the email instead of sending it
"""
import json
import mimetypes
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
APPLICATION_ID = (os.environ.get("APPLICATION_ID") or "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("JOBS_EMAIL_TO") or "booking@sisyphusbrewing.com").split(",") if a.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def sections():
    """The question list from jobs/fields.js: a JS file whose value is plain JSON."""
    with open(os.path.join(HERE, "jobs", "fields.js"), encoding="utf-8") as f:
        src = f.read()
    return json.loads(src[src.index("JOB_SECTIONS = ") + 15:].strip().rstrip(";"))


def fetch_application():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/job_applications", params={"id": f"eq.{APPLICATION_ID}", "select": "*"},
                     headers=AUTH, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        sys.exit(f"No application with id {APPLICATION_ID}")
    return rows[0]


def main():
    if not APPLICATION_ID:
        sys.exit("APPLICATION_ID is required")
    a = fetch_application()
    data = a.get("data") or {}
    role = (a.get("role") or "bartender").title()

    lines = [f"{a['name']} applied for {role}.", ""]
    for s in sections():
        rows = []
        for f in s["fields"]:
            if f.get("type") == "file":
                if a.get("resume_path"):
                    rows.append(f"  {f['label'].replace(' (optional)', '')}: attached")
                continue
            v = data.get(f["k"])
            if v in (None, ""):
                continue
            v = str(v).strip()
            rows.append(f"  {f['label']}: " + ("\n    " + v.replace("\n", "\n    ") if "\n" in v else v))
        if rows:
            lines += [s["title"].upper()] + rows + [""]
    lines += ["Hit reply to answer them.", "", "Sisyphus · 712 Ontario Ave W, Minneapolis"]

    msg = EmailMessage()
    msg["Subject"] = f"{role} application: {a['name']}" + (f" · {data['experience']}" if data.get("experience") else "")
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    msg["Reply-To"] = a["email"]
    msg.set_content("\n".join(lines))

    if a.get("resume_path"):
        try:
            r = requests.get(f"{SUPABASE_URL}/storage/v1/object/jobs/{a['resume_path']}", headers=AUTH, timeout=60)
            r.raise_for_status()
            name = os.path.basename(a["resume_path"])
            ctype = r.headers.get("Content-Type", "").split(";")[0] or mimetypes.guess_type(name)[0] or "application/octet-stream"
            maintype, _, subtype = ctype.partition("/")
            msg.add_attachment(r.content, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
        except Exception as e:
            print(f"Could not attach résumé: {e}")
            msg.set_content("\n".join(lines + ["", f"(The résumé didn't attach. It's in the Supabase 'jobs' bucket at {a['resume_path']}.)"]))

    if DRY_RUN:
        print(f"[DRY RUN] To: {TO}\nReply-To: {a['email']}\nSubject: {msg['Subject']}\n")
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
