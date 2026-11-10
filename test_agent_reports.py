"""Weekly agent reports find a show's contact even when the show is renamed.

Sam Schedler's monthly Advice Column got no reports in Nov 2026: his contact
was saved as "Advice Column" and the November listing is "Advice Column!".
"""
import unittest

from send_weekly_agent_reports import contact_for, show_family


ROWS = [
    {"show_title": "Advice Column - Spooky Edition", "agent_email": "old@example.com",
     "updated_at": "2026-10-16T15:00:00+00:00", "token": "a"},
    {"show_title": "Advice Column", "agent_email": "new@example.com",
     "updated_at": "2026-11-10T14:30:00+00:00", "token": "b"},
    {"show_title": "Bo Johnson", "agent_email": "bo@example.com",
     "updated_at": "2026-10-25T00:00:00+00:00", "token": "c"},
    {"show_title": "No Email Show", "agent_email": None, "updated_at": "", "token": "d"},
]


class ShowFamily(unittest.TestCase):
    def test_editions_are_one_show(self):
        for t in ["Advice Column!", "Advice Column - Spooky Edition", "Advice Column (Late Show)",
                  "advice  column", "Advice Column: Holiday"]:
            self.assertEqual(show_family(t), "advice column", t)

    def test_empty(self):
        self.assertEqual(show_family(""), "")
        self.assertEqual(show_family(None), "")


class ContactFor(unittest.TestCase):
    def test_renamed_edition_uses_latest_contact(self):
        self.assertEqual(contact_for("Advice Column!", ROWS)["agent_email"], "new@example.com")

    def test_exact_title_wins(self):
        self.assertEqual(contact_for("Advice Column - Spooky Edition", ROWS)["agent_email"], "old@example.com")

    def test_other_shows_untouched(self):
        self.assertEqual(contact_for("Bo Johnson", ROWS)["token"], "c")
        self.assertIsNone(contact_for("Michael Longfellow", ROWS))
        self.assertIsNone(contact_for("No Email Show", ROWS))


if __name__ == "__main__":
    unittest.main()
