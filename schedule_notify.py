"""
Sisyphus - tell staff about schedule changes, by email or text.

The schedule page (schedule/index.html, staff hub > Schedule) writes a short
notice to the schedule_outbox table whenever something affects a person: a
week is posted, their shift changes, a shift is up for grabs, time off is
answered. This script sends the notices nobody has been sent yet, the way
each person picked on the schedule page under "How to reach me": email, text,
both or neither (Sam, Nov 14 2026: "Staff should be able to choose if they
want text or e-mail, or both").

It also queues the "you work today" reminders, once a day from 9 AM Central.

The time clock (clock/index.html, Sam Nov 16 2026) uses the same outbox: a
manager hears when someone types a time in by hand, a person hears when a
manager changes their hours, and anyone who looks to have forgotten to clock
out gets one nudge. Those notices link to the Clock page, not the schedule.

Run by the "Schedule notices" action, which keeps this script going around
the clock and has it look for waiting notices every two minutes (--watch).
GitHub's own timer started only two to four of the 68 runs a day it was asked
for (Nov 14 to 17 2026), so a notice could sit for hours; see the workflow.
Nothing is sent between 1 AM and 8 AM Central: a notice waits for morning.

Texts go through Twilio and only when the TWILIO_ACCOUNT_SID,
TWILIO_AUTH_TOKEN and TWILIO_FROM secrets exist. Until then a person who
picked "text" gets the same notice by email instead.

Several notices for one person go out as one email, not five.

It also watches the office PC (Sam, Nov 18 2026: the PC is the nightly
backup and the offline fallback until a NAS arrives). The PC checks in every
10 minutes; device_check() in the database says when it has gone quiet for
30 minutes, when it is back, and when a nightly backup failed or was missed,
each once, and this emails Sam. Like the notices, these wait out 1 to 8 AM.

The log of a GitHub Action in this repo is public, so this never prints a
name, an email address, a phone number or what a notice says.

    python schedule_notify.py               one look, then stop
    python schedule_notify.py --watch 330   look every two minutes for 330 minutes
    DRY_RUN=1 ...   shows what would be sent (addresses masked), sends nothing
"""
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
TWILIO_SID = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_TOKEN = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
TWILIO_FROM = (os.environ.get("TWILIO_FROM") or "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
PAGE_URL = "https://staff.sisyphusbrewing.com/schedule/"
CLOCK_URL = "https://staff.sisyphusbrewing.com/clock/"
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
CENTRAL = ZoneInfo("America/Chicago")

REMIND_FROM_HOUR = 9       # "you work today" goes out from 9 AM Central
REMINDER_STALE_HOURS = 14  # a "you work today" that old is about yesterday; drop it
GIVE_UP_DAYS = 3           # anything unsent this long is dropped, not sent late
TEXT_MAX = 600             # keep a text to a few segments
WATCH_EVERY = 120          # seconds between looks when watching
QUIET_FROM, QUIET_TO = 1, 8   # nothing goes out from 1 AM to 8 AM Central; it waits for morning

# What the email subject says for each kind of notice.
SUBJECTS = {
    "published": "Your schedule is posted",
    "shift_new": "New shift for you",
    "shift_changed": "Your shift changed",
    "shift_off": "You're off a shift",
    "shift_offered": "A shift is up for grabs",
    "shift_taken": "A shift got covered",
    "timeoff_asked": "Time off request",
    "timeoff_approved": "Your time off was approved",
    "timeoff_denied": "Your time off was declined",
    "timeoff_cancelled": "A time off request was taken back",
    "availability": "Someone changed when they can work",
    "reminder": "You work today",
    # The time clock's notices (their kind starts with "clock_").
    "clock_typed": "Hours were typed in by hand",
    "clock_fixed": "Your hours were changed",
    "clock_open": "Did you forget to clock out?",
}


OWNER_EMAIL = "sam@sisyphusbrewing.com"
DEVICE_NAMES = {"office-pc": "The office PC"}


def device_alerts(rows):
    """Turn device_check() rows into emails for Sam: [(subject, body)].
    Pure, so the tests can check the wording."""
    out = []
    for r in rows or []:
        name = DEVICE_NAMES.get(r.get("device"), r.get("device") or "A device")
        seen = r.get("seen_at")
        seen_txt = parse_time(seen).astimezone(CENTRAL).strftime("%a %b %-d, %-I:%M %p") if seen else "never"
        state = r.get("state")
        if state == "offline":
            out.append((f"{name} is offline",
                        f"{name} hasn't checked in since {seen_txt} Central. It may be asleep, turned off, "
                        "unplugged or off the network. Until it's back, last night's backup is the newest "
                        "one and the show-night fallback on it isn't running.\n\n"
                        "You'll get one more email when it checks in again."))
        elif state == "back":
            out.append((f"{name} is back online", f"{name} checked in again at {seen_txt} Central."))
        elif state == "backup_failed":
            note = (r.get("note") or "").strip()
            out.append((f"{name}: last night's backup failed",
                        f"The nightly backup on {name[0].lower() + name[1:]} reported a problem"
                        + (f": {note}" if note else ".") + "\n\nThe backups from before it are still there. "
                        "Claude can look into it from the office PC."))
        elif state == "backup_missed":
            out.append((f"{name}: no backup in over a day",
                        f"{name} is on, but its nightly backup hasn't run since "
                        + (parse_time(r["last_backup_at"]).astimezone(CENTRAL).strftime("%a %b %-d") if r.get("last_backup_at") else "it was set up")
                        + ". The scheduled task may have been turned off."))
    return out


def send_device_alerts():
    """Ask the database what changed with the office PC and email Sam."""
    rows = rpc("device_check", optional=True)
    alerts = device_alerts(rows)
    if not alerts:
        return 0
    if not SMTP_USER or not SMTP_PASS:
        print(f"{len(alerts)} device alert(s) not sent: SMTP credentials missing.")
        return 0
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        for subject, body in alerts:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = f"Sisyphus Box Office <{FROM_EMAIL}>"
            msg["To"] = OWNER_EMAIL
            msg.set_content(body + "\n\nSisyphus")
            server.send_message(msg)
    print(f"Sent {len(alerts)} device alert(s).")
    return len(alerts)


CHECKS_LINK = "https://staff.sisyphusbrewing.com/payouts/#checks"


def check_alerts(rows):
    """Turn check_alerts() rows into emails for Sam: [(subject, body)].
    Printed comic checks only go out on Sam's OK (Sam, Nov 18 2026), so he
    hears when one is waiting for him, when it printed, and when it didn't.
    Pure, so the tests can check the wording."""
    out = []
    for r in rows or []:
        who = r.get("pay_to") or "a comic"
        amt = f"${float(r.get('amount') or 0):,.2f}"
        num = f"Check {r['number']}" if r.get("number") else "A check"
        note = (r.get("note") or "").strip()
        state = r.get("state")
        if state == "waiting":
            out.append((f"Check to approve: {amt} to {who}",
                        f"A check for {amt} to {who}" + (f" ({note})" if note else "") + " is waiting for your OK. "
                        f"Nothing prints until you approve it.\n\nApprove or void it here: {CHECKS_LINK}"))
        elif state == "printed":
            out.append((f"{num} printed: {amt} to {who}",
                        f"{num} for {amt} to {who} went to the office printer. Its pay line is marked paid.\n\n"
                        f"Didn't come out right? Void it here and approve a new one: {CHECKS_LINK}"))
        elif state == "failed":
            out.append((f"{num} did not print: {amt} to {who}",
                        f"The office PC couldn't print {num.lower()} for {amt} to {who}"
                        + (f": {note}." if note else ".") + f"\n\nFix it, then tap Print again: {CHECKS_LINK}"))
        elif state == "stuck":
            out.append((f"{num} hasn't printed yet: {amt} to {who}",
                        f"{num} for {amt} to {who} went to the office PC 10 minutes ago and it never said it printed. "
                        "The PC may be asleep or the printer jammed.\n\nIf the check came out, keep it and ignore this. "
                        f"If not, tap Print again; if a bad copy came out, void it: {CHECKS_LINK}"))
    return out


def send_check_alerts():
    """Ask the database what changed with printed checks and email Sam."""
    alerts = check_alerts(rpc("check_alerts", optional=True))
    if not alerts:
        return 0
    if not SMTP_USER or not SMTP_PASS:
        print(f"{len(alerts)} check alert(s) not sent: SMTP credentials missing.")
        return 0
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        for subject, body in alerts:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = f"Sisyphus Box Office <{FROM_EMAIL}>"
            msg["To"] = OWNER_EMAIL
            msg.set_content(body + "\n\nSisyphus")
            server.send_message(msg)
    print(f"Sent {len(alerts)} check alert(s).")
    return len(alerts)


def texts_on():
    return bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


def parse_time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def mask(value):
    """j***@gmail.com, ***-0100: enough to recognise in a dry run, no more."""
    value = str(value or "")
    if "@" in value:
        return value[0] + "***@" + value.split("@", 1)[1]
    return "***-" + value[-4:] if value else ""


def plan(rows, can_text, now):
    """Decide what to send. Pure: no network, so the tests can check every rule.

    rows are the unsent notices (schedule_outbox_pending). Returns
    (deliveries, skipped): deliveries is one entry per person per way of
    reaching them, skipped maps a notice id to the reason it won't be sent.
    """
    skipped = {}
    people = {}
    for row in rows:
        age = now - parse_time(row["created_at"])
        if row["kind"] == "reminder" and age > timedelta(hours=REMINDER_STALE_HOURS):
            skipped[row["id"]] = "too late to be useful"
            continue
        if age > timedelta(days=GIVE_UP_DAYS):
            skipped[row["id"]] = "too late to be useful"
            continue
        by = row.get("notify_by") or "email"
        if by == "none":
            skipped[row["id"]] = "asked for no notices"
            continue
        people.setdefault(row["user_id"], []).append(row)

    deliveries = []
    for rows_for in people.values():
        one = rows_for[0]
        by = one.get("notify_by") or "email"
        email = (one.get("notify_email") or "").strip()
        phone = (one.get("notify_phone") or "").strip()
        want_email = by in ("email", "both")
        want_text = by in ("text", "both")
        # Texts not switched on yet (or no number): the email carries it.
        if want_text and (not can_text or not phone):
            want_text = False
            want_email = True
        if want_email and not email:
            want_email = False
        ids = [r["id"] for r in rows_for]
        if not want_email and not want_text:
            for i in ids:
                skipped[i] = "no email or mobile number on file"
            continue
        bodies = [r["body"] for r in rows_for]
        first = (one.get("name") or "").split(" ")[0]
        if want_email:
            subject = SUBJECTS.get(one["kind"], "Schedule update") if len(rows_for) == 1 \
                else f"Sisyphus schedule: {len(rows_for)} updates"
            lines = [f"Hi {first}," if first else "Hi,", ""]
            lines += bodies if len(bodies) == 1 else [f"- {b}" for b in bodies]
            # Link the page the notice is about: the Clock for clock notices,
            # the schedule for the rest (both when one email carries both).
            kinds = [str(r.get("kind") or "") for r in rows_for]
            lines.append("")
            if any(k.startswith("clock_") for k in kinds):
                lines.append(f"The clock: {CLOCK_URL}")
            if any(not k.startswith("clock_") for k in kinds):
                lines.append(f"The schedule: {PAGE_URL}")
            lines += ["", "To get these by text instead, or to stop them, open the schedule and look under "
                          f"\"How to reach me\": {PAGE_URL}",
                      "", "Sisyphus"]
            deliveries.append({"how": "email", "to": email, "ids": ids, "subject": subject, "body": "\n".join(lines)})
        if want_text:
            text = "Sisyphus: " + " / ".join(bodies)
            if len(text) > TEXT_MAX:
                text = text[:TEXT_MAX - 40].rstrip() + "... More on the schedule page."
            deliveries.append({"how": "text", "to": "+1" + phone, "ids": ids, "body": text})
    return deliveries, skipped


def rpc(name, optional=False):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/rpc/{name}", headers=AUTH, json={}, timeout=30)
    if r.status_code == 404:
        if optional:
            # A part that isn't in the database yet (the time clock, before its
            # migration is applied). Skip it; the rest of the notices still go.
            return None
        # The schedule tables aren't in the database yet. Nothing to do, and not an error.
        print("The schedule isn't switched on yet.")
        sys.exit(0)
    r.raise_for_status()
    return r.json()


def stamp(ids, how):
    """Mark notices handled, with how they went (or why they didn't)."""
    if not ids:
        return
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/schedule_outbox",
                       params={"id": f"in.({','.join(str(i) for i in ids)})"},
                       json={"sent_at": datetime.now(timezone.utc).isoformat(), "sent_how": how},
                       headers={**AUTH, "Prefer": "return=minimal"}, timeout=30)
    r.raise_for_status()


