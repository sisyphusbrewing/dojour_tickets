"""
Shared show-date reader for the Sisyphus ticket scripts.

Turns variant names like these into a Central-time datetime:
    "Sat, Oct 17 • 7:00 PM"      (older shows)
    "Sat Oct 17 • 7:00 PM"       (shows made by the Create Show button)
    "Sat Nov 14th 6pm"
    "Fri, Apr 2, 2027 • 9:00 PM"

When no year is written, the weekday decides it ("Sat, Apr 3" can only be
2027), otherwise the nearest date that isn't long past is used.
"""
import re
from datetime import datetime, timedelta
import zoneinfo

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_MONTH_DAY = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_WEEKDAY = re.compile(r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", re.IGNORECASE)


def parse_show_datetime(text, now=None, require_time=False):
    """Return a timezone-aware datetime, or None if no date can be read.

    require_time=True returns None when there is no clock time in the text
    (e.g. "Starts Sunday October 11th - Multiple Week Class"), so multi-week
    classes are never mistaken for a single show.
    """
    if not text:
        return None
    text = str(text)
    md = _MONTH_DAY.search(text)
    if not md:
        return None
    month = MONTHS[md.group(1).lower()[:3]]
    day = int(md.group(2))

    tm = _TIME.search(text, md.end())
    if tm:
        hour = int(tm.group(1)) % 12
        minute = int(tm.group(2)) if tm.group(2) else 0
        if tm.group(3).lower() == "pm":
            hour += 12
    elif require_time:
        return None
    else:
        hour, minute = 19, 0

    ym = _YEAR.search(text)
    if ym:
        try:
            return datetime(int(ym.group(1)), month, day, hour, minute, tzinfo=CENTRAL_TZ)
        except ValueError:
            return None

    now = now or datetime.now(CENTRAL_TZ)
    candidates = []
    for y in (now.year - 1, now.year, now.year + 1):
        try:
            candidates.append(datetime(y, month, day, hour, minute, tzinfo=CENTRAL_TZ))
        except ValueError:
            pass  # Feb 29 in a non-leap year
    if not candidates:
        return None

    wd = _WEEKDAY.match(text)
    if wd:
        target = WEEKDAYS[wd.group(1).lower()[:3]]
        matching = [c for c in candidates if c.weekday() == target]
        if matching:
            candidates = matching

    floor = now - timedelta(days=60)
    upcoming = [c for c in candidates if c >= floor]
    return min(upcoming) if upcoming else max(candidates)
