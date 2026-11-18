"""Tests for events_inbox.classify(): how emails in the events@ inbox are
sorted (private events, ticket problems, accessibility, donations, comics who
wrote to the wrong inbox, sales pitches). Every name and email here is made
up. Dates are built relative to now so the tests never go stale."""
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

import events_inbox
from events_inbox import classify, people_count

NOW = datetime.now(timezone.utc)
EVENTS = "events@sisyphusbrewing.com"


def msg(sender, subject, text="", to=(EVENTS,), hours_ago=1.0, bulk=False):
    name, _, addr = sender.rpartition(" ")
    return {"from_name": name, "from_email": addr.strip("<>"), "to": list(to), "subject": subject,
            "text": text, "files": [], "bulk": bulk, "date": NOW - timedelta(hours=hours_ago)}


def thread(*messages):
    return {"key": "gm:1", "link": "https://mail.example/1", "messages": list(messages)}


class ClassifyTest(unittest.TestCase):
    def test_private_event_ask_with_date_and_headcount(self):
        row = classify(thread(msg("Chris Planner <chris@acme.example>", "Holiday party?",
                                  "We'd like to rent the taproom for a work party on Dec 12 for about 40 people.")))
        self.assertEqual((row["kind"], row["waiting_on"]), ("private", "us"))
        self.assertIn("Dec 12", row["asked"])
        self.assertEqual(row["people"], "40")
        self.assertEqual(row["from_email"], "chris@acme.example")

    def test_a_group_coming_to_a_show_is_a_private_ask(self):
        row = classify(thread(msg("Jo Organizer <jo@example.com>", "Group tickets",
                                  "Could we reserve tables for a group of 18 at the Friday show?")))
        self.assertEqual((row["kind"], row["people"]), ("private", "18"))

    def test_ticket_problem(self):
        row = classify(thread(msg("Sam Buyer <buyer@example.com>", "Wrong night",
                                  "I bought two tickets for Saturday but meant Friday. Can I exchange them? Order #1234.")))
        self.assertEqual(row["kind"], "tickets")
        self.assertIsNone(row["people"])

    def test_accessibility_question_wins_over_tickets(self):
        row = classify(thread(msg("Alex Guest <alex@example.com>", "Tickets for Friday",
                                  "I use a wheelchair. Is the comedy room accessible, and where should we sit?")))
        self.assertEqual(row["kind"], "access")

    def test_donation_request(self):
        row = classify(thread(msg("Robin Volunteer <robin@school.example>", "Silent auction",
                                  "Our PTA is holding a silent auction in March. Would you donate a gift card?")))
        self.assertEqual(row["kind"], "donation")

    def test_a_fundraiser_that_wants_the_room_is_a_private_ask(self):
        row = classify(thread(msg("Robin Volunteer <robin@school.example>", "Fundraiser night",
                                  "We're a nonprofit and would love to host a fundraiser in your space, around 60 guests.")))
        self.assertEqual((row["kind"], row["people"]), ("private", "60"))

    def test_a_comic_or_an_agent_belongs_in_booking(self):
        comic = classify(thread(msg("Lee Newcomer <lee@example.com>", "Stage time",
                                    "I'm a comedian based in Chicago and would love a guest spot.")))
        agent = classify(thread(msg("Dana Agent <dana.agent@unitedtalent.com>", "Avails", "Any weekends open in May?")))
        self.assertEqual((comic["kind"], agent["kind"]), ("comic", "comic"))

    def test_sales_pitch(self):
        row = classify(thread(msg("Pat Seller <pat@growth.example>", "Quick question",
                                  "We help breweries get more Google reviews. Can we hop on a quick call this week?")))
        self.assertEqual(row["kind"], "pitch")

    def test_anything_else_a_person_wrote_is_still_listed(self):
        row = classify(thread(msg("Jamie Neighbor <jamie@example.com>", "Lost scarf",
                                  "I think I left a green scarf at the bar on Saturday.")))
        self.assertEqual((row["kind"], row["waiting_on"]), ("other", "us"))

    def test_newsletters_receipts_and_our_own_mail_are_dropped(self):
        self.assertIsNone(classify(thread(msg("Deals <news@shop.example>", "50% off kegs", "Sale!", bulk=True))))
        self.assertIsNone(classify(thread(msg("Shopify <no-reply@shopify.com>", "Your payout", "..."))))
        self.assertIsNone(classify(thread(msg("Sisyphus <ticketing@sisyphusbrewing.com>", "Door list for tonight", "..."))))

    def test_once_we_answer_it_waits_on_them(self):
        guest = "Chris Planner <chris@acme.example>"
        row = classify(thread(
            msg(guest, "Birthday party", "Can we book the back room on March 3 for 20 people?", hours_ago=30),
            msg("Sisyphus <%s>" % EVENTS, "Re: Birthday party", "Yes! Here's how it works.", to=("chris@acme.example",), hours_ago=20)))
        self.assertEqual((row["kind"], row["waiting_on"], row["msg_count"]), ("private", "them", 2))

    def test_their_reply_puts_it_back_on_us(self):
        guest = "Chris Planner <chris@acme.example>"
        row = classify(thread(
            msg(guest, "Birthday party", "Can we book the back room on March 3 for 20 people?", hours_ago=30),
            msg("Sisyphus <%s>" % EVENTS, "Re: Birthday party", "Yes! Here's how it works.", to=("chris@acme.example",), hours_ago=20),
            msg(guest, "Re: Birthday party", "Great, what does it cost?", hours_ago=2)))
        self.assertEqual(row["waiting_on"], "us")
        self.assertIn("what does it cost", row["snippet"])

    def test_a_thank_you_after_our_answer_needs_nothing(self):
        guest = "Sam Buyer <buyer@example.com>"
        row = classify(thread(
            msg(guest, "Refund?", "Can I get a refund on my tickets?", hours_ago=30),
            msg("Sisyphus <%s>" % EVENTS, "Re: Refund?", "Done.", to=("buyer@example.com",), hours_ago=20),
            msg(guest, "Re: Refund?", "Thank you so much!", hours_ago=2)))
        self.assertEqual(row["waiting_on"], "them")

    def test_only_what_is_sent_is_saved_so_a_managers_call_survives(self):
        row = classify(thread(msg("Jamie Neighbor <jamie@example.com>", "Lost scarf", "Green scarf.")))
        for column in ("status", "status_by", "status_at", "note"):
            self.assertNotIn(column, row)


