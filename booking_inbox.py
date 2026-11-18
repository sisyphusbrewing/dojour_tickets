"""
Sisyphus - reads the booking@ inbox and files it on the Booking board.

Grace's Booking board (staff.sisyphusbrewing.com/booking/) shows every
weekend, what each show still needs, and the booking requests waiting for an
answer. This script is the part that reads the mail (Sam, Nov 14 2026: "booking
software for Grace ... connected to booking@"). It runs every hour as the
"Booking inbox" action and, for each conversation from the last few days:

  1. Throws out the noise: receipts, newsletters, our own automatic emails.
  2. Works out who it is about. A comic we already have on the calendar is
     matched by name; otherwise the name comes from the subject line
     ("Pat Example Avails") or the sender.
  3. Decides what it is:
       contract  a contract or deal memo, or an e-signature notice about one
       counts    an agent asking for ticket counts
       show      anything else about a show that is already booked
       request   someone asking for a date (agent pitch, avails, a comic)
       event     someone asking to rent the room for a private event
  4. Notes any paperwork attached (contract, W-9, rider), the dates they
     asked about, and whose turn it is to write back.
  5. Saves one row per conversation in Supabase (booking_threads). The board
     turns those into ticks on each show's checklist and the Requests list.

It only ever READS the mailbox: nothing is marked read, moved, labeled or
answered, and no email is sent. What is saved is the subject, who wrote, the
first couple of lines and attachment names; never whole emails or the files.

Needs the secret BOOKING_IMAP_PASS: an "app password" for the booking@ Google
account (myaccount.google.com/apppasswords). Until that exists the script
says so and stops without an error.

    python booking_inbox.py             the last 3 days
    DAYS=60 python booking_inbox.py     catch up on the last 60 days
    DRY_RUN=1 python booking_inbox.py   print what it would save, save nothing

This repo and its Actions logs are public, so as an action it prints counts
only: never names, addresses or subject lines.
"""
import email
import email.policy
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
IMAP_HOST = os.environ.get("BOOKING_IMAP_HOST") or "imap.gmail.com"
IMAP_USER = (os.environ.get("BOOKING_IMAP_USER") or "booking@sisyphusbrewing.com").strip()
IMAP_PASS = (os.environ.get("BOOKING_IMAP_PASS") or "").replace(" ", "").strip()
DAYS = int(os.environ.get("DAYS") or 3)
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

OURS = "sisyphusbrewing.com"
BIG_EMAIL = 4_000_000        # bigger than this, read the headers and attachment names only
THREADS_PER_ASK = 20         # conversations looked up in one question to Gmail
EMAILS_PER_ASK = 25          # emails downloaded in one go ...
BYTES_PER_ASK = 8_000_000    # ... or fewer, when they are large

# Shows that are not booked acts (same list the automatic advances skip).
REGULARS = re.compile(
    r"cancel|postpon|magic|gathering|blingo|advice column|\bmic\b|showcase|trivia|class|workshop|"
    r"private event|poets", re.IGNORECASE)

# The agencies that write to us, by the part of the address after the @.
AGENCIES = {
    "wmeagency.com": "WME", "unitedtalent.com": "UTA", "caa.com": "CAA", "gersh.com": "Gersh",
    "avalon-usa.com": "Avalon", "brillstein.com": "Brillstein", "independentartistgroup.com": "IAG",
    "ent360.com": "Entertainment 360", "innovativeartists.com": "Innovative Artists", "a3artistsagency.com": "A3",
    "paradigmagency.com": "Paradigm", "icmpartners.com": "ICM", "apa-agency.com": "APA", "3arts.com": "3 Arts",
    "levitytalent.com": "Levity", "omnipop.com": "Omnipop", "polaralg.com": "Polar", "theagencygroup.com": "TAG",
    "mainstageartists.com": "Mainstage", "personalpublicity.com": "Personal Publicity",
}

