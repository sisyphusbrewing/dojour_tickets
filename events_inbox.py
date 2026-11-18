"""
Sisyphus - reads the events@ inbox and sorts what lands there.

events@sisyphusbrewing.com is where the public writes: people who want to
rent the room or bring a big group, customers with a ticket problem,
accessibility questions, donation requests, and a steady drip of sales
pitches. Nobody owns that inbox (Sam, Nov 16 2026: "which isn't really anyone
right now because I hate doing it"), so things sit. After the booking@ inbox
was connected to the Booking board he asked for the same here (Sam, Nov 17
2026: "We should probably do this for the events@ email as well").

Every hour the "Events inbox" action runs this and, for each conversation
from the last few days:

  1. Throws out the noise: receipts, newsletters, our own automatic emails.
  2. Decides what it is (owner and press are shown to the owner login only):
       private    someone wants to rent the room, hold a party or bring a group
       tickets    a customer with a ticket problem (refund, wrong night, lost email)
       access     an accessibility question
       donation   a request for a donation or a gift card for a fundraiser
       comic      a comic or an agent who wrote to the wrong inbox (it belongs
                  in booking@)
       job        a resume or a job ask
       pitch      someone selling us something (a business we never wrote
                  back to, writing like a salesman, counts as one)
       owner      the lease, a new building: Sam's own business
       press      a reporter
       other      a person wrote and it is none of the above. It is still
                  listed: nothing a person wrote is ever dropped.
  3. Notes the dates and the number of people they mentioned, and whose turn
     it is to write back.
  4. Saves one row per conversation in Supabase (events_threads).

It only ever READS the mailbox: nothing is marked read, moved, labeled or
answered, and no email is sent. What is saved is the subject, who wrote and
the first couple of lines; never whole emails or attachments.

Needs the secret EVENTS_IMAP_PASS: an "app password" for the events@ Google
account (myaccount.google.com/apppasswords). Until that exists the script
says so and stops without an error.

    python events_inbox.py             the last 3 days
    DAYS=60 python events_inbox.py     catch up on the last 60 days
    DRY_RUN=1 python events_inbox.py   print what it would save, save nothing

This repo and its Actions logs are public, so as an action it prints counts
only: never names, addresses or subject lines.
"""
import json
import os
import re
import sys

import requests

import booking_inbox as mail   # the read-only mailbox reader and its small helpers

SUPABASE_URL = mail.SUPABASE_URL
SERVICE_KEY = mail.SERVICE_KEY
IMAP_USER = (os.environ.get("EVENTS_IMAP_USER") or "events@sisyphusbrewing.com").strip()
IMAP_PASS = (os.environ.get("EVENTS_IMAP_PASS") or "").replace(" ", "").strip()
DAYS = int(os.environ.get("DAYS") or 3)
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

# What each kind of email sounds like. Checked in the order used in classify().
ACCESS_WORDS = re.compile(
    r"wheel ?chair|accessib|\bADA\b|mobility|walker|scooter|hearing (aid|loop|impair)|hard of hearing|\bdeaf\b|"
    r"interpreter|\bASL\b|service (dog|animal)|elevator|wheelchair ramp|disab", re.I)
PRIVATE_WORDS = re.compile(
    r"private (event|party|show|room|space)|rent(ing|al)?\b.{0,30}(space|room|venue|taproom|brewery)|"
    r"(reserve|reserving|reservation|book(ing)?)\b.{0,40}(space|room|area|tables?|taproom|venue|party|group|event)|"
    r"buy ?out|birthday|bachelor|corporate (event|outing|party)|holiday party|work (party|event|outing)|"
    r"company (party|event|outing)|team (outing|building|event)|happy hour|rehearsal dinner|wedding|reception|"
    r"baby shower|bridal shower|graduation|retirement|reunion|celebration of life|memorial|"
    r"(host|hosting|have|hold|holding|plan(ning)?)\b.{0,25}(event|party|gathering|meet ?up|fundraiser|get[- ]together)|"
    r"(large|big) (group|party)|group of \d+|party of \d+|\d+\s*(-|to)?\s*\d*\s*(people|guests|ppl|folks|attendees|employees|coworkers)", re.I)
DONATION_WORDS = re.compile(
    r"donat|silent auction|raffle|in-kind|sponsor(ship)?\b|non-?profit|501\s*\(?c\)?|gift (card|certificate|basket)s? (for|to) (our|the|a)|"
    r"charit(y|able)|benefit (for|event)", re.I)
TICKET_WORDS = re.compile(
    r"\btickets?\b|refund|exchange|\bswap|transfer|resched|can'?t make|cannot make|unable to (make|attend)|"
    r"order (number|#|confirmation|no\b)|confirmation (email|number)|will call|wrong (date|night|show|time)|"
    r"\bseats?\b|seating|sold out|wait ?list|gift card|charged|double[- ]charged", re.I)
