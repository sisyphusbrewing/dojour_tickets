"""Checks for schedule_notify.py: who gets a schedule notice, and how.

These test plan(), which decides what to send without touching the network,
and the two-minute watch loop with the sending and the waiting swapped out.
Times are built from "now", never from today's date.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import requests

import schedule_notify as sn

NOW = datetime.now(timezone.utc)


def notice(i, user="u1", kind="shift_new", by="email", email="a@example.com", phone="6125550100",
           name="Pat Example", hours_old=0.1, body=None):
    return {"id": i, "user_id": user, "kind": kind, "body": body or f"Notice {i}",
            "created_at": (NOW - timedelta(hours=hours_old)).isoformat(),
            "name": name, "notify_by": by, "notify_email": email, "notify_phone": phone}


class PlanTest(unittest.TestCase):
    def test_email_choice_gets_one_email(self):
        deliveries, skipped = sn.plan([notice(1)], can_text=True, now=NOW)
        self.assertEqual([(d["how"], d["to"]) for d in deliveries], [("email", "a@example.com")])
        self.assertEqual(deliveries[0]["subject"], "New shift for you")
        self.assertIn("Hi Pat,", deliveries[0]["body"])
        self.assertIn("Notice 1", deliveries[0]["body"])
        self.assertEqual(skipped, {})

    def test_text_choice_gets_a_text_when_texts_are_on(self):
        deliveries, _ = sn.plan([notice(1, by="text")], can_text=True, now=NOW)
        self.assertEqual([(d["how"], d["to"]) for d in deliveries], [("text", "+16125550100")])
        self.assertTrue(deliveries[0]["body"].startswith("Sisyphus: Notice 1"))

    def test_text_choice_falls_back_to_email_until_texts_are_on(self):
        deliveries, _ = sn.plan([notice(1, by="text")], can_text=False, now=NOW)
        self.assertEqual([d["how"] for d in deliveries], ["email"])

    def test_both_gets_both(self):
        deliveries, _ = sn.plan([notice(1, by="both")], can_text=True, now=NOW)
        self.assertEqual(sorted(d["how"] for d in deliveries), ["email", "text"])

    def test_both_without_texting_is_one_email_not_two(self):
        deliveries, _ = sn.plan([notice(1, by="both")], can_text=False, now=NOW)
        self.assertEqual([d["how"] for d in deliveries], ["email"])

    def test_none_gets_nothing(self):
        deliveries, skipped = sn.plan([notice(1, by="none")], can_text=True, now=NOW)
        self.assertEqual(deliveries, [])
        self.assertEqual(skipped, {1: "asked for no notices"})

    def test_no_contact_on_file_is_skipped_not_crashed(self):
        deliveries, skipped = sn.plan([notice(1, email=None, phone=None)], can_text=True, now=NOW)
        self.assertEqual(deliveries, [])
        self.assertEqual(skipped, {1: "no email or mobile number on file"})

    def test_text_choice_with_no_number_uses_the_email(self):
        deliveries, _ = sn.plan([notice(1, by="text", phone=None)], can_text=True, now=NOW)
        self.assertEqual([d["how"] for d in deliveries], ["email"])

    def test_several_notices_for_one_person_are_one_email(self):
        rows = [notice(1), notice(2, kind="reminder"), notice(3, user="u2", email="b@example.com")]
        deliveries, _ = sn.plan(rows, can_text=False, now=NOW)
        self.assertEqual(len(deliveries), 2)
        mine = [d for d in deliveries if d["to"] == "a@example.com"][0]
        self.assertEqual(mine["ids"], [1, 2])
        self.assertEqual(mine["subject"], "Sisyphus schedule: 2 updates")
        self.assertIn("- Notice 1", mine["body"])
        self.assertIn("- Notice 2", mine["body"])

    def test_clock_notice_links_to_the_clock(self):
        deliveries, _ = sn.plan([notice(1, kind="clock_open")], can_text=False, now=NOW)
        self.assertEqual(deliveries[0]["subject"], "Did you forget to clock out?")
        self.assertIn("The clock: " + sn.CLOCK_URL, deliveries[0]["body"])
        self.assertNotIn("The schedule: ", deliveries[0]["body"])

    def test_schedule_notice_still_links_to_the_schedule(self):
        deliveries, _ = sn.plan([notice(1)], can_text=False, now=NOW)
        self.assertIn("The schedule: " + sn.PAGE_URL, deliveries[0]["body"])
        self.assertNotIn("The clock: ", deliveries[0]["body"])

    def test_mixed_notices_link_to_both_pages(self):
        deliveries, _ = sn.plan([notice(1, kind="clock_fixed"), notice(2, kind="shift_changed")],
                                can_text=False, now=NOW)
        self.assertEqual(len(deliveries), 1)
        self.assertIn("The clock: " + sn.CLOCK_URL, deliveries[0]["body"])
        self.assertIn("The schedule: " + sn.PAGE_URL, deliveries[0]["body"])

    def test_every_clock_notice_has_its_own_subject(self):
        for kind in ("clock_typed", "clock_fixed", "clock_open"):
            deliveries, _ = sn.plan([notice(1, kind=kind)], can_text=False, now=NOW)
            self.assertNotEqual(deliveries[0]["subject"], "Schedule update", kind)

    def test_stale_reminder_is_dropped(self):
        rows = [notice(1, kind="reminder", hours_old=20), notice(2, kind="reminder", hours_old=2)]
        deliveries, skipped = sn.plan(rows, can_text=False, now=NOW)
        self.assertEqual(deliveries[0]["ids"], [2])
        self.assertEqual(skipped, {1: "too late to be useful"})

    def test_anything_older_than_three_days_is_dropped(self):
        deliveries, skipped = sn.plan([notice(1, hours_old=80)], can_text=False, now=NOW)
        self.assertEqual(deliveries, [])
        self.assertIn(1, skipped)

    def test_long_text_is_cut_short(self):
        rows = [notice(i, by="text", body="x" * 200) for i in range(1, 6)]
        deliveries, _ = sn.plan(rows, can_text=True, now=NOW)
        self.assertLessEqual(len(deliveries[0]["body"]), sn.TEXT_MAX)
        self.assertTrue(deliveries[0]["body"].endswith("More on the schedule page."))

    def test_mask_hides_addresses(self):
        self.assertEqual(sn.mask("jane@example.com"), "j***@example.com")
        self.assertEqual(sn.mask("+16125550100"), "***-0100")


def central(hour, minute=0):
    """A moment at this hour in Minneapolis, on whatever day it is there now."""
    return datetime.now(sn.CENTRAL).replace(hour=hour, minute=minute, second=0, microsecond=0)


class QuietHoursTest(unittest.TestCase):
    def test_the_small_hours_are_quiet(self):
        for hour in (1, 2, 5, 7):
            self.assertTrue(sn.quiet_hours(central(hour, 30)), hour)

    def test_closing_time_and_the_morning_are_not(self):
        # A bartender offering up a shift at 12:45 AM still reaches people,
        # and the 9 AM "you work today" has an hour of room before it.
        for hour in (0, 8, 9, 13, 23):
            self.assertFalse(sn.quiet_hours(central(hour, 45)), hour)


class Clock:
    """A pretend clock: sleeping moves it forward instead of waiting."""
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class WatchTest(unittest.TestCase):
    def run_watch(self, minutes, looks, quiet=False):
        clock = Clock()
        with mock.patch.object(sn, "main", side_effect=looks) as main, \
             mock.patch.object(sn.time, "monotonic", clock.monotonic), \
             mock.patch.object(sn.time, "sleep", clock.sleep), \
             mock.patch.object(sn, "quiet_hours", return_value=quiet), \
             mock.patch("builtins.print") as printed:
            try:
                sn.watch(minutes)
                ended = None
            except SystemExit as stop:
                ended = stop.code
        said = " ".join(str(c.args[0]) for c in printed.call_args_list)
        return main.call_count, said, ended

    def test_looks_every_two_minutes_and_stops_on_time(self):
        # Ten minutes is five looks: at 0, 2, 4, 6 and 8 minutes.
        count, said, ended = self.run_watch(10, [0, 3, 0, 1, 0])
        self.assertEqual(count, 5)
        self.assertIn("Looked 5 time(s), sent 4 notice(s), 0 look(s) failed.", said)
        self.assertIsNone(ended)

    def test_one_bad_look_does_not_stop_the_watch(self):
        looks = [0, requests.ConnectionError("down"), 2, OSError("mail"), 0]
        count, said, ended = self.run_watch(10, looks)
        self.assertEqual(count, 5)
        self.assertIn("sent 2 notice(s), 2 look(s) failed", said)
        self.assertIsNone(ended)

    def test_every_look_failing_ends_in_an_error(self):
        count, said, ended = self.run_watch(6, [requests.ConnectionError("down")] * 3)
        self.assertEqual(count, 3)
        self.assertIn("Every look failed", str(ended))

    def test_nothing_is_sent_in_quiet_hours(self):
        count, said, ended = self.run_watch(10, [5] * 5, quiet=True)
        self.assertEqual(count, 0)
        self.assertIn("Looked 5 time(s), sent 0 notice(s)", said)
        self.assertIsNone(ended)

    def test_a_failed_look_never_prints_who_it_was_for(self):
        # The action's log is public. Only the kind of error is printed.
        looks = [requests.ConnectionError("could not reach pat@example.com"), 0]
        count, said, ended = self.run_watch(4, looks)
        self.assertNotIn("pat@example.com", said)
        self.assertIn("ConnectionError", said)


if __name__ == "__main__":
    unittest.main()