# E-signature services: their notices are about contracts, so they are not noise.
SIGNERS = re.compile(r"echosign|adobesign|docusign|esignature-noreply@google|hellosign|dropboxsign|pandadoc", re.I)
# Senders that are never a person writing about a booking.
NOISE = re.compile(
    r"no-?reply|do-?not-?reply|donotreply|notification|mailer-daemon|postmaster|newsletter|shopify|dojour|"
    r"google\.com$|facebookmail|instagram|linkedin|mailchimp|squarespace|intuit|quickbooks|paypal|venmo|"
    r"stripe|amazon|untappd|yelp|gotab|wheniwork|calendar-notification|bounce|marketing@|news@|hello@.*\.(io|co)$",
    re.I)
# Our own automatic emails, by subject.
OUR_AUTOMATIC = re.compile(
    r"^(your (vip|tickets|login)|supplies|safety report|what'?s new|voice note|pay request|ticket (report|count) for|"
    r"today'?s ticket count|weekly ticket|new job application|sign picture|recording)", re.I)

CONTRACT_WORDS = re.compile(r"\b(contract|agreement|deal memo|dealmemo|offer letter|booking confirmation|rider)\b", re.I)
CONTRACT_FILE = re.compile(r"contract|agreement|deal.?memo|offer|booking.?no|fully.?executed|countersigned", re.I)
SIGNED_WORDS = re.compile(r"fully executed|countersigned|\bsigned\b|^completed:|esigned document ready|is signed and filed|has been completed", re.I)
TO_SIGN_WORDS = re.compile(r"signature requested|please (e-?)?sign|awaiting (your )?signature|for (your )?signature|needs? (your )?signature|reminder: .*sign", re.I)
W9_WORDS = re.compile(r"\bw[\s-]?9\b", re.I)
RIDER_FILE = re.compile(r"rider|tech.?spec|hospitality", re.I)
COUNT_WORDS = re.compile(r"ticket counts?|ticket sales update|sales counts?|\bcounts? request", re.I)
EVENT_WORDS = re.compile(
    r"private (event|party|show)|rent(ing|al)? (the|your) (space|room|venue|taproom)|birthday|bachelor|corporate (event|outing)|"
    r"holiday party|fundraiser|rehearsal dinner|wedding|book (the|your) (space|room|taproom)|team (outing|building)|happy hour for", re.I)
REQUEST_WORDS = re.compile(
    r"avails?\b|availab|open dates?|headlin|book(ing|ed)?\b|routing|on tour|touring|tour dates|come (back|through)|"
    r"weekend|perform|stage time|guest spot|feature spot|host spot|submission|would love to|interested in|"
    r"comedy ideas|one[- ]nighter|hold(ing)? (a )?dates?", re.I)

FOLLOW_UP = re.compile(r"\bbump|follow(ing)?[- ]up|circling back|checking (back )?in|any update", re.I)
JUST_THANKS = re.compile(r"^(thanks?( you)?|many thanks|thx|perfect|great|awesome|got it|sounds (good|great)|appreciate|no worries|will do|ok(ay)?|wonderful)\b", re.I)


