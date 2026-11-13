"""Tests for the Stream Deck's "guests still to come" count (Sam, Nov 13 2026).
The count goes on the START SHOW key, so staff read it as real people: it has to be the
next show's tickets minus the guests the door has checked in."""
import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("door_count", Path(__file__).parent / "av/door-count/door_count.py")
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)

# Tonight, built from today's date so the tests never depend on the calendar.
TODAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def door_text(when):
    """A show time the way the door app writes it: "Fri, Nov 13 • 8:00 PM"."""
    return f"{when:%a}, {when:%b} {when.day} • {when.hour % 12 or 12}:{when.minute:02d} {'PM' if when.hour >= 12 else 'AM'}"


def row(hour, minute=0, tickets=0, checked_in=0, title="Headliner", day=0):
    when = TODAY + timedelta(days=day, hours=hour, minutes=minute)
    return {"show_date": door_text(when), "show_title": title, "tickets": tickets, "checked_in": checked_in}


def at(hour, minute=0):
    return TODAY + timedelta(hours=hour, minutes=minute)


class NextShow(unittest.TestCase):
    TWO_SHOWS = [row(20, tickets=94, checked_in=63), row(22, tickets=77)]

    def test_counts_tickets_minus_checked_in_for_the_next_show(self):
        self.assertEqual(dc.next_show(self.TWO_SHOWS, at(19, 30)), {"show": "8 PM", "left": 31, "total": 94})

    def test_stays_on_a_show_that_is_starting_late(self):
        self.assertEqual(dc.next_show(self.TWO_SHOWS, at(20, 40))["show"], "8 PM")

    def test_moves_to_the_late_show_once_the_early_one_is_an_hour_in(self):
        self.assertEqual(dc.next_show(self.TWO_SHOWS, at(21, 30)), {"show": "10 PM", "left": 77, "total": 77})

    def test_nothing_to_count_after_the_last_show_or_on_a_dark_night(self):
        self.assertIsNone(dc.next_show(self.TWO_SHOWS, at(23, 30)))
        self.assertIsNone(dc.next_show([], at(19)))

    def test_last_nights_shows_do_not_count_after_midnight(self):
        # the door app keeps last night's shows on its list until 5 AM
        self.assertIsNone(dc.next_show([row(22, tickets=77, day=-1)], at(1)))

    def test_everyone_in_and_never_below_zero(self):
        self.assertEqual(dc.next_show([row(20, tickets=70, checked_in=70)], at(20))["left"], 0)
        self.assertEqual(dc.next_show([row(20, tickets=70, checked_in=72)], at(20))["left"], 0)

    def test_same_time_in_two_rooms_counts_the_bigger_show(self):
        rows = [row(20, tickets=6, title="Open Mic"), row(20, tickets=70, checked_in=10, title="Headliner")]
        self.assertEqual(dc.next_show(rows, at(19)), {"show": "8 PM", "left": 60, "total": 70})

    def test_half_past_show_times_and_text_it_cannot_read(self):
        self.assertEqual(dc.next_show([row(19, 30, tickets=40)], at(18))["show"], "7:30 PM")
        self.assertIsNone(dc.next_show([{"show_date": "sometime soon", "tickets": 9, "checked_in": 0}], at(18)))


class ShowStart(unittest.TestCase):
    def test_reads_the_door_apps_text(self):
        now = datetime(2026, 11, 13, 17, 0)
        self.assertEqual(dc.show_start("Fri, Nov 13 • 8:00 PM", now), datetime(2026, 11, 13, 20, 0))
        self.assertEqual(dc.show_start("Sat, Nov 14, 2026 • 12:30 PM", now), datetime(2026, 11, 14, 12, 30))

    def test_no_year_means_the_nearest_one(self):
        self.assertEqual(dc.show_start("Thu, Dec 31 • 10:00 PM", datetime(2027, 1, 1, 0, 30)), datetime(2026, 12, 31, 22, 0))


class KeyText(unittest.TestCase):
    def test_what_the_key_says(self):
        self.assertEqual(dc.key_text({"show": "8 PM", "left": 31, "total": 94}), "START / 8 PM SHOW / 31 TO COME")
        self.assertEqual(dc.key_text({"show": "8 PM", "left": 0, "total": 94}), "START / 8 PM SHOW / ALL HERE")
        self.assertEqual(dc.key_text(None), "START / SHOW")


if __name__ == "__main__":
    unittest.main()
