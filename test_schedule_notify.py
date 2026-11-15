"""Checks for schedule_notify.py: who gets a schedule notice, and how.

These only test plan(), which decides what to send without touching the
network. Times are built from "now", never from today's date.
"""
import unittest
from datetime import datetime, timedelta, timezone

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


if __name__ == "__main__":
    unittest.main()