def just_thanks(text):
    """A short "Thank you so much!" that needs no answer. One that goes on to
    ask something ("Great, what does it cost?") still does."""
    text = text or ""
    return bool(JUST_THANKS.match(text)) and len(text) < 400 and "?" not in text

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_PATTERNS = [
    # "May 14/15 2027", "Sept 3-4", "March 26 & 27, 2027", "Nov. 12"
    re.compile(r"\b" + MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*(?:[-–/&]|and|to)\s*\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s*20\d\d)?", re.I),
    # "August-Sept", "early Sept", "Feb/March 2027"
    re.compile(r"\b(?:(?:early|mid|late)[- ])?" + MONTHS + r"(?:\s*(?:[-–/]|or|and|through|to)\s*" + MONTHS + r")?(?:\s+20\d\d)?(?![a-z])", re.I),
    # "3/26-27", "2/25", "5/14/27"
    re.compile(r"(?<![\d/.])\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[-–]\s*\d{1,2}(?:/\d{1,2})?)?(?![\d/])"),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def family(title):
    """The comic's name without the tour or 'Spooky Edition' tail, lowercased.
    Same rule as public.show_family() in Supabase."""
    t = re.sub(r"\s*(\(|:|\s[-–—|]\s).*$", "", title or "")
    return re.sub(r"\s+", " ", t).strip().lower()


def clean_subject(subject):
    """'Re: Fwd: RE: Pat Example Avails' -> 'Pat Example Avails'."""
    s = (subject or "").strip()
    while True:
        t = re.sub(r"^\s*(re|fwd?|fw)\s*:\s*", "", s, flags=re.I)
        if t == s:
            return re.sub(r"\s+", " ", s).strip()
        s = t


def domain(address):
    return (address or "").rsplit("@", 1)[-1].strip().lower()


def is_ours(address):
    return domain(address) == OURS


def agency_of(address):
    d = domain(address)
    for known, name in AGENCIES.items():
        if d == known or d.endswith("." + known):
            return name
    return None


def new_text(text):
    """What this message itself says: the body without the quoted earlier
    emails, forwarded headers and signature dashes."""
    lines = []
    for line in (text or "").replace("\r", "").split("\n"):
        s = line.strip()
        if re.match(r"^On .{5,90} wrote:$", s) or re.match(r"^-{2,}\s*Original Message", s, re.I):
            break
        if re.match(r"^From: .+@.+", s) and lines:        # Outlook-style quoted reply
            break
        if s.startswith(">") or re.match(r"^(Date|Sent|To|Cc|Subject):", s):
            continue
        if re.match(r"^-{5,}\s*Forwarded message", s, re.I):
            continue
        lines.append(s)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def forwarded_from(text):
    """(name, address) of whoever wrote the email that was forwarded to us,
    or None. Sam forwards booking asks from sam@ to booking@ this way."""
    m = re.search(r"Forwarded message.{0,40}?From:\s*(.+?)\s*<\s*([^<>\s]+@[^<>\s]+)\s*>", text or "", re.I | re.S)
    if not m:
        return None
    name = re.sub(r"[\"'*]", "", m.group(1)).strip()
    return name, m.group(2).strip().lower()


def forwarded_text(text):
    """The body of a forwarded email, after its little header block."""
    m = re.search(r"Forwarded message.*?\n\s*\n(.*)", text or "", re.I | re.S)
    return new_text(m.group(1)) if m else ""


def asked_dates(text):
    """The dates someone asked about, as they wrote them: 'May 14/15 2027, early Sept'."""
    found, spans = [], []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text or ""):
            if any(m.start() < e and m.end() > s for s, e in spans):
                continue                      # already inside a longer match
            piece = re.sub(r"\s+", " ", m.group(0)).strip(" .,")
            if re.fullmatch(r"(?i)may|march|mar", piece):
                continue                      # "may" and "march" are also plain words
            spans.append((m.start(), m.end()))
            found.append((m.start(), piece))
    out = []
    for _, piece in sorted(found):
        if piece.lower() not in [o.lower() for o in out]:
            out.append(piece)
    return ", ".join(out[:5])


def find_known_act(text, known):
    """The booked act named in this text, if any. known = list of act names."""
    low = " " + re.sub(r"[^a-z0-9&' ]+", " ", (text or "").lower()) + " "
    low = re.sub(r"\s+", " ", low)
    for act in sorted(known, key=len, reverse=True):
        fam = re.sub(r"[^a-z0-9&' ]+", " ", family(act))
        fam = re.sub(r"\s+", " ", fam).strip()
        if len(fam) >= 5 and (" " + fam + " ") in low:
            return act
    return None


NAME = r"[A-Z][\w.'’-]+(?:\s+(?:[A-Z][\w.'’-]+|&|and|de|la|van|von)){1,4}"
# Words that end a name at the front of a subject line: "Pat Example Avails".
NOT_A_NAME = re.compile(
    r"^(avails?|availability|dates?|tour|booking|bookings|sisyphus|brewing|comedy|club|minneapolis|mn|inquiry|request|"
    r"ticket|tickets|counts?|contract|offer|advance|show|shows|ideas|headlining|weekend|x|at|for|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|"
    r"september|october|november|december|20\d\d)$", re.I)
SUBJECT_LEAD = re.compile(
    r"^\s*(contract|advance|offer|avails?|booking( request| inquiry)?|ticket count request|signature requested on|"
    r"completed|reminder|esigned document ready|you signed)\s*[-:–]?\s*", re.I)


