"""Checks for the comics' ad results refresh (comic_ads_refresh.py)."""
import datetime as dt
import unittest

import comic_ads_refresh as c

TODAY = dt.date.today()


def day(n):
    return (TODAY + dt.timedelta(days=n)).isoformat()


class WhichCampaigns(unittest.TestCase):
    def test_running_campaign_is_fetched(self):
        self.assertTrue(c.needs_refresh({"starts_on": day(-5), "ends_on": day(10)}, TODAY))

    def test_no_dates_is_fetched(self):
        self.assertTrue(c.needs_refresh({}, TODAY))

    def test_just_ended_is_still_fetched(self):
        self.assertTrue(c.needs_refresh({"ends_on": day(-3)}, TODAY))

    def test_long_finished_keeps_its_final_numbers(self):
        self.assertFalse(c.needs_refresh({"ends_on": day(-4)}, TODAY))

    def test_not_started_yet_is_skipped(self):
        self.assertFalse(c.needs_refresh({"starts_on": day(1)}, TODAY))


class Reddit(unittest.TestCase):
    def test_money_is_in_millionths(self):
        body = {"data": {"metrics": [
            {"campaign_id": "111", "spend": 4_750_000, "impressions": 635, "reach": 600, "clicks": 26},
            {"campaign_id": "222", "spend": 1, "impressions": 1, "reach": 1, "clicks": 0},
        ]}}
        got = c.parse_reddit(body)
        self.assertEqual(got["111"], {"spend": 4.75, "impressions": 635, "reach": 600, "clicks": 26})
        self.assertEqual(got["222"]["spend"], 0.0)

    def test_empty_report(self):
        self.assertEqual(c.parse_reddit({"data": {"metrics": []}}), {})
        self.assertEqual(c.parse_reddit(None), {})

    def test_report_asks_for_whole_hours_and_no_day_split(self):
        start = dt.datetime(2026, 11, 15, 0, 0, tzinfo=dt.timezone.utc)
        now = dt.datetime(2026, 11, 18, 4, 37, 12, tzinfo=dt.timezone.utc)
        b = c.reddit_report_body(start, now)["data"]
        self.assertEqual(b["starts_at"], "2026-11-15T00:00:00Z")
        self.assertEqual(b["ends_at"], "2026-11-18T05:00:00Z")
        self.assertEqual(b["breakdowns"], ["CAMPAIGN_ID"])
        self.assertNotIn("DATE", b["breakdowns"])  # reach would be added up day by day
        self.assertIn("REACH", b["fields"])


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 300:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, reddit_body):
        self.reddit_body = reddit_body
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("post", url, kw))
        if url.endswith("/functions/v1/reddit-ads"):
            return FakeResponse({"status": 200, "body": self.reddit_body})
        return FakeResponse(None, 201)

    def delete(self, url, **kw):
        self.calls.append(("delete", url, kw))
        return FakeResponse(None, 204)


class RedditKey(unittest.TestCase):
    def test_one_time_key_is_made_used_and_deleted(self):
        s = FakeSession({"data": {"metrics": [
            {"campaign_id": "111", "spend": 2_000_000, "impressions": 10, "reach": 9, "clicks": 1}]}})
        now = dt.datetime.now(dt.timezone.utc)
        got = c.fetch_reddit([
            {"account_id": "a2_x", "campaign_id": "111", "starts_on": day(-2)},
            {"account_id": "a2_x", "campaign_id": "333", "starts_on": day(-2)},
        ], now, session=s)
        self.assertEqual(got["111"]["spend"], 2.0)
        self.assertEqual(got["333"]["spend"], 0)  # no line yet = nothing spent
        kinds = [k for k, url, _ in s.calls]
        self.assertEqual(kinds[0], "post")
        self.assertTrue(s.calls[0][1].endswith("/rest/v1/reddit_tool_keys"))
        self.assertEqual(kinds[-1], "delete")
        made = s.calls[0][2]["json"]["key_hash"]
        self.assertEqual(s.calls[-1][2]["params"]["key_hash"], f"eq.{made}")
        used = s.calls[1][2]["headers"]["x-tool-key"]
        self.assertNotEqual(used, made)  # only the hash is stored
        self.assertEqual(len(made), 64)


class Meta(unittest.TestCase):
    def test_link_clicks_not_all_clicks(self):
        got = c.parse_meta({"spend": "4.75", "impressions": "659", "reach": "635",
                            "clicks": "60", "inline_link_clicks": "26", "date_stop": "2026-11-16"})
        self.assertEqual(got, {"spend": 4.75, "impressions": 659, "reach": 635, "clicks": 26,
                               "data_through": "2026-11-16"})

    def test_nothing_spent_yet(self):
        self.assertEqual(c.parse_meta(None)["spend"], 0)


if __name__ == "__main__":
    unittest.main()