class FirstReadTuningTest(unittest.TestCase):
    """Shapes seen in the first read of events@ (Nov 18 2026), made up again."""

    def test_a_business_we_never_answered_selling_something_is_a_pitch(self):
        for subject, text in (("Photo Booth @ Sisyphus?", "I'm looking for fun spaces that might want a photo booth."),
                              ("ticket fees idea", "Would you let someone run your Meta ads if it cost nothing?"),
                              ("Event partnerships", "Exploring partnership opportunities and private events with you."),
                              ("A review worth mentioning", "This Google review is worth mentioning. We can get it removed.")):
            row = classify(thread(msg("Pat Seller <pat@seller.example>", subject, text)))
            self.assertEqual(row["kind"], "pitch", subject)

    def test_a_person_on_free_mail_is_not_taken_for_a_salesman(self):
        row = classify(thread(msg("Jo Organizer <jo@gmail.com>", "Rental / comedy show",
                                  "I am looking to rent the space for a comedy show with about 50 guests.")))
        self.assertEqual(row["kind"], "private")

    def test_a_parent_raising_money_is_a_donation_not_a_rental(self):
        row = classify(thread(msg("Chris Parent <chris@gmail.com>", "Team sponsorship",
                                  "I'm a parent helping raise funds for my son's hockey team. Would you sponsor us?")))
        self.assertEqual(row["kind"], "donation")

    def test_lease_and_press_are_for_sam_only(self):
        lease = classify(thread(msg("Lee Owner <lee@otherbrewery.example>", "Future Lease",
                                    "I read about your upcoming lease issues and have a possible alternative space.")))
        press = classify(thread(msg("Robin Writer <robin@news.example>", "Media inquiry",
                                    "I'm a reporter and was sorry to see the post about the future of the club.")))
        self.assertEqual((lease["kind"], press["kind"]), ("owner", "press"))
        self.assertTrue(set(events_inbox.OWNER_ONLY) >= {"owner", "press"})

    def test_an_agent_who_mentions_the_lease_is_still_booking_business(self):
        row = classify(thread(msg("Dana Agent <dana.agent@gersh.com>", "Pat Example x Sisyphus",
                                  "Confirmed for May. Sorry to hear about the lease, hope you land a new space!")))
        self.assertEqual(row["kind"], "comic")

    def test_a_resume_is_a_job_ask(self):
        row = classify(thread(msg("Sky Applicant <sky@gmail.com>", "Resume attached", "Here is my resume for the bartender position.")))
        self.assertEqual(row["kind"], "job")

    def test_a_venue_question_with_a_wheelchair_is_access_but_stairs_alone_is_not(self):
        chair = classify(thread(msg("Alex Guest <alex@gmail.com>", "Lost ticket", "I'm in a wheelchair and hoped to sit near the front.")))
        stairs = classify(thread(msg("Alex Guest <alex@gmail.com>", "Fall shows", "Had a great time! Saw you up the stairs. Any nights open?")))
        self.assertEqual(chair["kind"], "access")
        self.assertNotEqual(stairs["kind"], "access")

    def test_many_thanks_after_our_answer_needs_nothing(self):
        guest = "Jo Organizer <jo@gmail.com>"
        row = classify(thread(
            msg(guest, "Materials for the show", "Can you post the link?", hours_ago=30),
            msg("Sisyphus <%s>" % EVENTS, "Re: Materials", "Done.", to=("jo@gmail.com",), hours_ago=20),
            msg(guest, "Re: Materials", "Many thanks, this is so appreciated! See you soon!", hours_ago=2)))
        self.assertEqual(row["waiting_on"], "them")


