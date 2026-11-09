"""
Sisyphus - the morning-after email with a comic's show recording (Sam, Nov 4 2026).

The office PC (av/recordings/split_and_share.py) cuts each night's OBS
recording into one clip per set, uploads them to Google Drive and lists them
in public.recordings. Every morning at 9 AM the "Recording links" action runs
this: each headliner gets one email from Sam with a view-only link to their
set(s) and the full show, sent to the email on their advance, Bcc booking@.
Links stop working after 60 days, when the PC deletes the files.

A show where nobody pressed the stage timer is split from the host's intros
on the PC; only if that finds nothing is there just an "unsorted" full
recording, and booking@ gets that link instead so someone can trim it. A show
whose picture failed the PC's camera check (a CAMERA note: nearly black, or
not the stage) goes to booking@ too, so a headliner never gets a black video.

    python recording_mail.py
    PREVIEW_TO=someone@example.com ...  send everything to this address, mark nothing
    DRY_RUN=1 ...                       print what would be sent
"""
import html
import os
import smtplib
import ssl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
PREVIEW_TO = (os.environ.get("PREVIEW_TO") or "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
BOOKING = "booking@sisyphusbrewing.com"
CHICAGO = ZoneInfo("America/Chicago")
KEEP_DAYS = 60
H = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def get(table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def mark(ids, to):
    if PREVIEW_TO or DRY_RUN:
        return
    requests.patch(f"{SUPABASE_URL}/rest/v1/recordings", params={"id": f"in.({','.join(map(str, ids))})"},
                   headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"},
                   json={"emailed_at": datetime.now(timezone.utc).isoformat(), "emailed_to": to},
                   timeout=30).raise_for_status()


def ts(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def headliner_for(title, day):
    """The advance for this show: same night, act or show name in the title."""
    rows = get("advances", {"select": "contact_name,contact_email,act_name,show_name,show_date,show_end_date",
                            "show_date": f"lte.{day.isoformat()}", "contact_email": "not.is.null",
                            "order": "show_date.desc", "limit": "20"})
    t = title.lower()
    for a in rows:
        end = a.get("show_end_date") or a["show_date"]
        if end < day.isoformat():
            continue
        names = [x.lower() for x in (a.get("act_name"), a.get("show_name")) if x]
        if any(n in t or t in n for n in names):
            return a
    return None


def send(to, subject, body_html, text, bcc):
    if DRY_RUN:
        print(f"[DRY RUN] '{subject}' to {to} (bcc {bcc})\n{text}\n")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"], msg["Reply-To"] = subject, f"Sam at Sisyphus <{FROM_EMAIL}>", to, BOOKING
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, [to] + bcc, msg.as_string())
    print(f"Sent '{subject}' to {to}")


def show_label(r):
    local = ts(r["starts_at"]).astimezone(CHICAGO)
    return f"{local:%a %b} {local.day}, {local.hour % 12 or 12}{':%02d' % local.minute if local.minute else ''} {'PM' if local.hour >= 12 else 'AM'}"


def email(first, rows):
    esc = html.escape
    expires = (datetime.now(CHICAGO) + timedelta(days=KEEP_DAYS))
    links = []
    for r in sorted(rows, key=lambda r: (r["starts_at"], r["part"] != "headliner")):
        what = "Your set" if r["part"] == "headliner" else "The full show"
        links.append((f"{what}, {show_label(r)}", r["link"]))
    li = "".join(f'<li style="margin:6px 0"><a href="{esc(u)}">{esc(t)}</a></li>' for t, u in links)
    hey = f"Hey {first}," if first else "Hey,"
    gone = f"{expires:%B} {expires.day}"
    body = (f"<p>{esc(hey)}</p><p>Thanks for the show. Here's the video from the night:</p><ul>{li}</ul>"
            f"<p>The links work until {gone}, then we delete them to make room for the next comic, so download anything "
            f"you want to keep. It's one camera and the room mic, so it's honest.</p><p>Cheers,<br>Sam</p>")
    text = "\n".join([hey, "", "Thanks for the show. Here's the video from the night:", ""]
                     + [f"{t}: {u}" for t, u in links]
                     + ["", f"The links work until {gone}, then we delete them to make room for the next comic, "
                            "so download anything you want to keep.", "", "Cheers,", "Sam"])
    return body, text


def main():
    since = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    rows = get("recordings", {"select": "*", "emailed_at": "is.null", "link": "not.is.null",
                              "created_at": f"gte.{since}", "order": "starts_at"})
    by_show = defaultdict(list)
    for r in rows:
        by_show[(r["show_title"], r["starts_at"])].append(r)

    # Group a headliner's shows by night, so two shows = one email.
    batches = defaultdict(list)
    for (title, starts), parts in by_show.items():
        day = ts(starts).astimezone(CHICAGO).date()
        names = {p["part"] for p in parts}
        if any((p.get("note") or "").startswith("CAMERA") for p in parts):
            batches[(BOOKING, "", f"camera|{title}|{day}")].extend(parts)
            continue
        if "unsorted" in names:
            batches[(BOOKING, "", f"unsorted|{title}|{day}")].extend(parts)
            continue
        if "headliner" not in names:
            continue
        a = headliner_for(title, day)
        if not a:
            print(f"{title} {day}: no advance email, telling booking@")
            batches[(BOOKING, "", f"noemail|{title}|{day}")].extend(p for p in parts if p["part"] in ("headliner", "full"))
            continue
        first = (a.get("contact_name") or "").split(" ")[0]
        batches[(a["contact_email"].strip(), first, f"{title}|{day}")].extend(
            p for p in parts if p["part"] in ("headliner", "full"))

    for (to, first, key), parts in batches.items():
        title = key.split("|")[1]
        if key.startswith("unsorted"):
            subject = f"Recording needs trimming: {title}"
            links = "".join(f'<li><a href="{html.escape(p["link"])}">{html.escape(show_label(p))}</a></li>' for p in parts)
            body = (f"<p>Nobody pressed the stage timer during {html.escape(title)}, so the recording couldn't be split "
                    f"by comic. Full show:</p><ul>{links}</ul><p>Trim the headliner's set and send it to them, "
                    f"and remind whoever ran the deck: START for every comic.</p>")
            text = f"Nobody pressed the stage timer during {title}. Full show: " + ", ".join(p["link"] for p in parts)
            bcc = []
        elif key.startswith("camera"):
            subject = f"Recording needs a look: {title}"
            notes = sorted({p["note"] for p in parts if p.get("note")})
            links = "".join(f'<li><a href="{html.escape(p["link"])}">{html.escape(p["part"])}, '
                            f'{html.escape(show_label(p))}</a></li>' for p in parts)
            body = (f"<p>The camera check flagged {html.escape(title)}:</p><ul>"
                    + "".join(f"<li>{html.escape(n)}</li>" for n in notes)
                    + f"</ul><p>So the headliner wasn't sent anything. The recordings:</p><ul>{links}</ul>"
                    f"<p>If the sound is fine, send them on yourself. Then check the camera is on the stage preset.</p>")
            text = f"The camera check flagged {title}: " + " ".join(notes) + " Recordings: " + ", ".join(p["link"] for p in parts)
            bcc = []
        elif key.startswith("noemail"):
            subject = f"Recording ready, no email for the headliner: {title}"
            body, text = email("", parts)
            bcc = []
        else:
            subject = f"Your video from Sisyphus: {title}"
            body, text = email(first, parts)
            bcc = [] if PREVIEW_TO else [BOOKING]
        send(PREVIEW_TO or to, subject, body, text, bcc)
        mark([p["id"] for p in parts], to)
    # Full-show rows of other shows (no headliner email) stay unmailed and drop out after 4 days.


if __name__ == "__main__":
    main()
