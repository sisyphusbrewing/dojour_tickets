"""Checks for venue_calendar.py: which events@ calendar events reach the Schedule, on which days.
Dates are built from today, so these pass whenever they run."""

import datetime as dt
import unittest

import venue_calendar as vc

TODAY = dt.date.today()


def d(n):
    return (TODAY + dt.timedelta(days=n)).strftime("%Y%m%d")


def ics(*events):
    body = "".join("BEGIN:VEVENT\r\n" + "".join(line + "\r\n" for line in e) + "END:VEVENT\r\n" for e in events)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n" + body + "END:VCALENDAR\r\n").encode()


def ev(uid, title, start, end=None, *extra):
    """start and end are ("<params>:", "<value>"), e.g. (";VALUE=DATE:", "20261225")."""
    lines = ["UID:" + uid, "SUMMARY:" + title, "DTSTART" + start[0] + start[1]]
    if end:
        lines.append("DTEND" + end[0] + end[1])
    return lines + [k + (v if v.startswith(":") else ":" + v) for k, v in extra]


class Keep(unittest.TestCase):
    def test_holds_and_maybes_are_left_off(self):
        for t in ("HOLD Russians", "Stef Dag Hold", "DJ Demers HOLD 6p", "Possible Sophie Buddle", "Tentative: brunch"):
            self.assertFalse(vc.keep(t, None), t)

    def test_real_events_stay(self):
        for t in ("Sip and Sitch", "Josh Light Wedding Rental", "Holden's birthday", "Russian Comedy (doors 3:30p)"):
            self.assertTrue(vc.keep(t, "CONFIRMED"), t)

    def test_cancelled_tentative_and_blank_are_left_off(self):
        self.assertFalse(vc.keep("Party", "CANCELLED"))
        self.assertFalse(vc.keep("Party", "TENTATIVE"))
        self.assertFalse(vc.keep("  ", None))


class Rows(unittest.TestCase):
    def test_timed_event_lands_on_its_minneapolis_day(self):
        # 7 PM to 10 PM Central on day 5 is 01:00 to 04:00 UTC on day 6.
        text = ics(ev("a", "Birthday party", (":", d(6) + "T010000Z"), (":", d(6) + "T040000Z")))
        rows = vc.rows_from_ics(text, TODAY)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["day"], (TODAY + dt.timedelta(days=5)).isoformat())
        self.assertFalse(r["all_day"])
        self.assertEqual(r["title"], "Birthday party")
        self.assertTrue(r["starts_at"].startswith((TODAY + dt.timedelta(days=6)).isoformat() + "T01:00"))

    def test_all_day_event_covers_each_day(self):
        text = ics(ev("b", "Wedding rental", (";VALUE=DATE:", d(10)), (";VALUE=DATE:", d(12))))
        rows = vc.rows_from_ics(text, TODAY)
        self.assertEqual([r["day"] for r in rows], [(TODAY + dt.timedelta(days=n)).isoformat() for n in (10, 11)])
        self.assertTrue(all(r["all_day"] and r["starts_at"] is None for r in rows))
        self.assertEqual(len({(r["uid"], r["day"]) for r in rows}), 2)

    def test_weekly_event_repeats_with_one_week_moved(self):
        text = ics(
            ev("w", "Trivia", (";TZID=America/Chicago:", d(1) + "T190000"), (";TZID=America/Chicago:", d(1) + "T210000"),
               ("RRULE", "FREQ=WEEKLY;COUNT=3")),
            ev("w", "Trivia (moved)", (";TZID=America/Chicago:", d(9) + "T180000"), (";TZID=America/Chicago:", d(9) + "T200000"),
               ("RECURRENCE-ID;TZID=America/Chicago", ":" + d(8) + "T190000")),
        )
        rows = vc.rows_from_ics(text, TODAY)
        got = [(r["day"], r["title"]) for r in rows]
        want = [((TODAY + dt.timedelta(days=1)).isoformat(), "Trivia"),
                ((TODAY + dt.timedelta(days=9)).isoformat(), "Trivia (moved)"),
                ((TODAY + dt.timedelta(days=15)).isoformat(), "Trivia")]
        self.assertEqual(got, want)
        self.assertEqual(len({(r["uid"], r["day"]) for r in rows}), 3)

    def test_past_far_future_holds_and_cancelled_are_left_off(self):
        text = ics(
            ev("p", "Old party", (";VALUE=DATE:", d(-5))),
            ev("f", "Far party", (";VALUE=DATE:", d(200))),
            ev("h", "HOLD Russians", (";VALUE=DATE:", d(3))),
            ev("c", "Called off", (";VALUE=DATE:", d(4)), None, ("STATUS", "CANCELLED")),
            ev("k", "Kept", (";VALUE=DATE:", d(4))),
        )
        self.assertEqual([r["title"] for r in vc.rows_from_ics(text, TODAY)], ["Kept"])

    def test_nothing_but_title_and_times_is_kept(self):
        text = ics(ev("x", "Group", (";VALUE=DATE:", d(2)), None,
                      ("DESCRIPTION", "Call Pat 612-555-0100"), ("LOCATION", "Back room"), ("ATTENDEE", "mailto:pat@example.com")))
        rows = vc.rows_from_ics(text, TODAY)
        self.assertEqual(set(rows[0]), {"uid", "day", "title", "starts_at", "ends_at", "all_day"})
        self.assertNotIn("612", repr(rows))


if __name__ == "__main__":
    unittest.main()
