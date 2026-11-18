"""Tests for booking_inbox.classify(): how emails in the booking@ inbox are
filed on the Booking board. The emails are made up but shaped like the real
ones (agency pitches, CAA contracts through Adobe Sign, Sam's forwards).
Dates are built relative to now so the tests never go stale."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from email.message import EmailMessage

import booking_inbox
from booking_inbox import asked_dates, calls_to_carry, classify, clean_subject, guess_act, new_text, parse_message

NOW = datetime.now(timezone.utc)
KNOWN = ["Pat Example", "Robin Sample: The Loud Tour", "Home For The Holidays"]
GRACE = "booking@sisyphusbrewing.com"
SAM = "sam@sisyphusbrewing.com"


def msg(sender, subject, text="", to=(GRACE,), files=(), hours_ago=1.0):
    name, _, addr = sender.rpartition(" ")
    return {"from_name": name, "from_email": addr.strip("<>"), "to": list(to), "subject": subject,
            "text": text, "files": list(files), "date": NOW - timedelta(hours=hours_ago)}


def thread(*messages):
    return {"key": "gm:1", "link": "https://mail.example/1", "messages": list(messages)}


class ClassifyTest(unittest.TestCase):
    def test_agent_pitch_is_a_request_with_agency_and_dates(self):
        row = classify(thread(msg("Dana Agent <dana.agent@unitedtalent.com>", "Lee Newcomer @ Sisyphus Minneapolis",
                                  "Hey Grace - would you kindly send over your avails for August-Sept? "
                                  "I believe Lee's preference would be for early Sept.")), KNOWN)
        self.assertEqual(row["kind"], "request")
        self.assertEqual(row["agency"], "UTA")
        self.assertEqual(row["act"], "Lee Newcomer")
        self.assertEqual(row["waiting_on"], "us")
        self.assertIn("August-Sept", row["asked"])
        self.assertIn("early Sept", row["asked"])

    def test_self_booked_comic_is_named_after_the_sender(self):
        row = classify(thread(msg("Casey Jokes <caseyjokes@example.com>", "May 14/15 2027",
                                  "Hi, my name is Casey and I am a NYC comedian. I'd love to headline a weekend.")), KNOWN)
        self.assertEqual(row["kind"], "request")
        self.assertEqual(row["act"], "Casey Jokes")
        self.assertIsNone(row["agency"])
        self.assertIn("May 14/15 2027", row["asked"])

    def test_once_we_answer_it_waits_on_them(self):
        row = classify(thread(
            msg("Casey Jokes <caseyjokes@example.com>", "Booking 2027", "Any open weekends in March?", hours_ago=30),
            msg("Sisyphus <booking@sisyphusbrewing.com>", "Re: Booking 2027", "We have March 5-6.",
                to=("caseyjokes@example.com",), hours_ago=2)), KNOWN)
        self.assertEqual(row["waiting_on"], "them")
        self.assertEqual(row["msg_count"], 2)

    def test_sams_forward_counts_as_the_original_sender_and_still_waits_on_us(self):
        body = ("Booking pitch that came to sam@.\n\n---------- Forwarded message ----------\n"
                "From: Jo Rep <jo.rep@independentartistgroup.com>\nDate: Wed, Oct 28, 2026 at 11:27\n"
                "Subject: Morgan Sample Avails\nTo: sam@sisyphusbrewing.com\n\n"
                "Morgan is routing through the Midwest 3/26-27 and would love to play the room.")
        row = classify(thread(msg("Samuel Harriman <sam@sisyphusbrewing.com>", "Fwd: Morgan Sample Avails", body)), KNOWN)
        self.assertEqual(row["kind"], "request")
        self.assertEqual(row["from_email"], "jo.rep@independentartistgroup.com")
        self.assertEqual(row["agency"], "IAG")
        self.assertEqual(row["act"], "Morgan Sample")
        self.assertEqual(row["waiting_on"], "us")
        self.assertIn("3/26-27", row["asked"])
        self.assertNotIn("Oct 28", row["asked"] or "")        # the forward's own date is not an ask

    def test_contract_waiting_for_signature(self):
        row = classify(thread(msg(
            "Creative Artists Agency Touring via Adobe Acrobat Sign <echosign@echosign.com>",
            'Signature requested on "Pat Example May 14, 2027 - May 15, 2027 Sisyphus Comedy Club - Minneapolis, MN (Booking No. 1119891)"',
            "")), KNOWN)      # even with no readable body, the subject says enough
        self.assertEqual(row["kind"], "contract")
        self.assertEqual(row["act"], "Pat Example")
        self.assertEqual(row["docs"][0]["doc"], "contract")
        self.assertEqual(row["docs"][0]["state"], "to_sign")
        self.assertEqual(row["waiting_on"], "us")

    def test_signed_contract_is_done_and_names_an_unknown_act(self):
        row = classify(thread(
            msg("Agency Touring via Adobe Acrobat Sign <echosign@echosign.com>",
                'Signature requested on "Jamie Brandnew Sept 3, 2027 - Sept 4, 2027 Sisyphus Comedy Club"', "Please sign.", hours_ago=50),
            msg("Agency Touring via Adobe Acrobat Sign <echosign@echosign.com>",
                'Completed: "Jamie Brandnew Sept 3, 2027 - Sept 4, 2027 Sisyphus Comedy Club"',
                "Attached is the final agreement.", files=["Jamie Brandnew - signed.pdf"], hours_ago=3)), KNOWN)
        self.assertEqual(row["kind"], "contract")
        self.assertEqual(row["docs"][0]["state"], "signed")
        self.assertEqual(row["act"], "Jamie Brandnew")
        self.assertEqual(row["waiting_on"], "them")

    def test_w9_and_contract_attachments_are_noticed(self):
        row = classify(thread(msg("Robin Sample <robin@example.com>", "Paperwork for March",
                                  "Here you go!", files=["Robin Sample W-9 2026.pdf", "Sisyphus_contract_countersigned.pdf"])), KNOWN)
        kinds = {d["doc"]: d["state"] for d in row["docs"]}
        self.assertEqual(kinds, {"contract": "signed", "w9": "received"})
        self.assertEqual(row["act"], "Robin Sample: The Loud Tour")     # matched to the booked show by name

    def test_ticket_count_ask_for_a_booked_show(self):
        row = classify(thread(msg("Sky Helper <assistant@unitedtalent.com>",
                                  "Ticket Count Request: Pat Example / Mar 26-27, 2027 / Sisyphus Brewing", "Counts please!")), KNOWN)
        self.assertEqual(row["kind"], "counts")
        self.assertEqual(row["act"], "Pat Example")

    def test_mail_about_a_booked_show_is_filed_under_it(self):
        row = classify(thread(msg("Tour Manager <tm@ent360.com>", "ADVANCE: Pat Example / Nov. 12 / Sisyphus",
                                  "Bumping the below. What time is load in?")), KNOWN)
        self.assertEqual(row["kind"], "show")
        self.assertEqual(row["act"], "Pat Example")

    def test_private_event_ask(self):
        row = classify(thread(msg("Chris Planner <chris@acme.com>", "Holiday party in December?",
                                  "We'd like to rent the taproom for a corporate event on Dec 12 for 40 people.")), KNOWN)
        self.assertEqual(row["kind"], "event")
        self.assertIn("Dec 12", row["asked"])

    def test_subject_decides_who_it_is_about(self):
        # A pitch for someone new that also name-drops a comic we have booked.
        row = classify(thread(msg("Jordan Rep <jordan.rep@brillstein.com>", "Lou Example - Sisyphus Brewing",
                                  "Hey Grace! Excited for my guy Pat Example to do sold out shows next weekend! "
                                  "I've also been working with Lou Example for some time.")), KNOWN)
        self.assertEqual(row["kind"], "request")
        self.assertEqual(row["act"], "Lou Example")
        self.assertEqual(row["agency"], "Brillstein")

    def test_a_bump_on_a_named_subject_is_still_a_request(self):
        row = classify(thread(msg("Blake Example <blake@example.com>", "Re: Blake Example Sisyphus 2027",
                                  "Hi Grace! Wanted to give this a little bump. Hope you're doing great.")), KNOWN)
        self.assertEqual(row["kind"], "request")
        self.assertEqual(row["act"], "Blake Example")

    def test_a_thank_you_after_our_answer_needs_nothing(self):
        row = classify(thread(
            msg("Sky Helper <assistant@unitedtalent.com>", "Ticket Count Request: Pat Example / Mar 26-27, 2027", "Counts please!", hours_ago=40),
            msg("Samuel Harriman <sam@sisyphusbrewing.com>", "Re: Ticket Count Request: Pat Example", "Friday: 5 sold.",
                to=("assistant@unitedtalent.com",), hours_ago=20),
            msg("Sky Helper <assistant@unitedtalent.com>", "Re: Ticket Count Request: Pat Example", "Thank you so much, Sam! I appreciate it.",
                to=(SAM,), hours_ago=2)), KNOWN)
        self.assertEqual(row["kind"], "counts")
        self.assertEqual(row["waiting_on"], "them")

    def test_a_thank_you_that_asks_something_still_needs_an_answer(self):
        agent = "Dana Agent <dana.agent@unitedtalent.com>"
        row = classify(thread(
            msg(agent, "Lee Newcomer Avails", "Any avails in May?", hours_ago=30),
            msg("Grace <%s>" % GRACE, "Re: Lee Newcomer Avails", "May 14-15 is open.", to=("dana.agent@unitedtalent.com",), hours_ago=20),
            msg(agent, "Re: Lee Newcomer Avails", "Great, what would the deal be?", hours_ago=2)), KNOWN)
        self.assertEqual(row["waiting_on"], "us")

    def test_noise_is_dropped(self):
        self.assertIsNone(classify(thread(msg("Shopify <no-reply@shopify.com>", "[Sisyphus] Order #1234 placed", "avails")), KNOWN))
        self.assertIsNone(classify(thread(msg("Sisyphus Box Office <ticketing@sisyphusbrewing.com>",
                                              "Supplies running low", "Napkins")), KNOWN))
        self.assertIsNone(classify(thread(msg("A Customer <customer@example.com>", "Lost my hat", "Did anyone find a hat?")), KNOWN))
        # Grace and Sam talking to each other is not a request either.
        self.assertIsNone(classify(thread(msg("Samuel Harriman <sam@sisyphusbrewing.com>", "Kombucha order", "Delivering Thursday.")), KNOWN))

    def test_only_what_is_sent_is_saved_so_a_managers_status_survives(self):
        row = classify(thread(msg("Casey Jokes <caseyjokes@example.com>", "Booking 2027", "Any avails?")), KNOWN)
        self.assertNotIn("status", row)
        self.assertNotIn("note", row)


class HelpersTest(unittest.TestCase):
    def test_clean_subject(self):
        self.assertEqual(clean_subject("Re: FWD: RE:  Pat Example   Avails"), "Pat Example Avails")

    def test_new_text_drops_the_quoted_reply(self):
        text = "Sounds great.\n\nOn Wed, Oct 28, 2026 at 7:57 PM Casey <c@x.com> wrote:\n> March 5 works\n"
        self.assertEqual(new_text(text), "Sounds great.")

    def test_dates_as_written(self):
        self.assertEqual(asked_dates("one-nighter 2/25 or 3/25, or the weekend of 3/26-27, 2027"), "2/25, 3/25, 3/26-27")
        self.assertEqual(asked_dates("I may be around. We could march over."), "")
        self.assertEqual(asked_dates("Sunday May 16 for both"), "May 16")

    def test_guess_act_from_subject(self):
        self.assertEqual(guess_act("Fwd: Ariel Example Avails", "Jo Rep", "jo@independentartistgroup.com"), "Ariel Example")
        self.assertEqual(guess_act("Lou Example - Sisyphus Brewing", "Jordan Rep", "jordan.rep@brillstein.com"), "Lou Example")
        self.assertEqual(guess_act("Re: Blake Example Sisyphus 2027", "Blake Example", "blake@example.com"), "Blake Example")
        self.assertIsNone(guess_act("UTA Comedy Ideas", "Sky Rep", "sky.rep@unitedtalent.com"))

    def test_parse_message_reads_sender_body_and_attachment_names(self):
        m = EmailMessage()
        m["From"] = "Robin Sample <Robin@Example.com>"
        m["To"] = "booking@sisyphusbrewing.com"
        m["Cc"] = "Sam <sam@sisyphusbrewing.com>"
        m["Subject"] = "Paperwork"
        m["Date"] = "Mon, 09 Nov 2026 18:55:00 -0600"
        m.set_content("Attached.")
        m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="Robin W9.pdf")
        parsed = parse_message(m.as_bytes())
        self.assertEqual(parsed["from_email"], "robin@example.com")
        self.assertEqual(parsed["to"], ["booking@sisyphusbrewing.com", "sam@sisyphusbrewing.com"])
        self.assertEqual(parsed["files"], ["Robin W9.pdf"])
        self.assertIn("Attached.", parsed["text"])
        self.assertEqual(parsed["date"].utcoffset(), timedelta(hours=-6))


class CarryOverTest(unittest.TestCase):
    """Calls made on the preview rows follow the conversation into the real inbox."""

    def test_a_call_on_a_preview_row_moves_to_the_same_conversation(self):
        preview = [{"key": "sam:lee-newcomer", "subject": "Lee Newcomer Avails", "status": "later", "status_by": "manager"},
                   {"key": "sam:casey", "subject": "May 14/15 2027", "status": None},
                   {"key": "sam:other", "subject": "Somebody Else 2027", "status": "pass"}]
        rows = [{"key": "gm:aaa", "subject": "RE: Lee Newcomer Avails"}, {"key": "gm:bbb", "subject": "May 14/15 2027"},
                {"key": "gm:ccc", "subject": "A brand new pitch"}]
        pairs = calls_to_carry(rows, preview)
        self.assertEqual([(key, old["key"], old["status"]) for key, old in pairs], [("gm:aaa", "sam:lee-newcomer", "later")])

    def test_nothing_to_carry_when_no_calls_were_made(self):
        self.assertEqual(calls_to_carry([{"key": "gm:aaa", "subject": "Lee Newcomer Avails"}],
                                        [{"key": "sam:lee", "subject": "Lee Newcomer Avails", "status": None}]), [])


def made_up_email(sender, to, subject, text, hours, filename=None, pad=0):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, to, subject
    m["Date"] = (NOW - timedelta(hours=hours)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    m.set_content(text)
    if filename:
        m.add_attachment(b"%PDF" + b"0" * pad, maintype="application", subtype="pdf", filename=filename)
    return m.as_bytes()


class FakeGmail:
    """Answers the way Gmail's IMAP does, for two conversations of made-up
    mail. Tests change the class attributes to try Gmail's other habits."""
    selected = None
    grouped_search = True      # False: refuses "this conversation OR that one"
    uid_after_text = False     # True: names the email after its text, not before
    mail = None                # {uid: (conversation id, raw email)}; None = the two below
    asked = []                 # every question put to it, for counting

    def __init__(self, host):
        agent = "Dana Agent <dana.agent@unitedtalent.com>"
        self.mail = type(self).mail or {
            11: ("1700000000000000001", made_up_email(agent, GRACE, "Lee Newcomer Avails", "Any avails in May?", 5)),
            12: ("1700000000000000001", made_up_email("Grace <%s>" % GRACE, agent, "Re: Lee Newcomer Avails", "May 14-15 is open.", 3)),
            13: ("1700000000000000002", made_up_email("Robin Sample <robin@example.com>", GRACE, "W-9", "Attached.", 2, "Robin Sample W9.pdf")),
        }
        type(self).asked = []

    def login(self, user, password):
        return "OK", [b"done"]

    def select(self, name, readonly=False):
        FakeGmail.selected = (name, readonly)
        return "OK", [b"3"]

    @staticmethod
    def numbers(text):
        return [int(n) for n in (text.decode() if isinstance(text, bytes) else text).split(",")]

    def uid(self, command, *args):
        type(self).asked.append((command,) + args[1:])
        if command == "SEARCH" and args[1] == "SINCE":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mail))]
        if command == "SEARCH" and args[1] == "X-GM-THRID":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mail) if self.mail[u][0] == args[2])]
        if command == "SEARCH" and args[1].startswith("OR "):
            if not self.grouped_search:
                raise booking_inbox.imaplib.IMAP4.error("UID command error: BAD could not parse command")
            ids = set(args[1].replace("OR ", "").replace("X-GM-THRID ", "").split())
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.mail) if self.mail[u][0] in ids)]
        if command == "FETCH" and args[1] == "(X-GM-THRID)":
            return "OK", [b"%d (X-GM-THRID %s UID %d)" % (u, self.mail[u][0].encode(), u) for u in self.numbers(args[0])]
        if command == "FETCH" and args[1] == "(RFC822.SIZE)":
            return "OK", [b"%d (UID %d RFC822.SIZE %d)" % (u, u, len(self.mail[u][1])) for u in self.numbers(args[0])]
        if command == "FETCH" and args[1] == "(BODY.PEEK[])":
            answer = []
            for u in self.numbers(args[0]):
                raw = self.mail[u][1]
                if self.uid_after_text:
                    answer += [(b"%d (BODY[] {%d}" % (u, len(raw)), raw), b" UID %d)" % u]
                else:
                    answer += [(b"%d (UID %d BODY[] {%d}" % (u, u, len(raw)), raw), b")"]
            return "OK", answer
        if command == "FETCH" and args[1] == "(BODY.PEEK[HEADER] BODYSTRUCTURE)":
            u = self.numbers(args[0])[0]
            head = self.mail[u][1].split(b"\n\n")[0] + b"\n\n"
            return "OK", [(b"%d (UID %d BODY[HEADER] {%d}" % (u, u, len(head)), head),
                          b' BODYSTRUCTURE (("application" "pdf" ("name" "Big Contract.pdf") NIL NIL "base64" 5000000)))']
        raise AssertionError("unexpected IMAP call: %s %r" % (command, args))

    def logout(self):
        return "BYE", [b""]


