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


class TellDeck(unittest.TestCase):
    """Companion on the office PC answers on the PC's network address, not on 127.0.0.1
    (found Nov 14 2026), so the helper has to find the address that answers."""

    def setUp(self):
        self.calls = []
        self.real_call, self.real_env = dc.call, dc.os.environ.get("COMPANION_URL")
        dc.os.environ.pop("COMPANION_URL", None)
        dc._answered = None
        self.addCleanup(self.restore)

    def restore(self):
        dc.call = self.real_call
        dc._answered = None
        dc.os.environ.pop("COMPANION_URL", None)
        if self.real_env is not None:
            dc.os.environ["COMPANION_URL"] = self.real_env

    def answer_only_on(self, good):
        def fake(url, body=None, headers=None, timeout=20):
            self.calls.append(url)
            if not url.startswith(good):
                raise dc.urllib.error.URLError("connection refused")
            return "ok"
        dc.call = fake

    def test_network_address_is_tried_first(self):
        self.assertEqual(dc.companion_addresses()[0], "http://192.168.86.42:8000")
        self.answer_only_on("http://192.168.86.42:8000")
        used = dc.tell_deck({"show": "8 PM", "left": 31, "total": 94}, TODAY)
        self.assertEqual(used, "http://192.168.86.42:8000")
        self.assertEqual(len(self.calls), 4)                      # the four door_* variables, one address
        self.assertIn("/api/custom-variable/door_left/value?value=31", self.calls[1])
        self.assertIn("door_show/value?value=8%20PM", self.calls[0])

    def test_falls_back_and_remembers_the_address_that_answered(self):
        self.answer_only_on("http://127.0.0.1:8000")
        self.assertEqual(dc.tell_deck(None, TODAY), "http://127.0.0.1:8000")
        self.calls.clear()
        dc.tell_deck(None, TODAY)
        self.assertTrue(all(u.startswith("http://127.0.0.1:8000") for u in self.calls))   # no wasted try

    def test_address_from_the_settings_file_wins(self):
        dc.os.environ["COMPANION_URL"] = "http://10.0.0.9:8000/"
        self.assertEqual(dc.companion_addresses()[0], "http://10.0.0.9:8000")

    def test_says_so_when_companion_answers_nowhere(self):
        self.answer_only_on("http://nowhere")
        with self.assertRaises(OSError) as caught:
            dc.tell_deck(None, TODAY)
        self.assertIn("did not answer", str(caught.exception))

    def test_a_missing_variable_is_reported_not_retried_elsewhere(self):
        def fake(url, body=None, headers=None, timeout=20):
            self.calls.append(url)
            raise dc.urllib.error.HTTPError(url, 404, "Not found", None, None)
        dc.call = fake
        with self.assertRaises(dc.urllib.error.HTTPError):
            dc.tell_deck(None, TODAY)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()


class OpeningTime(unittest.TestCase):
    """DAYTIME at opening (Sam, Nov 18 2026): once a day, only right at opening, never over a show."""
    TODAY = f"{TODAY:%Y-%m-%d}"

    def test_presses_in_the_first_half_hour(self):
        self.assertTrue(dc.should_open(0, self.TODAY, "", "off"))
        self.assertTrue(dc.should_open(29, self.TODAY, "2000-01-01", "day"))

    def test_not_before_opening_or_later_in_the_day(self):
        self.assertFalse(dc.should_open(None, self.TODAY, "", "off"))
        self.assertFalse(dc.should_open(30, self.TODAY, "", "off"))
        self.assertFalse(dc.should_open(-1, self.TODAY, "", "off"))

    def test_only_once_a_day(self):
        self.assertFalse(dc.should_open(5, self.TODAY, self.TODAY, "off"))

    def test_never_over_pre_show_or_a_show(self):
        self.assertFalse(dc.should_open(5, self.TODAY, "", "pre"))
        self.assertFalse(dc.should_open(5, self.TODAY, "", "show"))