def send_text(to, body):
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                      auth=(TWILIO_SID, TWILIO_TOKEN), data={"To": to, "From": TWILIO_FROM, "Body": body}, timeout=30)
    r.raise_for_status()


def quiet_hours(now):
    """True from 1 AM to 8 AM Central, when a notice waits for morning."""
    return QUIET_FROM <= now.astimezone(CENTRAL).hour < QUIET_TO


def main(quietly=False):
    """One look: queue today's reminders, then send whatever is waiting.
    Returns how many notices went out. `quietly` leaves out the "nothing to
    send" line, so a run that looks 165 times doesn't print it 165 times."""
    now = datetime.now(timezone.utc)
    if not DRY_RUN and now.astimezone(CENTRAL).hour >= REMIND_FROM_HOUR:
        queued = rpc("schedule_queue_reminders")
        if queued:
            print(f"Queued {queued} reminder(s) for today's shifts.")
    if not DRY_RUN:
        # "Did you forget to clock out?", once per shift, at any hour: bar
        # shifts end after midnight.
        nudged = rpc("clock_queue_reminders", optional=True)
        if nudged:
            print(f"Queued {nudged} forgot-to-clock-out nudge(s).")
        # The office PC: gone quiet, back, or a backup problem.
        try:
            send_device_alerts()
        except (requests.RequestException, smtplib.SMTPException, OSError) as err:
            print(f"Device check failed ({type(err).__name__}); trying again next look.")
        # Printed comic checks: waiting for Sam's OK, printed, or not.
        try:
            send_check_alerts()
        except (requests.RequestException, smtplib.SMTPException, OSError) as err:
            print(f"Check alerts failed ({type(err).__name__}); trying again next look.")

    rows = rpc("schedule_outbox_pending")
    if not rows:
        if not quietly:
            print("Nothing to send. The boulder rests.")
        return 0
    deliveries, skipped = plan(rows, texts_on(), now)

    if DRY_RUN:
        for d in deliveries:
            print(f"[DRY RUN] {d['how']} to {mask(d['to'])}, notices {d['ids']}:")
            print(d.get("subject", ""))
            print(d["body"], "\n")
        for i, why in skipped.items():
            print(f"[DRY RUN] notice {i} not sent: {why}")
        return 0

    for why in sorted(set(skipped.values())):
        stamp([i for i, w in skipped.items() if w == why], f"not sent: {why}")

    server = None
    sent = {}      # notice id -> ways it went out
    failed = set()
    try:
        for d in deliveries:
            try:
                if d["how"] == "email":
                    if not SMTP_USER or not SMTP_PASS:
                        sys.exit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
                    if server is None:
                        server = smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30)
                        server.login(SMTP_USER, SMTP_PASS)
                    msg = EmailMessage()
                    msg["Subject"] = d["subject"]
                    msg["From"] = f"Sisyphus Schedule <{FROM_EMAIL}>"
                    msg["To"] = d["to"]
                    msg.set_content(d["body"])
                    server.send_message(msg)
                else:
                    send_text(d["to"], d["body"])
                for i in d["ids"]:
                    sent.setdefault(i, []).append(d["how"])
            except (smtplib.SMTPException, requests.RequestException, OSError) as err:
                # Say that it failed, never who it was for. It is tried again next run.
                failed.update(d["ids"])
                print(f"A {d['how']} did not go out ({type(err).__name__}); notices {d['ids']} will be retried.")
    finally:
        if server is not None:
            server.quit()

    # A notice is done once it went out at least one way, so nobody gets it twice.
    by_how = {}
    for i, hows in sent.items():
        by_how.setdefault("+".join(sorted(set(hows))), []).append(i)
    for how, ids in by_how.items():
        stamp(ids, how)
    print(f"Sent {len(sent)} notice(s) in {len(deliveries)} message(s); "
          f"{len(skipped)} not sent; {len(failed - set(sent))} to retry.")
    return len(sent)


def watch(minutes):
    """Look every two minutes for `minutes`, then stop so the action can start
    its next run (a GitHub job may run six hours at most). One look that fails
    (the database or the mail server hiccups) is tried again at the next look;
    the run only ends in an error when every single look failed."""
    end = time.monotonic() + minutes * 60
    looks = sent = failed = 0
    while True:
        looks += 1
        try:
            if not quiet_hours(datetime.now(timezone.utc)):
                sent += main(quietly=True) or 0
        except (requests.RequestException, smtplib.SMTPException, OSError) as err:
            failed += 1
            print(f"A look failed ({type(err).__name__}); trying again in two minutes.")
        if time.monotonic() + WATCH_EVERY >= end:
            break
        time.sleep(WATCH_EVERY)
    print(f"Looked {looks} time(s), sent {sent} notice(s), {failed} look(s) failed.")
    if failed == looks:
        sys.exit("Every look failed. Check the Supabase and email secrets.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--watch":
        watch(float(sys.argv[2]))
    else:
        main()