class ReadMailboxTest(unittest.TestCase):
    def setUp(self):
        FakeGmail.grouped_search, FakeGmail.uid_after_text, FakeGmail.mail = True, False, None

    def read(self, days=3):
        with mock.patch.object(booking_inbox.imaplib, "IMAP4_SSL", FakeGmail):
            return booking_inbox.read_mailbox(days)

    def check_the_two_conversations(self, threads):
        self.assertEqual([t["key"] for t in threads], ["gm:1700000000000000001", "gm:1700000000000000002"])
        self.assertEqual([m["subject"] for m in threads[0]["messages"]], ["Lee Newcomer Avails", "Re: Lee Newcomer Avails"])
        self.assertTrue(threads[0]["link"].startswith("https://mail.google.com/"))
        rows = [classify(t, KNOWN) for t in threads]
        self.assertEqual((rows[0]["kind"], rows[0]["waiting_on"], rows[0]["act"]), ("request", "them", "Lee Newcomer"))
        self.assertEqual([d["doc"] for d in rows[1]["docs"]], ["w9"])

    def test_reads_whole_conversations_without_marking_anything_read(self):
        threads = self.read()
        self.assertEqual(FakeGmail.selected, ('"[Gmail]/All Mail"', True))          # read-only
        self.check_the_two_conversations(threads)
        # Nothing but looking: searches, and downloads that leave mail unread.
        for command, *rest in FakeGmail.asked:
            self.assertIn(command, ("SEARCH", "FETCH"))
            self.assertNotIn("BODY[", " ".join(str(r) for r in rest).replace("BODY.PEEK[", ""))

    def test_when_gmail_refuses_the_grouped_question_it_asks_one_by_one(self):
        FakeGmail.grouped_search = False
        self.check_the_two_conversations(self.read())

    def test_when_gmail_names_the_email_after_its_text(self):
        FakeGmail.uid_after_text = True
        self.check_the_two_conversations(self.read())

    def test_another_mailbox_gets_its_own_link(self):
        with mock.patch.object(booking_inbox.imaplib, "IMAP4_SSL", FakeGmail):
            threads = booking_inbox.read_mailbox(3, "events@sisyphusbrewing.com", "made-up-password")
        self.assertIn("authuser=events@sisyphusbrewing.com", threads[0]["link"])

    def test_a_big_catch_up_is_a_few_questions_not_thousands(self):
        """The first 60-day read of booking@ asked Gmail about every email one
        at a time and ran out the clock (Nov 17 2026). 300 conversations of
        two emails each should now take well under a hundred questions."""
        FakeGmail.mail = {}
        for n in range(300):
            for part in (0, 1):
                FakeGmail.mail[1000 + n * 2 + part] = (
                    str(1800000000000000000 + n),
                    made_up_email("Pat Writer <pat%d@example.com>" % n, GRACE, "Question %d" % n, "Hello %d" % part, 5 - part))
        threads = self.read(60)
        self.assertEqual(len(threads), 300)
        self.assertTrue(all(len(t["messages"]) == 2 for t in threads))
        self.assertEqual(threads[7]["messages"][1]["text"].strip(), "Hello 1")
        self.assertLess(len(FakeGmail.asked), 100)

    def test_a_very_large_email_is_read_by_its_headers_only(self):
        big = made_up_email("Robin Sample <robin@example.com>", GRACE, "Signed contract", "Attached.", 2,
                            "Big Contract.pdf", pad=booking_inbox.BIG_EMAIL)
        FakeGmail.mail = {21: ("1900000000000000001", big)}
        threads = self.read()
        self.assertEqual(threads[0]["messages"][0]["subject"], "Signed contract")
        self.assertEqual(threads[0]["messages"][0]["files"], ["Big Contract.pdf"])
        self.assertNotIn("(BODY.PEEK[])", [q[-1] for q in FakeGmail.asked])       # never downloaded whole


if __name__ == "__main__":
    unittest.main()
