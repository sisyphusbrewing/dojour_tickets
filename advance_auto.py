"""
Sisyphus - comedian advances that make and send themselves, three weeks out.

Every morning the "Automatic advances" action runs this. Sam decided on
Nov 9 2026 that Grace shouldn't have to ask for advance links: any headliner
run starting in the next 21 days that has no advance yet gets one.

  1. Upcoming headliner shows come from two lists: every showtime on sale on
     the website (exchange_showtimes, refreshed by the sync every 4 hours)
     and every Dojour showtime (show_history). At first this read Dojour
     alone, because only headliners were ever listed there; with Dojour being
     phased out, new shows are on the website only and were being missed
     (Sam, Nov 15 2026). The house nights are kept out two ways: free website
     showtimes never count, and the recurring shows Sam listed (Magicians,
     Magic: The Gathering, Blingo, Advice Column and the like) are skipped by
     name.
  2. Showtimes of the same show within a week of each other are one run
     (Fri + Sat = one advance, one email; so is a show that plays Sunday,
     Wednesday and the Sunday after).
  3. A run that already has an advance (made on the booking desk or here) is
     left alone, including its later nights once the first ones have played. So is a run a manager marked on the Booking board as
     "Advance: not needed" or as fallen through.
  4. If we know the comic's own email (from the weekly-report list, a past
     advance or the pay list; agency addresses never count, since agents
     rarely fill these in) the advance is made and the "You're booked"
     welcome goes out right away (advance_welcome.py, copy to booking@).
     If not, the advance is made with no email and booking@ gets one short
     note asking for it. Once someone adds the email on the booking desk, the
     next morning's run sends the welcome by itself.
  5. If the email is still missing a week before the first night, booking@
     is asked again 7, 3 and 1 days out, and the note carries the comic's own
     link so it can simply be forwarded or shown. (Jeffrey Keller's Nov 19
     2026 run got one note on Nov 10 and nothing after, so he never got his
     advance; Sam showed him the link at the club.)

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
TRIP_URL = "https://www.sisyphusbrewing.com/pages/advance?s="
REMIND_DAYS = (7, 3, 1)   # ask booking@ again this many days before the first night

DAYS_OUT = 21          # make the advance this many days before the first night
# Nights of one show up to a week apart are one run and get one advance. It
# was 3 days, which fits a Thursday-to-Saturday comic but split a show playing
# Sunday, Wednesday, Sunday into separate runs. (Nov 15 2026)
RUN_GAP_DAYS = 7
LOOK_AHEAD_DAYS = 90   # read this far ahead, so a run's last night is known
LOOK_BACK_DAYS = 60    # advances and board rows this old can still cover a run
AUTO_NOTE = "Made automatically"   # marks advances this script made (staff_notes)

# Shows that never get an advance (Sam, Nov 9 2026: "reoccuring events like
# Magicians, magic the gathering, blingo, advice column, etc can be skipped").
SKIP = re.compile(
    r"cancel|postpon|magic|gathering|blingo|advice column|\bmic\b|showcase|queen.?s gambit|chess|"
    r"trivia|class|workshop|private event|poets", re.IGNORECASE)


def family(title):
    """The comic's name without the tour or 'Spooky Edition' tail, lowercased.
    Same rule as public.show_family() in Supabase."""
    t = re.sub(r"\s*(\(|:|\s[-–—|]\s).*$", "", title or "")
    return re.sub(r"\s+", " ", t).strip().lower()


def central_day(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(CENTRAL).date()


def website_nights(showtimes):
    """Website showtimes (exchange_showtimes rows) in the same shape as the
    Dojour list, so both can be read together. Free showtimes are left out:
    those are the house nights (open mics, Blingo), never a booked headliner."""
    return [{"show_title": row.get("show_title"), "starts_at": row.get("starts_at")}
            for row in showtimes if float(row.get("price") or 0) > 0]


def runs(history, today):
    """[{title, family, first, last}] for headliner runs whose first night is
    from tomorrow up to DAYS_OUT days away. history = Dojour showtimes
    (show_history rows) plus website_nights(); a show on both lists is one run."""
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


def covers(run, first, last=None):
    """True when the dates first..last (ISO strings; last may be empty) belong
    to this run: they come within RUN_GAP_DAYS of its nights. Compared against
    the whole run, not just its first night, because once a run has started
    only its remaining nights are still in the showtime lists."""
    if not first:
        return False
    a = date.fromisoformat(first)
    b = max(a, date.fromisoformat(last)) if last else a
    gap = timedelta(days=RUN_GAP_DAYS)
    return a - gap <= run["last"] and run["first"] <= b + gap


def has_advance(run, advances):
    for a in advances:
        if family(a.get("show_name")) != run["family"] and family(a.get("act_name")) != run["family"]:
            continue
        if covers(run, a.get("show_date"), a.get("show_end_date")):
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


def off_on_board(run, board):
    """True when a manager said on the Booking board that this run needs no
    advance ("Advance: not needed") or that it fell through. board =
    booking_shows rows."""
    for row in board:
        if family(row.get("act")) != run["family"] or not covers(run, row.get("first_night"), row.get("last_night")):
            continue
        if row.get("stage") == "dropped" or (row.get("checks") or {}).get("advance") == "na":
            return True
    return False


def plan(history, advances, agents, today, payees=(), past_advances=(), board=()):
    """What today's run does. Pure, so it can be tested.
    Returns [(action, run, emails, name)] where action is 'welcome' (make it and
    send it) or 'ask' (make it, ask booking@ for a contact), plus
    [advance] rows made earlier whose email has since been added ('send')."""
    todo = []
    for run in sorted(runs(history, today), key=lambda r: r["first"]):
        if has_advance(run, advances) or off_on_board(run, board):
            continue
        emails = contacts(run, agents, list(past_advances) + list(advances), payees)
        todo.append(("welcome" if emails else "ask", run, emails, None))
    later = [a for a in advances
             if AUTO_NOTE in (a.get("staff_notes") or "") and (a.get("contact_email") or "").strip()
             and not a.get("welcome_sent_at") and a.get("show_date") and date.fromisoformat(a["show_date"]) > today]
    return todo, later


def still_missing(advances, today):
    """Advances this script made that still have no email and no welcome, on a
    reminder day (7, 3 or 1 days before the first night). Pure, for the tests.
    One note on the day the advance is made was easy to miss (Nov 19 2026)."""
    return [a for a in advances
            if AUTO_NOTE in (a.get("staff_notes") or "") and not (a.get("contact_email") or "").strip()
            and not a.get("welcome_sent_at") and not a.get("submitted_at") and a.get("show_date")
            and (date.fromisoformat(a["show_date"]) - today).days in REMIND_DAYS]


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


def ask_booking(run, advance_id, token=None, days_left=None):
    """A short note to booking@: we need an email for this show. The reminders
    (days_left set) also carry the comic's own link, ready to forward."""
    link = DESK + advance_id
    soon = f"Still no email, {days_left} day{'s' if days_left != 1 else ''} to go. " if days_left else ""
    subject = f"{'Reminder: ' if days_left else ''}Advance needs a contact: {run['title']}, {when(run)}"
    trip = (f"Or forward the comic their own advance link: {TRIP_URL}{token}\n\n") if token else ""
    trip_html = (f'<p>Or forward the comic their own advance link: <a href="{TRIP_URL}{token}">{TRIP_URL}{token}</a></p>') if token else ""
    text = (f"{soon}{run['title']} plays {when(run)}, and we don't have an email for the comic or their tour manager (agents rarely fill these in).\n\n"
            f"Add it on the booking desk: {link}\n\n{trip}"
            "That's it. The advance and the \"You're booked\" email go out the next morning by themselves.")
    html = (f"<p>{soon}{run['title']} plays {when(run)}, and we don't have an email for the comic or their tour manager (agents rarely fill these in).</p>"
            f'<p><a href="{link}">Add it on the booking desk</a></p>{trip_html}'
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
    # Read well past the three weeks: only runs starting inside them get an
    # advance, but the whole run has to be seen to know its last night.
    horizon = datetime.now(timezone.utc) + timedelta(days=DAYS_OUT + LOOK_AHEAD_DAYS)
    window = {"starts_at": f"gte.{datetime.now(timezone.utc).isoformat()}", "and": f"(starts_at.lte.{horizon.isoformat()})"}
    history = sb("GET", "show_history", params={"select": "show_title,event_title,starts_at", **window})
    history += website_nights(sb("GET", "exchange_showtimes", params={"select": "show_title,starts_at,price", **window}))
    board = sb("GET", "booking_shows", params={"select": "act,first_night,last_night,stage,checks",
                                               "first_night": f"gte.{today - timedelta(days=LOOK_BACK_DAYS)}"})
    advances = sb("GET", "advances", params={"select": "id,token,show_name,act_name,show_date,show_end_date,contact_email,staff_notes,welcome_sent_at,submitted_at",
                                             "show_date": f"gte.{today - timedelta(days=LOOK_BACK_DAYS)}"})
    agents = sb("GET", "show_agents", params={"select": "show_title,agent_name,agent_email"})
    past = sb("GET", "advances", params={"select": "show_name,act_name,show_date,contact_email",
                                         "contact_email": "not.is.null"})
    payees = sb("GET", "payees", params={"select": "name,email"})
    todo, later = plan(history, advances, agents, today, payees, past, board)
    remind = still_missing(advances, today)

    if not todo and not later and not remind:
        print("Nothing to do: every headliner run in the next 3 weeks already has an advance.")
    for action, run, emails, name in todo:
        # The log is public: say how many addresses, never the addresses.
        print(f"{when(run)} {run['title']}: " + (f"make advance + welcome to the comic ({len(emails)} address{'es' if len(emails) != 1 else ''})" if action == "welcome"
                                                else "make advance, ask booking@ for a contact"))
        if DRY_RUN:
            continue
        adv = make_advance(run, emails, name)
        if action == "welcome":
            send_welcome(adv["id"])
        else:
            ask_booking(run, adv["id"])
    for a in later:
        print(f"{a['show_date']} {a['show_name']}: email added on the desk, sending the welcome")
        if not DRY_RUN:
            send_welcome(a["id"])
    for a in remind:
        first = date.fromisoformat(a["show_date"])
        run = {"title": a["show_name"], "first": first,
               "last": date.fromisoformat(a["show_end_date"]) if a.get("show_end_date") else first}
        print(f"{when(run)} {a['show_name']}: still no email, reminding booking@")
        if not DRY_RUN:
            ask_booking(run, a["id"], a.get("token"), (first - today).days)
    if DRY_RUN:
        print("[DRY RUN] nothing made or sent.")


if __name__ == "__main__":
    main()
