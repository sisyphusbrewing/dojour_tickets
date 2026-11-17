"""Checks for the Green Room safety report email (safety_notify.py)."""
import unittest

import booking_inbox
import safety_notify as s

SAM = ["sam@example.com"]
GRACE = ["grace@example.com"]


def report(**kw):
    row = {"id": "x", "what": "Someone kept\ngrabbing my arm.", "happened_on": None, "place": None,
           "who": None, "name": None, "contact": None, "send_to": "both", "via": "tag"}
    row.update(kw)
    return row


class Recipients(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(s.recipients("both", SAM, GRACE), SAM + GRACE)
        self.assertEqual(s.recipients("sam", SAM, GRACE), SAM)
        self.assertEqual(s.recipients("grace", SAM, GRACE), GRACE)

    def test_unknown_goes_to_both(self):
        self.assertEqual(s.recipients(None, SAM, GRACE), SAM + GRACE)
        self.assertEqual(s.recipients("everyone", SAM, GRACE), SAM + GRACE)

    def test_no_doubles(self):
        self.assertEqual(s.recipients("both", SAM, SAM), SAM)

    def test_only_sam_never_reaches_grace(self):
        msg = s.build_message(report(send_to="sam"))
        self.assertNotIn(s.GRACE_TO[0], msg["To"])
        self.assertIn(s.SAM_TO[0], msg["To"])

    def test_only_grace_never_reaches_sam(self):
        msg = s.build_message(report(send_to="grace"))
        self.assertNotIn(s.SAM_TO[0], msg["To"])


class Compose(unittest.TestCase):
    def test_anonymous(self):
        subject, lines = s.compose(report())
        body = "\n".join(lines)
        self.assertEqual(subject, "Safety report from the Green Room (anonymous)")
        self.assertIn("Sent by: Anonymous", body)
        self.assertIn("  Someone kept\n  grabbing my arm.", body)
        self.assertIn("no way to write back", body)
        self.assertIn("Sam and Grace", body)

    def test_named_with_email(self):
        r = report(name="Pat Example", contact="pat@example.com", place="Green room",
                   happened_on="2026-11-17", who="A guy in a red hat", send_to="sam")
        subject, lines = s.compose(r)
        body = "\n".join(lines)
        self.assertIn("from Pat Example", subject)
        self.assertIn("When: Tue, Nov 17", body)
        self.assertIn("Where: Green room", body)
        self.assertIn("Who was involved: A guy in a red hat", body)
        self.assertIn("How to reach them: pat@example.com", body)
        self.assertIn("Replying to this email reaches them.", body)
        self.assertIn("only Sam", body)
        self.assertEqual(s.build_message(r)["Reply-To"], "pat@example.com")

    def test_phone_only_has_no_reply_to(self):
        r = report(name="Pat", contact="612 555 0100")
        self.assertIsNone(s.build_message(r)["Reply-To"])
        self.assertNotIn("Replying to this email", "\n".join(s.compose(r)[1]))

    def test_named_without_contact(self):
        body = "\n".join(s.compose(report(name="Pat"))[1])
        self.assertIn("They left no way to reach them.", body)

    def test_marked_urgent(self):
        self.assertEqual(s.build_message(report())["X-Priority"], "1")

    def test_booking_board_skips_it(self):
        # The Booking board reads booking@; a safety report must never show
        # up there for other managers to see.
        subject, _ = s.compose(report())
        self.assertTrue(booking_inbox.OUR_AUTOMATIC.search(subject))


if __name__ == "__main__":
    unittest.main()