def leading_name(subject):
    """'Pat Example Avails' -> 'Pat Example'; 'Booking 2027' -> None."""
    words = []
    for word in re.sub(r"[\"“”]", "", subject).split():
        bare = word.strip(",.;:!?()")
        joiner = bare.lower() in ("&", "and", "de", "la", "van", "von") and words
        if NOT_A_NAME.match(bare) or not (joiner or re.match(r"^[A-Z][\w.'’-]*$", bare)):
            break
        words.append(bare)
        if word != bare and not word.startswith(bare + "'"):
            break                                  # punctuation ends the name
    while words and words[-1].lower() in ("&", "and", "de", "la", "van", "von"):
        words.pop()
    return " ".join(words) if len(words) >= 2 else None


def subject_name(subject):
    """The person a subject line leads with, once 'Contract -' and the like are peeled off."""
    s = clean_subject(subject)
    while SUBJECT_LEAD.match(s) and SUBJECT_LEAD.sub("", s) != s:
        s = SUBJECT_LEAD.sub("", s)
    return leading_name(s)


def guess_act(subject, sender_name, sender_address):
    """Who a request is about when it is nobody we have booked: the name in
    the subject line if there is one, else the person writing (a comic
    booking themselves)."""
    name = subject_name(subject)
    if name:
        return name
    s = clean_subject(subject)
    m = re.search(r"\b(?:for|regarding|booking)\s+(" + NAME + r")", s)
    if m and leading_name(m.group(1)):
        return leading_name(m.group(1))
    if sender_name and not agency_of(sender_address) and not SIGNERS.search(sender_address or ""):
        name = re.sub(r"\s*\(.*?\)\s*", " ", sender_name).strip()
        name = re.sub(r"\s+comedy$", "", name, flags=re.I)
        if name and "@" not in name:
            return " ".join(w if w[:1].isupper() else w.capitalize() for w in name.split())
    return None


def docs_in(message):
    """Paperwork this one message carries or announces."""
    subject = message.get("subject") or ""
    text = (subject + " " + new_text(message.get("text"))[:600])
    files = message.get("files") or []
    at = message["date"].isoformat() if message.get("date") else None
    docs = []
    signer = bool(SIGNERS.search(message.get("from_email") or "")) or bool(SIGNERS.search(text[:300]))
    contract_file = next((f for f in files if CONTRACT_FILE.search(f) and not W9_WORDS.search(f)), None)
    from_signer = bool(SIGNERS.search(message.get("from_email") or ""))
    signing_notice = from_signer and (TO_SIGN_WORDS.search(subject) or SIGNED_WORDS.search(subject))
    if (contract_file or signing_notice or (CONTRACT_WORDS.search(subject) and not W9_WORDS.search(subject))
            or (signer and CONTRACT_WORDS.search(text))):
        if SIGNED_WORDS.search(subject) or (contract_file and SIGNED_WORDS.search(contract_file)) or (signer and SIGNED_WORDS.search(text)):
            state = "signed"
        elif TO_SIGN_WORDS.search(text) or signer:
            state = "to_sign"
        else:
            state = "received"
        docs.append({"doc": "contract", "state": state, "name": contract_file or clean_subject(subject)[:120], "at": at})
    w9_file = next((f for f in files if W9_WORDS.search(f)), None)
    if w9_file:
        docs.append({"doc": "w9", "state": "received", "name": w9_file, "at": at})
    rider_file = next((f for f in files if RIDER_FILE.search(f)), None)
    if rider_file:
        docs.append({"doc": "rider", "state": "received", "name": rider_file, "at": at})
    return docs


def merge_docs(docs):
    """One line per kind of paperwork, keeping the furthest-along state."""
    rank = {"received": 1, "to_sign": 2, "signed": 3}
    best = {}
    for d in docs:
        old = best.get(d["doc"])
        if not old or rank[d["state"]] > rank[old["state"]] or (rank[d["state"]] == rank[old["state"]] and (d["at"] or "") > (old["at"] or "")):
            best[d["doc"]] = d
    return [best[k] for k in sorted(best)]


# ---------------------------------------------------------------------------
# The decision: what is this conversation?
# ---------------------------------------------------------------------------

