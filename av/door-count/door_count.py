"""
Sisyphus - tell the showroom Stream Deck how many guests the next show is
still waiting on (Sam, Nov 13 2026: "it should pull how many guests we are
waiting on").

Runs all day on the office PC (DESKTOP-8QOGQGK); setup.ps1 next to this file
starts it at sign-in. Every 30 seconds it:

1. Asks the door app's own numbers for tonight's shows (Supabase function
   door_shows: tickets sold and guests checked in at the door, website and
   Dojour tickets together).
2. Picks the next show: the earliest one tonight that hasn't been going for
   more than an hour. So after the 8 PM show it moves on to the 10 PM show.
3. Writes four Companion custom variables, which the START SHOW key reads:
       door_show   "8 PM" (which show the numbers are for)
       door_left   31     (guests not checked in yet; -1 = no show to count)
       door_total  94     (tickets for that show)
       door_at     the time of this reading; the key hides the count when
                   this is more than 3 minutes old, so a stale number never
                   sits on the deck if this script or the internet is down.

It signs in with the staff login "recorder", the same one the recordings job
uses. The password is in %USERPROFILE%\\.sisyphus\\recordings.env
(RECORDER_PASSWORD=...), never in the repo. No extra Python packages needed.

    python door_count.py          run until stopped
    python door_count.py --once   read once, print what the key would say
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ"  # public anon key, same as staff.js
LOGIN = "recorder@sisyphusbrewing.com"
COMPANION = "http://127.0.0.1:8000"
EVERY = 30                        # seconds between readings
STILL_NEXT = timedelta(hours=1)   # a show stays "the next show" until it has been going this long
SIGN_IN_EVERY = 45 * 60           # the sign-in lasts an hour; renew before it runs out
STATE_DIR = Path(os.environ.get("USERPROFILE") or Path.home()) / ".sisyphus"
LOG = STATE_DIR / "door-count.log"

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
# The door app writes show times as "Fri, Nov 13 • 8:00 PM" (sometimes with a year).
SHOW_DATE = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?\s*•\s*(\d{1,2}):(\d{2})\s*([AP]M)", re.I)


def show_start(show_date, now):
    """When a show starts, read from the door app's text. The office PC's clock is
    Minneapolis time, the same as the show times, so plain local times are compared.
    Returns None for text it can't read."""
    m = SHOW_DATE.search(show_date or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, day, year = MONTHS[m.group(1).lower()], int(m.group(2)), m.group(3)
    hour = int(m.group(4)) % 12 + (12 if m.group(6).upper() == "PM" else 0)
    years = [int(year)] if year else [now.year - 1, now.year, now.year + 1]
    starts = []
    for y in years:
        try:
            starts.append(datetime(y, month, day, hour, int(m.group(5))))
        except ValueError:   # Feb 29 in the wrong year
            pass
    # No year in the text: it is whichever one puts the show closest to now.
    return min(starts, key=lambda s: abs(s - now)) if starts else None


def hour_label(start):
    """8 PM, or 7:30 PM when it isn't on the hour."""
    hour = start.hour % 12 or 12
    minutes = f":{start.minute:02d}" if start.minute else ""
    return f"{hour}{minutes} {'PM' if start.hour >= 12 else 'AM'}"


def next_show(rows, now):
    """The show the deck should count for, from door_shows rows
    ({show_date, show_title, tickets, checked_in}). Returns
    {"show": "8 PM", "left": 31, "total": 94}, or None when there is no show left tonight.

    Two shows at the same time (Thursday's open mic in the other room): the deck is in
    the showroom, so the one with the most tickets wins."""
    upcoming = {}
    for row in rows:
        start = show_start(row.get("show_date"), now)
        if start is not None and start >= now - STILL_NEXT:
            upcoming.setdefault(start, []).append(row)
    if not upcoming:
        return None
    start = min(upcoming)
    show = max(upcoming[start], key=lambda r: r.get("tickets") or 0)
    total = int(show.get("tickets") or 0)
    here = int(show.get("checked_in") or 0)
    return {"show": hour_label(start), "left": max(total - here, 0), "total": total}


def key_text(reading):
    """What the START SHOW key says for a reading. The deck builds this itself from the
    variables (build_companion_config.py, DOOR_KEY); this copy is for --once and the tests."""
    if reading is None:
        return "START / SHOW"
    line = f"{reading['left']} TO COME" if reading["left"] else "ALL HERE"
    return f"START / {reading['show']} SHOW / {line}"


def load_env():
    env = STATE_DIR / "recordings.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def call(url, body=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
    return json.loads(text) if text.strip().startswith(("{", "[")) else text


def sign_in():
    token = call(f"{SUPABASE_URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON_KEY},
                 body={"email": LOGIN, "password": os.environ["RECORDER_PASSWORD"]})["access_token"]
    return {"apikey": ANON_KEY, "Authorization": "Bearer " + token}


def tell_deck(reading, now):
    values = {"door_show": reading["show"] if reading else "",
              "door_left": reading["left"] if reading else -1,
              "door_total": reading["total"] if reading else 0,
              "door_at": int(now.timestamp())}
    for name, value in values.items():
        call(f"{COMPANION}/api/custom-variable/{name}/value?value={urllib.parse.quote(str(value))}", timeout=5)


def log(message):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 500_000:   # keep the log small
            LOG.write_text("")
        with LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    once = "--once" in sys.argv
    load_env()
    headers, signed_in_at, last = None, 0, "just started"   # so the first reading is always logged
    while True:
        try:
            if headers is None or time.time() - signed_in_at > SIGN_IN_EVERY:
                headers, signed_in_at = sign_in(), time.time()
            now = datetime.now()
            reading = next_show(call(f"{SUPABASE_URL}/rest/v1/rpc/door_shows", body={}, headers=headers), now)
            if once:
                print(key_text(reading))
                return
            tell_deck(reading, now)
            if reading != last:   # log changes only, not every 30 seconds
                log(key_text(reading))
                last = reading
        except Exception as e:   # the internet, Supabase or Companion is down: say so and try again
            if once:
                raise
            problem = f"could not update the deck: {e}"
            if problem != last:   # once per problem, not every 30 seconds
                log(problem)
                last = problem
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                headers = None    # the sign-in ran out early: sign in again next time
        time.sleep(EVERY)


if __name__ == "__main__":
    main()
