"""
Sisyphus - copies the events@ Google Calendar onto the staff Schedule.

The events@sisyphusbrewing.com Google Calendar is where the club's whole
calendar lives: headliner runs, the weekly nights, and the things the website
never sells tickets for (private parties, rentals, a group booked for an
afternoon). The staff Schedule only knew what was on sale on the website, so
staff never saw a private event coming (Sam, Nov 24 2026: "Is the staff
schedule showing private events too?" ... "Yeah can we pull those events from
the calendar?" ... "The calendar being the google calendar for
events@sisyphusbrewing.com").

Every hour the "Venue calendar" action runs this:

  1. Reads the calendar's private address (the "Secret address in iCal
     format"), kept in the database (venue_calendar_feed, service key only),
     never in this repo.
  2. Lists every event from yesterday to 90 days out, repeating events
     included, one row per day an event touches. Skipped: cancelled or
     tentative events, and holds ("HOLD ...", "Possible ..."), which are
     dates being asked about, not events.
  3. Saves them with venue_calendar_save(), which marks anything no longer on
     the calendar as gone. Nothing is deleted.

The database decides what staff see: schedule_needs() lists a calendar event
on its day unless the website already sells a show by that name that day,
and an event with a start time counts like a free event when it works out
how many people the day needs.

Only the title, the day and the times are kept: never the description, the
guests or the location, where phone numbers and emails live. This repo's
logs are public, so the script prints counts only, never titles.

Run with DRY_RUN=1 to count what it would save without saving anything.
"""

import datetime as dt
import os
import re
import sys
from zoneinfo import ZoneInfo

import requests

CENTRAL = ZoneInfo("America/Chicago")
DAYS_AHEAD = 90
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# A hold or a maybe is a date being asked about, not an event (the calendar
# has "HOLD Russians", "Stef Dag Hold", "Possible ..." next to real bookings).
HOLD = re.compile(r"\bhold\b|^\s*possible\b|^\s*tentative\b", re.I)


def keep(title, status):
    """Whether a calendar event should reach the Schedule."""
    title = (title or "").strip()
    if not title:
        return False
    if (status or "CONFIRMED").upper() in ("CANCELLED", "TENTATIVE"):
        return False
    return not HOLD.search(title)


def rows_from_ics(text, today, days=DAYS_AHEAD):
    """One dict per (event, day) from yesterday to `days` ahead, Minneapolis days."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(text)
    start = today - dt.timedelta(days=1)
    end = today + dt.timedelta(days=days + 1)
    out = {}
    for ev in recurring_ical_events.of(cal).between(start, end):
        title = str(ev.get("SUMMARY", "")).strip()
        if not keep(title, str(ev.get("STATUS", "")) if ev.get("STATUS") else None):
            continue
        s = ev.get("DTSTART").dt
        e = ev.get("DTEND").dt if ev.get("DTEND") else None
        uid = str(ev.get("UID", "")).strip() or title
        if isinstance(s, dt.datetime):
            if s.tzinfo is None:
                s = s.replace(tzinfo=CENTRAL)
            if e is None:
                e = s
            elif e.tzinfo is None:
                e = e.replace(tzinfo=CENTRAL)
            first = s.astimezone(CENTRAL).date()
            # A timed event belongs to the day it starts (a party to 1 AM is that night's).
            days_on = [first]
            starts, ends, all_day = s.astimezone(dt.timezone.utc), e.astimezone(dt.timezone.utc), False
        else:
            last = (e - dt.timedelta(days=1)) if isinstance(e, dt.date) and e > s else s
            days_on = [s + dt.timedelta(days=i) for i in range((last - s).days + 1)]
            starts = ends = None
            all_day = True
        for d in days_on:
            if not (start <= d <= end):
                continue
            key = (uid + "|" + (s.isoformat() if isinstance(s, dt.date) else ""), d.isoformat())
            out[key] = {
                "uid": key[0][:300],
                "day": d.isoformat(),
                "title": title[:120],
                "starts_at": starts.isoformat() if starts else None,
                "ends_at": ends.isoformat() if ends else None,
                "all_day": all_day,
            }
    return sorted(out.values(), key=lambda r: (r["day"], r["starts_at"] or "", r["title"]))


def sb(method, path, **kw):
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
    r = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=h, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def main():
    if not SUPABASE_URL or not SERVICE_KEY:
        print("Supabase settings are missing; nothing to do.")
        return 0
    feed = sb("GET", "venue_calendar_feed", params={"select": "ical_url"})
    url = (feed[0]["ical_url"] if feed else "") or ""
    if not url.startswith("https://calendar.google.com/"):
        print("No calendar address saved yet (venue_calendar_feed); nothing to do.")
        return 0
    r = requests.get(url, timeout=60, headers={"User-Agent": "sisyphus-staff-schedule"})
    if r.status_code != 200:
        print(f"The calendar could not be read (HTTP {r.status_code}).")
        return 1
    today = dt.datetime.now(CENTRAL).date()
    rows = rows_from_ics(r.content, today)
    timed = sum(1 for x in rows if not x["all_day"])
    print(f"{len(rows)} calendar day(s) from {today - dt.timedelta(days=1)} on ({timed} with a start time).")
    if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
        print("Dry run: nothing saved.")
        return 0
    res = sb("POST", "rpc/venue_calendar_save",
             json={"p_from": (today - dt.timedelta(days=1)).isoformat(), "p_rows": rows})
    print(f"Saved. {res.get('kept', 0)} on the calendar, {res.get('gone', 0)} no longer there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
