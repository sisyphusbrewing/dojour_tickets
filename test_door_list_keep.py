"""The door database keeps Dojour buyers until their show, even if Dojour stops
listing the event (Sam, Nov 10 2026, winding Dojour down)."""
import unittest
from datetime import datetime, timedelta

from fetch_tickets import CENTRAL_TZ, format_show_date, shows_to_purge


def show(days):
    return format_show_date((datetime.now(CENTRAL_TZ) + timedelta(days=days)).replace(hour=19, minute=0, second=0, microsecond=0))


class KeepDojourBuyers(unittest.TestCase):
    def test_dojour_show_missing_from_feed_is_kept(self):
        d = show(30)
        rows = [{"unique_id": "dj_86885_abc", "show_date": d, "show_title": "Ian Fidance"}]
        self.assertEqual(shows_to_purge(rows, [], sources_ok=True), set())

    def test_website_show_missing_from_feed_is_dropped(self):
        d = show(30)
        rows = [{"unique_id": "shopify_1_2", "show_date": d, "show_title": "Old Show"}]
        self.assertEqual(shows_to_purge(rows, [], sources_ok=True), {(d, "Old Show")})

    def test_past_dojour_show_is_dropped(self):
        d = show(-3)
        rows = [{"unique_id": "dj_1_x", "show_date": d, "show_title": "Done"}]
        self.assertEqual(shows_to_purge(rows, [], sources_ok=True), {(d, "Done")})

    def test_listed_show_is_kept(self):
        d = show(10)
        rows = [{"unique_id": "shopify_1_2", "show_date": d, "show_title": "Live"}]
        active = [{"show_date": d, "show_title": "Live"}]
        self.assertEqual(shows_to_purge(rows, active, sources_ok=True), set())


if __name__ == "__main__":
    unittest.main()
