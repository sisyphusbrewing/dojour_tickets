"""Checks for recording_mail.py: where the morning-after video goes.

The email on the advance is the default; an "Email for the video" typed on
the Booking board for that run wins (Sam, Nov 18 2026). Nothing is sent and
no network is touched: get, send and mark are swapped for fakes.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import recording_mail as rm


def iso(d):
    return d.isoformat()


class VideoEmailTest(unittest.TestCase):
    def setUp(self):
        # A show two nights ago at 8 PM Central (02:00 UTC the next day).
        self.night = (datetime.now(rm.CHICAGO) - timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0)
        self.day = self.night.date()
        starts = self.night.astimezone(timezone.utc).isoformat()
        self.recordings = [
            {"id": 1, "show_title": "Pat Example", "starts_at": starts, "part": "headliner", "link": "https://drive.example/1", "note": None},
            {"id": 2, "show_title": "Pat Example", "starts_at": starts, "part": "full", "link": "https://drive.example/2", "note": None},
        ]
        self.advances = [{"contact_name": "Pat Example", "contact_email": "agent@example.com", "act_name": "Pat Example",
                          "show_name": "Pat Example", "show_date": iso(self.day), "show_end_date": iso(self.day + timedelta(days=1))}]
        self.board = []
        self.sent = []

    def fake_get(self, table, params):
        if table == "recordings":
            return self.recordings
        if table == "advances":
            return self.advances
        if table == "booking_shows":
            return [b for b in self.board if b["first_night"] <= self.day.isoformat() and (b.get("info") or {}).get("footage")]
        raise AssertionError(table)

    def run_main(self):
        with mock.patch.object(rm, "get", self.fake_get), \
             mock.patch.object(rm, "send", lambda to, subject, body, text, bcc: self.sent.append((to, subject, text, bcc))), \
             mock.patch.object(rm, "mark", lambda ids, to: None), \
             mock.patch.object(rm, "PREVIEW_TO", ""):
            rm.main()
        return self.sent

    def test_advance_email_by_default(self):
        sent = self.run_main()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "agent@example.com")
        self.assertTrue(sent[0][2].startswith("Hey Pat,"))
        self.assertEqual(sent[0][3], [rm.BOOKING])

    def test_show_in_pieces_goes_to_booking(self):
        # Nov 19 2026: OBS saved one show as several files; the later ones are
        # "(from 8.54PM)". Nobody guesses which piece is the headliner's.
        starts = self.recordings[0]["starts_at"]
        self.recordings.append({"id": 3, "show_title": "Pat Example", "starts_at": starts,
                                "part": "headliner (from 8.54PM)", "link": "https://drive.example/3", "note": None})
        sent = self.run_main()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], rm.BOOKING)
        self.assertIn("pieces", sent[0][1])
        self.assertIn("https://drive.example/3", sent[0][2])

    def test_board_email_wins(self):
        self.board = [{"act": "Pat Example", "first_night": iso(self.day), "last_night": iso(self.day + timedelta(days=1)),
                       "stage": "confirmed", "info": {"footage": "pat@example.com"}}]
        sent = self.run_main()
        self.assertEqual(sent[0][0], "pat@example.com")
        # Not the person on the advance, so no first name.
        self.assertTrue(sent[0][2].startswith("Hey,"))

    def test_board_email_without_an_advance(self):
        self.advances = []
        self.board = [{"act": "Pat Example", "first_night": iso(self.day), "last_night": None,
                       "stage": "confirmed", "info": {"footage": "pat@example.com"}}]
        sent = self.run_main()
        self.assertEqual(sent[0][0], "pat@example.com")
        self.assertIn("Your video", sent[0][1])

    def test_other_runs_and_dropped_runs_dont_count(self):
        self.board = [
            {"act": "Someone Else", "first_night": iso(self.day), "last_night": None, "stage": "confirmed", "info": {"footage": "x@example.com"}},
            {"act": "Pat Example", "first_night": iso(self.day - timedelta(days=30)), "last_night": iso(self.day - timedelta(days=29)),
             "stage": "confirmed", "info": {"footage": "old@example.com"}},
            {"act": "Pat Example", "first_night": iso(self.day), "last_night": None, "stage": "dropped", "info": {"footage": "gone@example.com"}},
        ]
        sent = self.run_main()
        self.assertEqual(sent[0][0], "agent@example.com")

    def test_no_email_anywhere_goes_to_booking(self):
        self.advances = []
        sent = self.run_main()
        self.assertEqual(sent[0][0], rm.BOOKING)
        self.assertIn("no email for the headliner", sent[0][1])


if __name__ == "__main__":
    unittest.main()
