"""Tests for the purchase time the sync saves for the sales-by-day page."""
import unittest
from datetime import datetime

from fetch_tickets import dojour_purchase_time


class DojourPurchaseTime(unittest.TestCase):
    def test_dojour_timestamp_format(self):
        got = dojour_purchase_time({"timestamp": "2026-10-03T21:07:22+0000"})
        self.assertEqual(datetime.fromisoformat(got), datetime.fromisoformat("2026-10-03T21:07:22+00:00"))

    def test_z_suffix(self):
        got = dojour_purchase_time({"timestamp": "2026-10-03T21:07:22Z"})
        self.assertEqual(datetime.fromisoformat(got), datetime.fromisoformat("2026-10-03T21:07:22+00:00"))

    def test_missing_or_garbage(self):
        self.assertIsNone(dojour_purchase_time({}))
        self.assertIsNone(dojour_purchase_time({"timestamp": None}))
        self.assertIsNone(dojour_purchase_time({"timestamp": "yesterday"}))


if __name__ == "__main__":
    unittest.main()