def classify(thread, known_acts):
    """thread = {"key", "link", "messages": [{from_name, from_email, to: [..],
    date, subject, text, files: [..]}]} oldest first. known_acts = names of
    acts on the calendar. Returns the booking_threads row, or None for noise."""
    messages = [m for m in thread.get("messages") or [] if m.get("date")]
    if not messages:
        return None
    messages.sort(key=lambda m: m["date"])
    subject = clean_subject(messages[0].get("subject") or messages[-1].get("subject"))

    # Who outside Sisyphus is in this conversation? A forward from sam@ counts
    # as its original sender.
    people = []
    for m in messages:
        addr = (m.get("from_email") or "").lower()
        if is_ours(addr):
            fwd = forwarded_from(m.get("text"))
            if fwd and not is_ours(fwd[1]):
                people.append({"name": fwd[0], "email": fwd[1], "text": forwarded_text(m.get("text")), "date": m["date"], "fwd": True})
            continue
        if SIGNERS.search(addr):
            people.append({"name": m.get("from_name") or "E-signature", "email": addr, "text": new_text(m.get("text")), "date": m["date"], "signer": True})
        elif not NOISE.search(addr):
            people.append({"name": m.get("from_name") or addr, "email": addr, "text": new_text(m.get("text")), "date": m["date"]})

    docs = merge_docs([d for m in messages for d in docs_in(m)])
    if not people:
        return None                           # all ours, or all automatic
    if OUR_AUTOMATIC.search(subject) and not docs:
        return None

    real = [p for p in people if not p.get("signer")] or people
    who = real[-1]
    everything = subject + " " + " ".join(p["text"] for p in people)
    names = " . ".join(p["name"] for p in real)
    # Who is it about? The subject line wins: "Lou Example - Sisyphus" is about
    # Lou even when the email also mentions a comic we already have booked.
    known = find_known_act(subject, known_acts)
    named = None if known else subject_name(subject)
    if not known and not named:
        known = find_known_act(everything[:3000], known_acts) or find_known_act(names, known_acts)

    has_contract = any(d["doc"] == "contract" for d in docs)
    if has_contract:
        kind = "contract"
    elif COUNT_WORDS.search(subject):
        kind = "counts"
    elif known:
        kind = "show"
    elif EVENT_WORDS.search(everything[:2500]):
        kind = "event"
    elif (REQUEST_WORDS.search(everything[:2500]) or agency_of(who["email"])
          or (named and FOLLOW_UP.search(everything[:1500]))):
        kind = "request"
    elif docs:
        kind = "show"
    else:
        return None                           # a customer question, a vendor, small talk

    act = known or named
    if not act:
        act = guess_act(subject, None if who.get("signer") else who["name"], who["email"])

    # Whose turn is it? Ours unless the last word was ours, to someone outside.
    last = messages[-1]
    last_ours = is_ours(last.get("from_email"))
    wrote_out = any(not is_ours(a) for a in last.get("to") or [])
    waiting = "them" if (last_ours and wrote_out) else "us"
    latest_outside = max(real, key=lambda p: p["date"])
    answered = any(is_ours(m.get("from_email")) and any(not is_ours(a) for a in m.get("to") or []) for m in messages)
    if answered and just_thanks(latest_outside["text"]):
        waiting = "them"                      # "Thank you so much!" needs no answer
    if kind == "contract" and docs and all(d["state"] == "signed" for d in docs if d["doc"] == "contract"):
        waiting = "them"                      # nothing left to answer on a finished contract

    asked = asked_dates(subject + " . " + latest_outside["text"][:1500]) if kind in ("request", "event") else ""
    return {
        "key": thread["key"],
        "source": "email",
        "kind": kind,
        "subject": subject[:200],
        "from_name": (who["name"] or "")[:120],
        "from_email": who["email"][:200],
        "agency": agency_of(who["email"]),
        "act": (act or "")[:120] or None,
        "asked": asked[:200] or None,
        "snippet": latest_outside["text"][:260] or None,
        "docs": docs,
        "link": thread.get("link"),
        "first_at": messages[0]["date"].isoformat(),
        "last_at": last["date"].isoformat(),
        "last_from": (last.get("from_name") or last.get("from_email") or "")[:120],
        "msg_count": len(messages),
        "waiting_on": waiting,
    }