COMIC_WORDS = re.compile(
    r"avails?\b|headlin|feature (spot|act)|guest spot|stage time|my (comedy|stand[- ]?up|act|set)|i'?m a (comic|comedian)|"
    r"comedian (based|from|out of)|routing|tour dates|booking (inquiry|request)|booker|perform at", re.I)
PITCH_WORDS = re.compile(
    r"we (help|work with|specialize)|our (platform|software|services?|agency|company|team|solution)\b|free (trial|demo|quote|audit|sample)|"
    r"(schedule|book|hop on|jump on) a (quick )?(call|demo|chat)|quick (call|chat|question about your)|15 minutes|"
    r"\bSEO\b|web ?site (design|redesign|traffic)|google (ranking|reviews|listing)|\bleads?\b|merchant (services|account)|"
    r"credit card processing|payroll|point of sale|\bPOS\b|insurance|financing|loan|wholesale|distribut|"
    r"partnership opportunit|collab(oration)? opportunit|influencer|unsubscribe|opt[- ]out", re.I)
PEOPLE = re.compile(
    r"(?:group|party) of (?:about |around |roughly |approximately |~)?(\d{1,3})\b|"
    r"\b(\d{1,3})\s*(?:[-–]|to)\s*(\d{1,3})\s*(?:people|guests|ppl|folks|attendees|employees|coworkers|friends)|"
    r"\b(?:about |around |roughly |approximately |~)?(\d{1,3})\+?\s*(?:people|guests|ppl|folks|attendees|employees|coworkers|friends)\b", re.I)

# Sam's own business: the lease, a new building, reporters. Kept off the
# managers' list (the database hides these two kinds from everyone but the
# owner login).
OWNER_WORDS = re.compile(
    r"\blease\b|landlord|real estate|(new|alternative|possible) (brewery |taproom )?(space|location|building|home)|"
    r"\bmov(e|ing) (out|locations?)\b|buy(ing)? a building", re.I)
PRESS_WORDS = re.compile(r"reporter|journalist|media (inquiry|request)|\bpress\b|for (a|an|our) (story|article)|newsroom|on the record", re.I)
JOB_WORDS = re.compile(r"\bresume\b|résumé|\bcv\b|cover letter|job (posting|opening|application)|appl(y|ying|ication) for|hiring|position", re.I)
# Cold sales mail that the pitch words alone missed (Nov 18 2026, first read
# of events@: ad agencies, review-removal offers, photo booths, holiday lights,
# floor coatings, listing sites, "partnerships").
COLD_WORDS = re.compile(
    r"partner(ship)?s?\b|agency|\bads\b|meta ads|line of credit|graphics|photo ?booth|holiday lights|coatings?\b|"
    r"manufactur|raw material|\breviews?\b|commission|free (service|promo|listing)|on the (twin cities )?map|registration|"
    r"\bpromote\b|our readers|craft beer space|beverage space|worth mentioning|just following up|circling back|"
    r"last one from me|make sure this didn'?t get buried|grow(th)?\b|revenue|leads?\b", re.I)
FREE_MAIL = re.compile(r"@(gmail|yahoo|hotmail|outlook|icloud|aol|msn|comcast|live|me|proton(mail)?|mac)\.", re.I)

KINDS = ("private", "tickets", "access", "donation", "comic", "job", "pitch", "other", "owner", "press")
OWNER_ONLY = ("owner", "press")


def people_count(text):
    """The number of people they mentioned ("group of 25", "30-40 guests"), as text."""
    m = PEOPLE.search(text or "")
    if not m:
        return ""
    a, lo, hi, b = m.groups()
    return f"{lo}-{hi}" if lo and hi else (a or b or "")


