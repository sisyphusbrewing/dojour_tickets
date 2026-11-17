"""
Checks the email booking@ gets when someone asks to be paid: a comic from
payme/, or someone who worked the door from doorshift/ (Sam, Nov 17 2026).
Nothing is sent and no database is read: only the wording is checked.

    python -m unittest test_pay_request_notify
"""
import contextlib
import io
import unittest
from unittest import mock

import pay_request_notify as n

# Made-up people.
DOOR = {"name": "Alex Rivera", "handle": "@alexr", "role": "Door", "show_name": "Hana Weekend",
        "show_dates": "Fri, Nov 13", "show_end": "2026-11-13", "amount": None, "email": None, "phone": None, "note": None}
COMIC = {"name": "Hana Lee", "handle": "@hana", "role": "Feature", "show_name": "Hana Weekend",
         "show_dates": "Nov 13–14", "show_end": "2026-11-14", "amount": 355.5, "email": "hana@example.com",
         "phone": "612-555-0100", "note": "Two shows Saturday.\nThanks!"}
VENMO_ONLY = {"name": "Hana Lee", "handle": "@hana", "role": "", "show_name": "", "show_dates": None,
              "show_end": None, "amount": None, "email": None, "phone": None, "note": None}


class DoorShift(unittest.TestCase):
    def test_subject_says_door_shift_and_the_night(self):
        subject, _ = n.compose(DOOR)
        self.assertEqual(subject, "Door shift: Alex Rivera · Fri, Nov 13")

    def test_an_amount_is_shown_only_when_there_is_one(self):
        # The door form sends none; Sam sets it on the pay sheet.
        self.assertFalse(any("pay:" in line for line in n.compose(DOOR)[1]))
        subject, lines = n.compose(dict(DOOR, amount=35))
        self.assertEqual(subject, "Door shift: Alex Rivera · Fri, Nov 13 · $35")
        self.assertIn("  Door pay: $35", lines)

    def test_body_says_who_worked_which_night_and_how_to_pay(self):
        _, lines = n.compose(DOOR)
        self.assertEqual(lines[0], "Alex Rivera worked the door on Fri, Nov 13 (Hana Weekend).")
        self.assertIn("  Venmo: @alexr", lines)
        self.assertIn(f"Approve it and pay it on the pay sheet: {n.SHEET_URL}", lines)

    def test_a_door_shift_is_not_worded_like_a_comic_asking(self):
        text = "\n".join(n.compose(DOOR)[1])
        self.assertNotIn("wants to be paid", text)
        self.assertNotIn("Told:", text)
        self.assertNotIn("Did:", text)

    def test_door_in_any_letters_counts(self):
        self.assertTrue(n.compose(dict(DOOR, role=" door "))[0].startswith("Door shift:"))

    def test_no_night_and_no_amount_still_reads_right(self):
        subject, lines = n.compose(dict(DOOR, show_dates=None, show_name=""))
        self.assertEqual(subject, "Door shift: Alex Rivera · a show night")
        self.assertEqual(lines[0], "Alex Rivera worked the door on a show night.")
        self.assertFalse(any(line.startswith("  Door pay") for line in lines))


class ComicRequestIsAsItWas(unittest.TestCase):
    def test_subject(self):
        self.assertEqual(n.compose(COMIC)[0], "Pay request: Hana Lee · Hana Weekend · $355.50")

    def test_body(self):
        _, lines = n.compose(COMIC)
        self.assertEqual(lines[:7], ["Hana Lee wants to be paid for Hana Weekend (Nov 13–14).", "", "  Did: Feature",
                                     "  Told: $355.50", "  Venmo: @hana", "  Phone: 612-555-0100", "  Email: hana@example.com"])
        self.assertIn("  Two shows Saturday.\n  Thanks!", lines)

    def test_venmo_only(self):
        subject, lines = n.compose(VENMO_ONLY)
        self.assertEqual(subject, "Pay request: Hana Lee")
        self.assertEqual(lines[0], "Hana Lee left their Venmo.")
        self.assertEqual(lines[2], "  Venmo: @hana")


class PublicLog(unittest.TestCase):
    """This repo's Actions logs are public: a real run must not print who it was."""

    def test_a_real_run_prints_no_name_show_or_address(self):
        got = mock.Mock()
        got.json.return_value = [dict(COMIC)]
        out = io.StringIO()
        with mock.patch.object(n, "REQUEST_ID", "11111111-2222-3333-4444-555555555555"), \
             mock.patch.object(n, "DRY_RUN", False), \
             mock.patch.object(n, "SMTP_USER", "robot@example.com"), mock.patch.object(n, "SMTP_PASS", "x"), \
             mock.patch.object(n, "TO", ["someone@example.com"]), \
             mock.patch.object(n.requests, "get", return_value=got), \
             mock.patch.object(n.smtplib, "SMTP_SSL") as smtp, \
             contextlib.redirect_stdout(out):
            n.main()
        sent = smtp.return_value.__enter__.return_value.send_message
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(sent.call_args[0][0]["Subject"], "Pay request: Hana Lee · Hana Weekend · $355.50")
        printed = out.getvalue()
        for secret in ("Hana", "Weekend", "@hana", "example.com", "612-555"):
            self.assertNotIn(secret, printed)
        self.assertIn("Sent the pay request email", printed)


if __name__ == "__main__":
    unittest.main()