# ---------------------------------------------------------------------------
# Reading the mailbox (read-only)
# ---------------------------------------------------------------------------

def decoded(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def body_text(msg):
    """The plain-text body of an email (or its HTML with the tags stripped)."""
    plain, html = None, None
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        try:
            text = part.get_content()
        except Exception:
            continue
        if kind == "text/plain" and plain is None:
            plain = text
        elif kind == "text/html" and html is None:
            html = text
    if plain is not None:
        return plain
    if html is not None:
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        html = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", html)
        return re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").replace("&amp;", "&")
    return ""


def parse_message(raw):
    """One raw email -> the small dict classify() reads."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, addr = parseaddr(decoded(msg.get("From", "")))
    to = [a.lower() for _, a in getaddresses([decoded(msg.get(h, "")) for h in ("To", "Cc")]) if a]
    try:
        date = parsedate_to_datetime(msg.get("Date"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
    except Exception:
        date = None
    files = [decoded(p.get_filename()) for p in msg.walk() if p.get_filename()]
    # A mailing-list email says so in its headers ("List-Unsubscribe"). The
    # events@ reader uses this to tell a newsletter from a person.
    bulk = bool(msg.get("List-Unsubscribe")) or str(msg.get("Precedence", "")).strip().lower() in ("bulk", "list", "junk")
    return {"from_name": name.strip(), "from_email": addr.lower(), "to": to, "date": date,
            "subject": decoded(msg.get("Subject", "")), "text": body_text(msg)[:20000], "files": files, "bulk": bulk}


def _line(row):
    """The text part of one line of an IMAP answer."""
    return (row if isinstance(row, bytes) else row[0]) or b""


def _thread_uids(box, thread_ids):
    """{conversation id: [its emails, oldest first]}. Asks Gmail about a
    handful of conversations at a time: one question per conversation took
    longer than the job is allowed on the first 60-day catch-up (Nov 17 2026)."""
    found = {t: [] for t in thread_ids}
    for i in range(0, len(thread_ids), THREADS_PER_ASK):
        group = thread_ids[i:i + THREADS_PER_ASK]
        uids = []
        if len(group) > 1:
            # "this conversation OR that one OR ..." in IMAP's own wording
            ask = "X-GM-THRID " + group[-1]
            for t in reversed(group[:-1]):
                ask = f"OR X-GM-THRID {t} {ask}"
            try:
                status, data = box.uid("SEARCH", None, ask)
                uids = data[0].split() if status == "OK" and data and data[0] else []
            except imaplib.IMAP4.error:
                uids = []
        if not uids:
            # One conversation, or Gmail didn't take the grouped question: ask one by one.
            for t in group:
                _, data = box.uid("SEARCH", None, "X-GM-THRID", t)
                found[t] = [int(u) for u in data[0].split()]
            continue
        # Which of those emails belongs to which conversation?
        for j in range(0, len(uids), 200):
            _, rows = box.uid("FETCH", b",".join(uids[j:j + 200]), "(X-GM-THRID)")
            for row in rows:
                t = re.search(rb"X-GM-THRID (\d+)", _line(row))
                u = re.search(rb"UID (\d+)", _line(row))
                if t and u and t.group(1).decode() in found:
                    found[t.group(1).decode()].append(int(u.group(1)))
    return {t: sorted(set(u)) for t, u in found.items()}


def _download(box, uids):
    """{email: its raw text} for a group of emails asked for in one go.
    PEEK: nothing gets marked as read."""
    got = {}
    if not uids:
        return got
    _, parts = box.uid("FETCH", ",".join(str(u) for u in uids), "(BODY.PEEK[])")
    for n, part in enumerate(parts):
        if not isinstance(part, tuple):
            continue
        # Gmail says which email this is either before the text or right after it.
        after = parts[n + 1] if n + 1 < len(parts) and isinstance(parts[n + 1], bytes) else b""
        m = re.search(rb"UID (\d+)", part[0] or b"") or re.search(rb"UID (\d+)", after)
        if m:
            got[int(m.group(1))] = part[1]
        elif len(uids) == 1:
            got[uids[0]] = part[1]
    return got


def read_mailbox(days, user=None, password=None):
    """Every conversation with a message in the last `days` days, read-only.
    Returns [{"key", "link", "messages"}]. It reads booking@ unless another
    mailbox's address and app password are passed in (events_inbox.py reads
    events@ with this same function)."""
    user, password = user or IMAP_USER, password or IMAP_PASS
    box = imaplib.IMAP4_SSL(IMAP_HOST)
    box.login(user, password)
    try:
        # All Mail has both what came in and what Grace sent, so we can tell
        # whose turn it is. readonly=True: nothing gets marked as read.
        status, _ = box.select('"[Gmail]/All Mail"', readonly=True)
        if status != "OK":
            box.select("INBOX", readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        _, data = box.uid("SEARCH", None, "SINCE", since)
        recent = data[0].split()
        if not recent:
            return []
        # Which conversations do those belong to?
        thread_ids = set()
        for i in range(0, len(recent), 200):
            _, rows = box.uid("FETCH", b",".join(recent[i:i + 200]), "(X-GM-THRID)")
            for row in rows:
                m = re.search(rb"X-GM-THRID (\d+)", _line(row))
                if m:
                    thread_ids.add(m.group(1).decode())
        thread_ids = sorted(thread_ids)
        # Every email of those conversations, older ones included. A very long
        # thread: the latest 25 are plenty.
        in_thread = {t: uids[-25:] for t, uids in _thread_uids(box, thread_ids).items()}
        wanted = [u for t in thread_ids for u in in_thread[t]]
        # How big is each one? (asked 200 at a time)
        sizes = {}
        for i in range(0, len(wanted), 200):
            _, rows = box.uid("FETCH", ",".join(str(u) for u in wanted[i:i + 200]), "(RFC822.SIZE)")
            for row in rows:
                u, size = re.search(rb"UID (\d+)", _line(row)), re.search(rb"RFC822\.SIZE (\d+)", _line(row))
                if u and size:
                    sizes[int(u.group(1))] = int(size.group(1))
        # Download them a group at a time, not one by one.
        parsed, group, weight = {}, [], 0

        def take(batch):
            got = _download(box, batch)
            for uid in batch:
                if uid not in got and len(batch) > 1:
                    got.update(_download(box, [uid]))        # missed in the group: ask for it alone
                if got.get(uid):
                    try:
                        parsed[uid] = parse_message(got[uid])
                    except Exception:
                        pass                                 # one unreadable email never stops the run

        for uid in wanted:
            size = sizes.get(uid, 0)
            if size > BIG_EMAIL:
                # Too big to download: read the headers, and take the
                # attachment names from the email's outline.
                _, parts = box.uid("FETCH", str(uid), "(BODY.PEEK[HEADER] BODYSTRUCTURE)")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw:
                    try:
                        parsed[uid] = parse_message(raw)
                        outline = b" ".join(_line(p) for p in parts)
                        parsed[uid]["files"] = [n.decode("utf-8", "replace")
                                                for n in re.findall(rb'"(?:file)?name\*?" "([^"]+)"', outline, re.I)]
                    except Exception:
                        pass
                continue
            if group and (len(group) >= EMAILS_PER_ASK or weight + size > BYTES_PER_ASK):
                take(group)
                group, weight = [], 0
            group.append(uid)
            weight += size
        take(group)

        threads = []
        for thrid in thread_ids:
            messages = [parsed[u] for u in in_thread[thrid] if u in parsed]
            if messages:
                threads.append({"key": "gm:" + thrid, "messages": messages,
                                "link": f"https://mail.google.com/mail/u/0/?authuser={user}#all/{int(thrid):x}"})
        return threads
    finally:
        try:
            box.logout()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

def auth():
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def known_acts():
    """Acts on the calendar: shows on sale, dates pencilled on the board, advances."""
    names = set()
    since = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    for table, column, params in (
        ("show_nights", "title", {"starts_at": f"gte.{since}"}),
        ("booking_shows", "act", {"stage": "neq.dropped"}),
        ("advances", "show_name", {"show_date": f"gte.{since[:10]}"}),
    ):
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", params={"select": column, **params}, headers=auth(), timeout=30)
        r.raise_for_status()
        for row in r.json():
            name = (row.get(column) or "").strip()
            if name and not REGULARS.search(name):
                names.add(name)
    return sorted(names)


def save(rows):
    """Add or refresh the rows. Only the columns we send are touched, so a
    manager's status and note on a request are never overwritten."""
    for i in range(0, len(rows), 100):
        r = requests.post(f"{SUPABASE_URL}/rest/v1/booking_threads", params={"on_conflict": "key"},
                          headers={**auth(), "Content-Type": "application/json",
                                   "Prefer": "resolution=merge-duplicates,return=minimal"},
                          data=json.dumps(rows[i:i + 100]), timeout=60)
        r.raise_for_status()