def classify(thread):
    """thread = {"key", "link", "messages": [...]} as read by the mailbox
    reader. Returns the events_threads row, or None for noise."""
    messages = [m for m in thread.get("messages") or [] if m.get("date")]
    if not messages:
        return None
    messages.sort(key=lambda m: m["date"])
    subject = mail.clean_subject(messages[0].get("subject") or messages[-1].get("subject"))

    # Who outside Sisyphus is in this conversation? A forward from one of our
    # own addresses counts as its original sender.
    people, bulk = [], 0
    for m in messages:
        addr = (m.get("from_email") or "").lower()
        if mail.is_ours(addr):
            fwd = mail.forwarded_from(m.get("text"))
            if fwd and not mail.is_ours(fwd[1]):
                people.append({"name": fwd[0], "email": fwd[1], "text": mail.forwarded_text(m.get("text")), "date": m["date"]})
            continue
        if mail.NOISE.search(addr) or mail.SIGNERS.search(addr):
            continue
        if m.get("bulk"):
            bulk += 1                         # a newsletter or a mass mailing
            continue
        people.append({"name": m.get("from_name") or addr, "email": addr, "text": mail.new_text(m.get("text")), "date": m["date"]})
    if not people:
        return None                           # all ours, all automatic, or a mailing list
    if mail.OUR_AUTOMATIC.search(subject):
        return None

    who = people[-1]
    first_words = subject + " . " + " ".join(p["text"] for p in people)[:2500]
    answered = any(mail.is_ours(m.get("from_email")) and any(not mail.is_ours(a) for a in m.get("to") or []) for m in messages)
    # A business we never wrote back to, writing like a salesman.
    cold = not answered and not FREE_MAIL.search(who["email"]) and not mail.agency_of(who["email"])
    if mail.agency_of(who["email"]):
        kind = "comic"                    # an agent is booking business, even when the lease comes up
    elif OWNER_WORDS.search(first_words):
        kind = "owner"
    elif PRESS_WORDS.search(first_words):
        kind = "press"
    elif cold and (COLD_WORDS.search(first_words) or PITCH_WORDS.search(first_words)) and not DONATION_WORDS.search(first_words):
        kind = "pitch"
    elif ACCESS_WORDS.search(first_words):
        kind = "access"
    elif JOB_WORDS.search(subject) or (JOB_WORDS.search(first_words) and not PRIVATE_WORDS.search(first_words)):
        kind = "job"
    elif COMIC_WORDS.search(first_words):
        kind = "comic"
    elif DONATION_WORDS.search(first_words) and not re.search(r"\brent(al|ing)?\b|reserve|host(ing)? (a|an|our)", first_words, re.I):
        kind = "donation"
    elif PRIVATE_WORDS.search(first_words):
        kind = "private"
    elif TICKET_WORDS.search(first_words):
        kind = "tickets"
    elif PITCH_WORDS.search(first_words):
        kind = "pitch"
    else:
        kind = "other"

    # Whose turn is it? Ours unless the last word was ours, to someone outside.
    last = messages[-1]
    wrote_out = any(not mail.is_ours(a) for a in last.get("to") or [])
    waiting = "them" if (mail.is_ours(last.get("from_email")) and wrote_out) else "us"
    latest = max(people, key=lambda p: p["date"])
    if answered and mail.just_thanks(latest["text"]):
        waiting = "them"                      # "Thank you so much!" needs no answer

    asking = subject + " . " + latest["text"][:1500]
    return {
        "key": thread["key"],
        "kind": kind,
        "subject": subject[:200],
        "from_name": (who["name"] or "")[:120],
        "from_email": who["email"][:200],
        "asked": (mail.asked_dates(asking) if kind in ("private", "tickets", "donation") else "")[:200] or None,
        "people": (people_count(first_words) if kind == "private" else "") or None,
        "snippet": latest["text"][:260] or None,
        "link": thread.get("link"),
        "first_at": messages[0]["date"].isoformat(),
        "last_at": last["date"].isoformat(),
        "last_from": (last.get("from_name") or last.get("from_email") or "")[:120],
        "msg_count": len(messages),
        "waiting_on": waiting,
    }


def save(rows):
    """Add or refresh the rows. Only the columns we send are touched, so a
    call someone made on a conversation (done / later) is never overwritten."""
    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), 100):
        r = requests.post(f"{SUPABASE_URL}/rest/v1/events_threads", params={"on_conflict": "key"},
                          headers=headers, data=json.dumps(rows[i:i + 100]), timeout=60)
        r.raise_for_status()


def main():
    if not IMAP_PASS:
        print("EVENTS_IMAP_PASS is not set yet, so there is no way into the events@ inbox. Nothing to do.")
        return
    if not SERVICE_KEY and not DRY_RUN:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY is required")
    threads = mail.read_mailbox(DAYS, IMAP_USER, IMAP_PASS)
    rows, unreadable = [], 0
    for t in threads:
        try:
            row = classify(t)
        except Exception:
            unreadable += 1                              # counted, not shown: the log is public
            continue
        if row:
            rows.append(row)
    counts = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(f"Read {len(threads)} conversations from the last {DAYS} days; kept {len(rows)}: "
          + (", ".join(f"{counts[k]} {k}" for k in KINDS if counts.get(k)) or "none")
          + (f". {unreadable} could not be read." if unreadable else ""))
    if DRY_RUN:
        # Public logs: the per-email detail only prints when run by hand on a computer.
        for row in ([] if os.environ.get("GITHUB_ACTIONS") else rows):
            print(f"  [{row['kind']}] {row['from_name']} | {row['subject']} | waiting on {row['waiting_on']}"
                  + (f" | asked: {row['asked']}" if row["asked"] else "") + (f" | people: {row['people']}" if row["people"] else ""))
        return
    if rows:
        save(rows)
    print("Saved.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if not os.environ.get("GITHUB_ACTIONS"):
            raise
        # Public log: say where it broke, never the error text (it can quote an email).
        import traceback
        print("Stopped on an error:", type(exc).__name__,
              getattr(getattr(exc, "response", None), "status_code", ""))
        print("".join(traceback.format_tb(exc.__traceback__)))
        sys.exit(1)
