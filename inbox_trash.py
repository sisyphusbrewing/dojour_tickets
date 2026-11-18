"""
Sisyphus - moves obvious junk in the events@ or booking@ inbox to Trash.

Sam, Nov 18 2026: "it would be nice to not have to deal with stuff that is
obvious trash ... In all 3 inboxes". sam@ is cleaned through the Gmail
connector; events@ and booking@ have no connector, so this does it for them
with the same app passwords the inbox readers use (EVENTS_IMAP_PASS,
BOOKING_IMAP_PASS).

It only does what it is told: a list of conversations, by the key the
readers save (events_threads.key / booking_threads.key, "gm:<number>").
For each one it:

  - refuses if anyone at Sisyphus ever wrote in that conversation (a real
    conversation is never junk), or if it can't find it;
  - otherwise moves every email of it to Trash. Trash, never a permanent
    delete: Gmail keeps it there for 30 days and it can be put back.

Nothing else is touched: nothing is marked read, labeled, answered or sent.
Afterwards the conversation's row on the staff site is marked handled
(events: "done"; booking: "pass"), with the note "Moved to Trash".

    INBOX=events KEYS=gm:123,gm:456 python inbox_trash.py
    DRY_RUN=1 ...   say what it would do, change nothing

This repo and its Actions logs are public: it prints counts only.
"""
import imaplib
import os
import re
import sys

import requests

import booking_inbox as mail

MAX_PER_RUN = 50
INBOXES = {
    # inbox: (address, password env, table, status to set)
    "events": ("events@sisyphusbrewing.com", "EVENTS_IMAP_PASS", "events_threads", "done"),
    "booking": ("booking@sisyphusbrewing.com", "BOOKING_IMAP_PASS", "booking_threads", "pass"),
}


def parse_keys(text):
    """'gm:123, gm:456' or '123 456' -> ['123', '456'] (Gmail conversation numbers).
    A hex id from a Gmail link (like 1a1f057ca4d87b59) is turned into the number."""
    out = []
    for part in re.split(r"[\s,]+", text or ""):
        part = part.strip()
        if not part:
            continue
        if part.lower().startswith("gm:"):
            part = part[3:]
        if part.isdigit():
            out.append(part)
        elif re.fullmatch(r"[0-9a-fA-F]{12,16}", part):
            out.append(str(int(part, 16)))
        else:
            raise ValueError("not a conversation key")
    seen = []
    for k in out:
        if k not in seen:
            seen.append(k)
    return seen


def from_us(raw_headers):
    """True when an email's From is a Sisyphus address."""
    m = re.search(rb"^From:(.*(?:\r?\n[ \t].*)*)", raw_headers, re.I | re.M)
    if not m:
        return False
    found = re.findall(r"[\w.+-]+@[\w.-]+", m.group(1).decode("utf-8", "replace"))
    return any(mail.is_ours(a.lower()) for a in found)


def trash(box, thread_ids, dry_run):
    """Returns (trashed, refused, missing) conversation counts."""
    trashed = refused = missing = 0
    done = []
    found = mail._thread_uids(box, thread_ids)
    for t in thread_ids:
        uids = found.get(t) or []
        if not uids:
            missing += 1
            continue
        _, parts = box.uid("FETCH", ",".join(str(u) for u in uids), "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        heads = [p[1] for p in parts if isinstance(p, tuple)]
        if any(from_us(h) for h in heads):
            refused += 1
            continue
        if not dry_run:
            status, _ = box.uid("STORE", ",".join(str(u) for u in uids), "+X-GM-LABELS", "(\\Trash)")
            if status != "OK":
                refused += 1
                continue
        trashed += 1
        done.append(t)
    return trashed, refused, missing, done


def mark_rows(table, status, thread_ids):
    if not thread_ids or not mail.SERVICE_KEY:
        return
    keys = ",".join(f'"gm:{t}"' for t in thread_ids)
    requests.patch(
        f"{mail.SUPABASE_URL}/rest/v1/{table}?key=in.({keys})",
        headers={**mail.auth(), "Content-Type": "application/json", "Prefer": "return=minimal"},
        json={"status": status, "status_by": "trash job", "note": "Moved to Trash"},
        timeout=30,
    ).raise_for_status()


def main():
    inbox = (os.environ.get("INBOX") or "").strip().lower()
    if inbox not in INBOXES:
        print("INBOX must be events or booking.")
        return 1
    address, pass_env, table, status = INBOXES[inbox]
    password = (os.environ.get(pass_env) or "").replace(" ", "").strip()
    dry_run = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    try:
        thread_ids = parse_keys(os.environ.get("KEYS"))
    except ValueError:
        print("A key wasn't a conversation key (gm:<number>). Nothing done.")
        return 1
    if not thread_ids:
        print("No conversations given. Nothing to do.")
        return 0
    if len(thread_ids) > MAX_PER_RUN:
        print(f"{len(thread_ids)} conversations is more than {MAX_PER_RUN} at once. Nothing done.")
        return 1
    if not password:
        print(f"{pass_env} is not set, so there is no way into that inbox. Nothing done.")
        return 1
    box = imaplib.IMAP4_SSL(mail.IMAP_HOST)
    box.login(address, password)
    try:
        status_ok, _ = box.select('"[Gmail]/All Mail"')
        if status_ok != "OK":
            print("Couldn't open All Mail. Nothing done.")
            return 1
        trashed, refused, missing, done = trash(box, thread_ids, dry_run)
    finally:
        try:
            box.logout()
        except Exception:
            pass
    if not dry_run:
        mark_rows(table, status, done)
    word = "Would move" if dry_run else "Moved"
    print(f"{inbox}: {word} {trashed} conversation(s) to Trash; "
          f"{refused} left alone (someone at Sisyphus wrote in it); {missing} not found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