def calls_to_carry(rows, preview_rows):
    """Before this inbox was connected, the board was filled with the booking
    mail that had been copied to Sam (rows keyed "sam:..."). A manager may
    have already sorted some of those (later / pass / pencilled). This pairs
    each of those calls with the same conversation as read from the real
    inbox, matched by subject line, so the call isn't lost."""
    by_subject = {}
    for old in preview_rows:
        subject = clean_subject(old.get("subject")).lower()
        if subject and old.get("status"):
            by_subject[subject] = old
    pairs = []
    for row in rows:
        old = by_subject.get(clean_subject(row.get("subject")).lower())
        if old:
            pairs.append((row["key"], old))
    return pairs


def carry_over(rows):
    """Move each call made on a preview row to the real conversation, once:
    the real row only takes it if nobody has made a call there yet, and the
    preview row's call is cleared so it is never copied a second time."""
    url = f"{SUPABASE_URL}/rest/v1/booking_threads"
    r = requests.get(url, params={"select": "key,subject,status,status_by,status_at,note", "key": "like.sam:*",
                                  "status": "not.is.null"}, headers=auth(), timeout=30)
    r.raise_for_status()
    pairs = calls_to_carry(rows, r.json())
    headers = {**auth(), "Content-Type": "application/json", "Prefer": "return=minimal"}
    for key, old in pairs:
        call = {k: old.get(k) for k in ("status", "status_by", "status_at", "note")}
        requests.patch(url, params={"key": f"eq.{key}", "status": "is.null"}, headers=headers,
                       data=json.dumps(call), timeout=30).raise_for_status()
        requests.patch(url, params={"key": f"eq.{old['key']}"}, headers=headers,
                       data=json.dumps({"status": None}), timeout=30).raise_for_status()
    return len(pairs)