class PeopleCountTest(unittest.TestCase):
    def test_headcounts_as_written(self):
        self.assertEqual(people_count("a group of about 25"), "25")
        self.assertEqual(people_count("somewhere between 30-40 guests"), "30-40")
        self.assertEqual(people_count("roughly 15 people"), "15")
        self.assertEqual(people_count("see you at 7"), "")


class PublicLogTest(unittest.TestCase):
    """This repo's Actions logs are public: as an action the script may print
    how many, never who or what."""

    def run_main(self, threads, **env):
        saved, out = [], io.StringIO()
        with mock.patch.object(events_inbox, "IMAP_PASS", "made-up-password"), \
             mock.patch.object(events_inbox, "SERVICE_KEY", "made-up-key"), \
             mock.patch.object(events_inbox, "DRY_RUN", env.get("dry", False)), \
             mock.patch.object(events_inbox.mail, "read_mailbox", lambda *a: threads), \
             mock.patch.object(events_inbox, "save", saved.extend), \
             mock.patch.dict(events_inbox.os.environ, {"GITHUB_ACTIONS": "true"}), \
             redirect_stdout(out):
            events_inbox.main()
        return saved, out.getvalue()

    THREADS = [
        thread(msg("Chris Planner <chris@acme.example>", "Holiday party?", "Rent the taproom Dec 12 for 40 people?")),
        thread(msg("Sam Buyer <buyer@example.com>", "Wrong night", "Can I exchange my tickets?")),
        thread(msg("Deals <news@shop.example>", "50% off kegs", "Sale!", bulk=True)),
    ]

    def test_prints_counts_only(self):
        saved, printed = self.run_main(self.THREADS)
        self.assertEqual(sorted(r["kind"] for r in saved), ["private", "tickets"])
        self.assertIn("Read 3 conversations", printed)
        self.assertIn("kept 2: 1 private, 1 tickets", printed)
        for private in ("Chris", "Planner", "acme", "Buyer", "example.com", "Holiday", "Wrong night", "taproom"):
            self.assertNotIn(private, printed)

    def test_a_dry_run_saves_nothing_and_still_prints_counts_only(self):
        saved, printed = self.run_main(self.THREADS, dry=True)
        self.assertEqual(saved, [])
        self.assertIn("kept 2", printed)
        self.assertNotIn("Chris", printed)

    def test_without_the_password_it_stops_quietly(self):
        out = io.StringIO()
        with mock.patch.object(events_inbox, "IMAP_PASS", ""), redirect_stdout(out):
            events_inbox.main()                      # no error, nothing read
        self.assertIn("EVENTS_IMAP_PASS is not set yet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
