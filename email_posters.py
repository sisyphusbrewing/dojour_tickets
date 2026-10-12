"""
Sisyphus - email show posters.

Sends poster PDFs from posters/out/ (made by make_posters.py) as email
attachments, using the same Gmail SMTP settings as the weekly agent reports.

    python email_posters.py sam-jay ali-sultan   # these shows' posters
    python email_posters.py --new                # shows created in the last NEW_HOURS (default 6)

Recipients: POSTER_EMAIL_TO (comma-separated), falling back to FROM_EMAIL /
SMTP_USER. Set DRY_RUN=1 to print what would be sent without sending.
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("POSTER_OUT") or os.path.join(HERE, "posters", "out")
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TO = [a.strip() for a in (os.environ.get("POSTER_EMAIL_TO") or FROM_EMAIL).split(",") if a.strip()]
NEW_HOURS = float(os.environ.get("NEW_HOURS", "6"))
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
REPO = os.environ.get("GITHUB_REPOSITORY", "sisyphusbrewing/dojour_tickets")


def pick(manifest, args):
    if "--new" in args:
        since = datetime.now(timezone.utc) - timedelta(hours=NEW_HOURS)
        chosen = [m for m in manifest if m.get("created_at")
                  and datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")) >= since]
        if not chosen:
            print(f"No shows created in the last {NEW_HOURS:g} h - nothing to email.")
        return chosen
    wanted = {a.lower() for a in args if not a.startswith("--")}
    missing = wanted - {m["handle"] for m in manifest}
    if missing:
        print(f"No poster for: {', '.join(sorted(missing))}")
    return [m for m in manifest if m["handle"] in wanted]


def main():
    with open(os.path.join(OUT_DIR, "manifest.json")) as f:
        manifest = json.load(f)["posters"]
    shows = pick(manifest, sys.argv[1:])
    if not shows:
        return
    if not TO:
        sys.exit("No recipient: set POSTER_EMAIL_TO (or FROM_EMAIL).")

    titles = ", ".join(m["title"] for m in shows)
    msg = EmailMessage()
    msg["Subject"] = f"New show poster{'s' if len(shows) > 1 else ''}: {titles}"
    msg["From"] = f"Sisyphus <{FROM_EMAIL}>"
    msg["To"] = ", ".join(TO)
    lines = ["Print-ready 11 x 17 poster(s) attached (1/8 in bleed; print 'fit to page' on an 11x17 printer).", ""]
    for m in shows:
        dates = "; ".join(f"{d} {t}" for d, t in m["dates"])
        lines += [f"{m['title']}", f"  {dates}", f"  Tickets: {m['url']}",
                  f"  Poster: https://github.com/{REPO}/releases/download/posters/{m['file']}", ""]
    lines += [f"All current posters: https://github.com/{REPO}/releases/tag/posters", "", "Sisyphus · 712 Ontario Ave W, Minneapolis"]
    msg.set_content("\n".join(lines))
    for m in shows:
        with open(os.path.join(OUT_DIR, m["file"]), "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=m["file"])

    if DRY_RUN:
        print(f"[DRY RUN] Would send '{msg['Subject']}' to {TO} with {len(shows)} attachment(s)")
        return
    if not SMTP_USER or not SMTP_PASS:
        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print(f"Sent '{msg['Subject']}' to {', '.join(TO)}")


if __name__ == "__main__":
    main()