def main():
    if not IMAP_PASS:
        print("BOOKING_IMAP_PASS is not set yet, so there is no way into the booking@ inbox. Nothing to do.")
        return
    if not SERVICE_KEY and not DRY_RUN:
        sys.exit("SUPABASE_SERVICE_ROLE_KEY is required")
    acts = known_acts() if SERVICE_KEY else []
    threads = read_mailbox(DAYS)
    rows, unreadable = [], 0
    for t in threads:
        try:
            row = classify(t, acts)
        except Exception:
            unreadable += 1                              # counted, not shown: the log is public
            continue
        if row:
            rows.append(row)
    counts = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(f"Read {len(threads)} conversations from the last {DAYS} days; kept {len(rows)}: "
          + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none")
          + (f". {unreadable} could not be read." if unreadable else ""))
    if DRY_RUN:
        # This repo and its Actions logs are public, so the per-email detail
        # (names, subject lines) only prints when run by hand on a computer.
        for row in ([] if os.environ.get("GITHUB_ACTIONS") else rows):
            print(f"  [{row['kind']}] {row['act'] or '?'} | {row['subject']} | waiting on {row['waiting_on']}"
                  + (f" | asked: {row['asked']}" if row["asked"] else "")
                  + (f" | {', '.join(d['doc'] + ':' + d['state'] for d in row['docs'])}" if row["docs"] else ""))
        return
    if rows:
        save(rows)
        moved = carry_over(rows)
        if moved:
            print(f"Carried over {moved} call(s) a manager made on the preview rows.")
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
