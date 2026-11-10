"""
Sisyphus - comedian advances that make and send themselves, three weeks out.

Every morning the "Automatic advances" action runs this. Sam decided on
Nov 9 2026 that Grace shouldn't have to ask for advance links: any headliner
run starting in the next 21 days that has no advance yet gets one.

  1. Upcoming headliner shows come from show_history (every Dojour showtime;
     the free recurring nights live only on the website, so they never show
     up there). Recurring shows Sam listed (Magicians, Magic: The Gathering,
     Blingo, Advice Column and the like) are skipped by name anyway.
  2. Showtimes of the same comic within 3 days of each other are one run
     (Fri + Sat = one advance, one email).
  3. A run that already has an advance (made on the booking desk or here) is
     left alone.
  4. If we know the comic's own email (from the weekly-report list, a past
     advance or the pay list; agency addresses never count, since agents
     rarely fill these in) the advance is made and the "You're booked"
     welcome goes out right away (advance_welcome.py, copy to booking@).
     If not, the advance is made with no email and booking@ gets one short
     note asking for it. Once someone adds the email on the booking desk, the
     next morning's run sends the welcome by itself.

    python advance_auto.py
    DRY_RUN=1 python advance_auto.py   says what it would do, sends nothing
"""
import os
import re
import smtplib
import ssl
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
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
BOOKING = "booking@sisyphusbrewing.com"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
CENTRAL = ZoneInfo("America/Chicago")
DESK = "https://staff.sisyphusbrewing.com/advance/booking.html#/a/"

DAYS_OUT = 21          # make the advance this many days before the first night
RUN_GAP_DAYS = 3       # showtimes this close together are one run
AUTO_NOTE = "Made automatically"   # marks advances this script made (staff_notes)

# Shows that never get an advance (Sam, Nov 9 2026: "reoccuring events like
# Magicians, magic the gathering, blingo, advice column, etc can be skipped").
SKIP = re.compile(
    r"cancel|postpon|magic|gathering|blingo|advice column|\bmic\b|showcase|queen.?s gambit|chess|"
    r"trivia|class|workshop|private event", re.IGNORECASE)


def family(title):
    """The comic's name without the tour or 'Spooky Edition' tail, lowercased.
    Same rule as public.show_family() in Supabase."""
    t = re.sub(r"\s*(\(|:|\s[-–—|]\s).*$", "", title or "")
    return re.sub(r"\s+", " ", t).strip().lower()


def central_day(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(CENTRAL).date()


def runs(history, today):
    """[{title, family, first, last}] for headliner runs whose first night is
    from tomorrow up to DAYS_OUT days away. history = show_history rows."""
    nights = {}
    for row in history:
        title = (row.get("show_title") or row.get("event_title") or "").strip()
        if not title or SKIP.search(title) or not row.get("starts_at"):
            continue
        fam = family(title)
        if not fam:
            continue
        nights.setdefault(fam, {"title": title, "days": set()})["days"].add(central_day(row["starts_at"]))
    out = []
    for fam, info in nights.items():
        days = sorted(d for d in info["days"] if d > today)
        start = None
        for i, d in enumerate(days):
            if start is None:
                start = prev = d
            elif (d - prev).days <= RUN_GAP_DAYS:
                prev = d
            else:
                out.append((fam, info["title"], start, prev))
                start = prev = d
            if i == len(days) - 1:
                out.append((fam, info["title"], start, prev))
    return [{"family": f, "title": t, "first": a, "last": b} for f, t, a, b in out
            if (a - today).days <= DAYS_OUT]


def has_advance(run, advances):
    for a in advances:
        if not a.get("show_date"):
            continue
        if family(a.get("show_name")) != run["family"] and family(a.get("act_name")) != run["family"]:
            continue
        if abs((date.fromisoformat(a["show_date"]) - run["first"]).days) <= RUN_GAP_DAYS:
            return True
    return False


# Agencies and managers. Sam, Nov 9 2026: "The agents are rarely the people
# that reach out with the advance info", so the welcome goes to the comic (or
# their tour manager), never to an agency address.
AGENCY = re.compile(
    r"@([\w.-]*\.)?(wmeagency|unitedtalent|caa|gersh|avalon-usa|3arts|independentartistgroup|bep-la|bep-ny|"
    r"levitytalent|artistsfirst[\w-]*|mosaicla|underscoretalent|agi-entertainment|ent360|apa-agency|icmpartners|"
    r"dynamictalentint|nordictalenthouse|1717mgmt|forzamanagement|barrykatz|kaminproductions|micdropcomedy|"
    r"10000laughs|arsonhouse|waltermasterson)\.com$|agency|talent|mgmt|management", re.IGNORECASE)


def split_emails(text):
    return [e for e in re.split(r"[,;\s]+", text or "") if "@" in e]


def contacts(run, agents, advances, payees):
    """The comic's own email(s), from anywhere we've seen one: the report list,
    past advances, the pay list. Agency addresses are left out."""
    found = []
    def add(e):
        if not AGENCY.search(e) and e.lower() not in [x.lower() for x in found]:
            found.append(e)
    for row in agents:
        if family(row.get("show_title")) == run["family"]:
            for e in split_emails(row.get("agent_email")):
                add(e)
    for a in advances:
        if run["family"] in (family(a.get("show_name")), family(a.get("act_name"))):
            for e in split_emails(a.get("contact_email")):
                add(e)
    for p in payees:
        if family(p.get("name")) == run["family"]:
            for e in split_emails(p.get("email")):
                add(e)
    return found


def plan(history, advances, agents, today, payees=(), past_advances=()):
    """What today's run does. Pure, so it can be tested.
    Returns [(action, run, emails, name)] where action is 'welcome' (make it and
    send it) or 'ask' (make it, ask booking@ for a contact), plus
    [advance] rows made earlier whose email has since been added ('send')."""
    todo = []
    for run in sorted(runs(history, today), key=lambda r: r["first"]):
        if has_advance(run, advances):
            continue
        emails = contacts(run, agents, list(past_advances) + list(advances), payees)
        todo.append(("welcome" if emails else "ask", run, emails, None))
    later = [a for a in advances
             if AUTO_NOTE in (a.get("staff_notes") or "") and (a.get("contact_email") or "").strip()
             and not a.get("welcome_sent_at") and a.get("show_date") and date.fromisoformat(a["show_date"]) > today]
    return todo, later


# ---------- Supabase + email ----------

def sb(method, path, **kw):
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
    h.update(kw.pop("headers", {}))
    r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=h, timeout=30, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def make_advance(run, emails, name):
    row = {"show_name": run["title"], "show_date": run["first"].isoformat(),
           "show_end_date": run["last"].isoformat() if run["last"] > run["first"] else None,
           "contact_email": ", ".join(emails) or None, "contact_name": name,
           "staff_notes": f"{AUTO_NOTE} {date.today():%b %-d %Y} ({DAYS_OUT} days out)."}
    return sb("POST", "advances", json=row, headers={"Prefer": "return=representation"})[0]


def send_welcome(advance_id):
    env = dict(os.environ, ADVANCE_ID=advance_id, WELCOME_TO="")
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "advance_welcome.py")],
                   env=env, check=True)


