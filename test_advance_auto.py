"""Tests for advance_auto.plan(): which shows get an automatic advance, and who it goes to.
Dates are built relative to today so the tests never go stale."""
import unittest
from datetime import datetime, time, timedelta

from advance_auto import CENTRAL, plan, website_nights


def night(title, days, hour=19):
    """A show_history row for a showtime `days` from today at `hour` Central."""
    day = datetime.now(CENTRAL).date() + timedelta(days=days)
    ts = datetime.combine(day, time(hour), CENTRAL).astimezone().isoformat()
    return {"show_title": title, "starts_at": ts}


def web(title, days, price=25, hour=19):
    """An exchange_showtimes row: a showtime on sale on the website."""
    return dict(night(title, days, hour), price=price)


TODAY = datetime.now(CENTRAL).date()


class PlanTest(unittest.TestCase):
    def test_run_inside_three_weeks_with_comic_email_gets_welcome(self):
        hist = [night("Pat Example", 10), night("Pat Example", 11), night("Pat Example", 11, 21)]
        todo, _ = plan(hist, [], [{"show_title": "Pat Example", "agent_email": "pat@gmail.com"}], TODAY)
        self.assertEqual(len(todo), 1)
        action, run, emails, _ = todo[0]
        self.assertEqual(action, "welcome")
        self.assertEqual(emails, ["pat@gmail.com"])
        self.assertEqual((run["last"] - run["first"]).days, 1)   # Fri + Sat = one run

    def test_agency_address_is_not_the_contact(self):
        hist = [night("Pat Example", 10)]
        agents = [{"show_title": "Pat Example", "agent_email": "someone.assistant@wmeagency.com, x@caa.com"}]
        todo, _ = plan(hist, [], agents, TODAY)
        self.assertEqual(todo[0][0], "ask")

    def test_comic_email_found_on_pay_list_or_old_advance(self):
        hist = [night("Pat Example: The Tour", 5)]
        todo, _ = plan(hist, [], [], TODAY, payees=[{"name": "Pat Example", "email": "pat@me.com"}])
        self.assertEqual(todo[0][2], ["pat@me.com"])
        todo, _ = plan(hist, [], [], TODAY, past_advances=[{"show_name": "Pat Example", "contact_email": "pat@icloud.com"}])
        self.assertEqual(todo[0][2], ["pat@icloud.com"])

    def test_too_far_out_waits(self):
        todo, _ = plan([night("Pat Example", 30)], [], [], TODAY)
        self.assertEqual(todo, [])

    def test_recurring_and_cancelled_shows_skipped(self):
        hist = [night("Blingo", 3), night("Advice Column!", 4), night("The Magicians", 5),
                night("Magic: The Gathering Night", 6), night("CANCELED: Pat Example", 7)]
        todo, _ = plan(hist, [], [], TODAY)
        self.assertEqual(todo, [])

    def test_existing_advance_left_alone(self):
        hist = [night("Pat Example", 10), night("Pat Example", 11)]
        adv = [{"show_name": "Pat Example", "show_date": (TODAY + timedelta(days=10)).isoformat()}]
        todo, _ = plan(hist, adv, [], TODAY)
        self.assertEqual(todo, [])

    def test_email_added_on_desk_gets_sent_next_morning(self):
        adv = [{"id": "a1", "show_name": "Pat Example", "show_date": (TODAY + timedelta(days=9)).isoformat(),
                "contact_email": "pat@gmail.com", "staff_notes": "Made automatically Nov 10", "welcome_sent_at": None},
               {"id": "a2", "show_name": "Grace Made", "show_date": (TODAY + timedelta(days=9)).isoformat(),
                "contact_email": "g@gmail.com", "staff_notes": None, "welcome_sent_at": None}]
        _, later = plan([], adv, [], TODAY)
        self.assertEqual([a["id"] for a in later], ["a1"])   # never re-sends Grace's own desk rows


class WebsiteOnlyTest(unittest.TestCase):
    """Dojour is being phased out, so a new show may be on the website only
    (Sam, Nov 15 2026). It still gets its advance."""

    def test_website_only_run_gets_an_advance(self):
        hist = website_nights([web("Pat Example", 12), web("Pat Example", 13), web("Pat Example", 13, hour=21)])
        todo, _ = plan(hist, [], [], TODAY)
        self.assertEqual([(a, r["title"], (r["last"] - r["first"]).days) for a, r, _, _ in todo], [("ask", "Pat Example", 1)])

    def test_show_on_both_lists_is_one_run(self):
        hist = [night("Pat Example", 12), night("Pat Example", 13)] + website_nights([web("Pat Example", 12), web("Pat Example", 13)])
        todo, _ = plan(hist, [], [], TODAY)
        self.assertEqual(len(todo), 1)

    def test_free_house_nights_on_the_website_never_count(self):
        hist = website_nights([web("Tuesday Night Laughs", 2, price=0), web("Stand Up Comedy Open Mic", 4, price=0),
                               web("Blingo!", 5, price="0.00"), web("Advice Column!", 6, price=8)])
        todo, _ = plan(hist, [], [], TODAY)
        self.assertEqual(todo, [])

    def test_website_run_with_an_advance_is_left_alone(self):
        hist = website_nights([web("Pat Example", 12), web("Pat Example", 13)])
        adv = [{"show_name": "Pat Example", "show_date": (TODAY + timedelta(days=12)).isoformat()}]
        todo, _ = plan(hist, adv, [], TODAY)
        self.assertEqual(todo, [])

    def test_not_needed_or_fallen_through_on_the_booking_board_is_skipped(self):
        hist = website_nights([web("Pat Example", 12), web("Robin Sample", 14), web("Lee Newcomer", 16)])
        board = [{"act": "Pat Example", "first_night": (TODAY + timedelta(days=12)).isoformat(), "stage": "confirmed", "checks": {"advance": "na"}},
                 {"act": "Robin Sample", "first_night": (TODAY + timedelta(days=14)).isoformat(), "stage": "dropped", "checks": {}},
                 {"act": "Lee Newcomer", "first_night": (TODAY + timedelta(days=16)).isoformat(), "stage": "confirmed", "checks": {"host": "na"}}]
        todo, _ = plan(hist, [], [], TODAY, board=board)
        self.assertEqual([r["title"] for _, r, _, _ in todo], ["Lee Newcomer"])


if __name__ == "__main__":
    unittest.main()