def when(run):
    a, b = run["first"], run["last"]
    if b <= a:
        return f"{a:%a %b %-d}"
    return f"{a:%a %b %-d}–{b:%-d}" if a.month == b.month else f"{a:%a %b %-d} – {b:%b %-d}"


def ask_booking(run, advance_id):
    """One short note to booking@: we need an email for this show."""
    link = DESK + advance_id
    subject = f"Advance needs a contact: {run['title']}, {when(run)}"
    text = (f"{run['title']} plays {when(run)}, and we don't have an email for the comic or their tour manager (agents rarely fill these in).\n\n"
            f"Add it on the booking desk: {link}\n\n"
            "That's it. The advance and the \"You're booked\" email go out the next morning by themselves.")
    html = (f"<p>{run['title']} plays {when(run)}, and we don't have an email for the comic or their tour manager (agents rarely fill these in).</p>"
            f'<p><a href="{link}">Add it on the booking desk</a></p>'
            "<p>That's it. The advance and the \"You're booked\" email go out the next morning by themselves.</p>")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Sisyphus <{FROM_EMAIL}>", BOOKING
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM_EMAIL, [BOOKING], msg.as_string())


def main():
    today = datetime.now(CENTRAL).date()
    horizon = datetime.now(timezone.utc) + timedelta(days=DAYS_OUT + 2)
    history = sb("GET", "show_history", params={"select": "show_title,event_title,starts_at",
                                                 "starts_at": f"gte.{datetime.now(timezone.utc).isoformat()}",
                                                 "and": f"(starts_at.lte.{horizon.isoformat()})"})
    advances = sb("GET", "advances", params={"select": "id,show_name,act_name,show_date,contact_email,staff_notes,welcome_sent_at",
                                             "show_date": f"gte.{today - timedelta(days=RUN_GAP_DAYS)}"})
    agents = sb("GET", "show_agents", params={"select": "show_title,agent_name,agent_email"})
    past = sb("GET", "advances", params={"select": "show_name,act_name,show_date,contact_email",
                                         "contact_email": "not.is.null"})
    payees = sb("GET", "payees", params={"select": "name,email"})
    todo, later = plan(history, advances, agents, today, payees, past)

    if not todo and not later:
        print("Nothing to do: every headliner run in the next 3 weeks already has an advance.")
    for action, run, emails, name in todo:
        print(f"{when(run)} {run['title']}: " + (f"make advance + welcome to {', '.join(emails)}" if action == "welcome"
                                                else "make advance, ask booking@ for a contact"))
        if DRY_RUN:
            continue
        adv = make_advance(run, emails, name)
        if action == "welcome":
            send_welcome(adv["id"])
        else:
            ask_booking(run, adv["id"])
    for a in later:
        print(f"{a['show_date']} {a['show_name']}: email added on the desk, sending the welcome to {a['contact_email']}")
        if not DRY_RUN:
            send_welcome(a["id"])
    if DRY_RUN:
        print("[DRY RUN] nothing made or sent.")


if __name__ == "__main__":
    main()
