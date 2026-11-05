"""
Block website sales on Dojour.

Dojour and the website sell the same 90 seats. sync_inventory.py already takes
Dojour sales off the website; this does the other direction. For every upcoming
Dojour showtime it adds up website tickets + comps (Supabase `tickets`) and
compares that with the seats the venue has already blocked on Dojour (manual
reservations with no email: Sam's "Shopify Sales" / "Hold" rows and ours). If
more need blocking, it adds one manual reservation named "Website Hold" with
the difference, GA against GA and VIP against Reserved, never more than Dojour
still has open. It never cancels a hold (a website refund leaves the seat
blocked, which is the safe side).

"Website Hold" has no email and "hold" in its name, so the inventory mirror,
the door list counts and every agent report treat it as a block, not a sale.

Env: DOJOUR_STATE (or DOJOUR_TOKEN), SUPABASE_URL, SUPABASE_KEY.
  APPLY=1            actually create holds (default: print the plan only)
  INSTANCE_IDS=a,b   only these Dojour showtimes
"""
import os
import re
import sys
from collections import defaultdict

import requests

from fetch_tickets import (clean_show_title, format_show_date, get_dojour_token,
                           is_past_event, parse_show_datetime)

API = "https://dojour.us/api/"
APPLY = os.environ.get("APPLY", "").strip().lower() in ("1", "true", "yes")
ONLY = {x.strip() for x in (os.environ.get("INSTANCE_IDS") or "").split(",") if x.strip()}
HOLD_FIRST = HOLD_LAST = "Website Hold"   # same as Sam's own holds

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def is_vip(title):
    return bool(re.search(r"vip|premium|reserved", title or "", re.I))


def website_counts():
    """{(title lower, show_date): {"ga": n, "vip": n}} for Website and Comp rows."""
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    rows, offset = [], 0
    while True:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/tickets?select=show_title,show_date,tickets,source,ticket_type"
                         f"&source=in.(Website,Comp)&limit=1000&offset={offset}", headers=h, timeout=30)
        r.raise_for_status()
        page = r.json()
        rows += page
        if len(page) < 1000:
            break
        offset += 1000
    out = defaultdict(lambda: {"ga": 0, "vip": 0})
    for row in rows:
        key = ((row.get("show_title") or "").strip().lower(), (row.get("show_date") or "").strip())
        tier = "vip" if row.get("source") == "Website" and is_vip(row.get("ticket_type")) else "ga"
        out[key][tier] += int(row.get("tickets") or 0)
    return out


class Dojour:
    def __init__(self):
        token = get_dojour_token()
        self.s = requests.Session()
        self.s.cookies.set("usertoken", token, domain="dojour.us")
        self.s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json",
                               "User-Agent": "Mozilla/5.0"})

    def get(self, path):
        r = self.s.get(API + path if not path.startswith("http") else path, timeout=30)
        r.raise_for_status()
        return r.json()

    def showings(self):
        url, out = API + "event_instances/reserve_reports/?page_size=100&upcoming=true", []
        while url:
            data = self.get(url)
            out += data.get("results", []) if isinstance(data, dict) else data
            url = data.get("next") if isinstance(data, dict) else None
        return out

    def manual_create(self, payload):
        """The dashboard's Add Reservation call, exactly as recorded from Sam's browser
        (Nov 5 2026): token auth, no CSRF, Origin + admin-tools Referer."""
        h = {"Content-Type": "application/json;charset=UTF-8", "Origin": "https://dojour.us",
             "Referer": f"https://dojour.us/admin-tools/reservations/s/{payload['showing']}/add"}
        try:
            key = self.s.post(API + "sessions/current/", json={"referrer_link": "", "referrer": "dojour.us"},
                              timeout=20).json().get("session_key")
            if key:
                h["Dojour-Session"] = f"Key {key}"
        except Exception:
            pass
        return self.s.post(API + "reservations/manual_create/", json=payload, headers=h, timeout=30)


def venue_holds(report):
    """Seats already blocked by the venue, per option id: manual, no email, not cancelled."""
    held = defaultdict(int)
    for res in report.get("reservation_set") or []:
        if res.get("is_cancelled") or not res.get("manual_add"):
            continue
        email = res.get("email") or ((res.get("user") or {}).get("email") if isinstance(res.get("user"), dict) else "")
        if email:
            continue
        for opt in res.get("option_set") or []:
            held[opt.get("offer_option_id")] += int(opt.get("count") or 0)
    return held


def oid(opt):
    """Dojour's report calls an option's id offer_option_id; the offer itself calls it id."""
    return opt.get("offer_option_id") or opt.get("id")


def option_remaining(opt):
    for k in ("remaining_count", "remaining"):
        if opt.get(k) is not None:
            return max(int(opt[k]), 0)
    return None


def plan_for(report, title, date_str, web):
    """Returns (payload or None, summary line)."""
    options = report.get("option_set") or []
    if not options:
        return None, "no ticket options"
    held = venue_holds(report)
    ga = [o for o in options if not is_vip(o.get("title"))]
    vip = [o for o in options if is_vip(o.get("title"))]
    held_ga = sum(held.get(oid(o), 0) for o in ga)
    held_vip = sum(held.get(oid(o), 0) for o in vip)
    need = {"ga": max(web["ga"] - held_ga, 0), "vip": max(web["vip"] - held_vip, 0)}
    # Held seats count against the total even when bought in the other tier.
    extra_held = max(held_ga - web["ga"], 0) + max(held_vip - web["vip"], 0)
    total_need = max(need["ga"] + need["vip"] - extra_held, 0)
    if total_need == 0:
        return None, f"ok (website {web['ga']}+{web['vip']} vip, held {held_ga}+{held_vip} vip)"

    counts = {}
    order = [("ga", ga), ("vip", vip)] if need["ga"] >= need["vip"] else [("vip", vip), ("ga", ga)]
    left = total_need
    # First each tier against its own options, then any overflow into whatever is open.
    for tier, opts in order + [("any", ga + vip)]:
        want = left if tier == "any" else min(need[tier], left)
        for o in opts:
            if want <= 0:
                break
            k = oid(o)
            room = option_remaining(o)
            room = want if room is None else room - counts.get(k, 0)
            take = max(min(want, room), 0)
            if take:
                counts[k] = counts.get(k, 0) + take
                want -= take
                left -= take
    blocked = sum(counts.values())
    if not blocked:
        return None, f"needs {total_need} but Dojour has nothing open"
    payload_opts = []
    for o in options:
        o2 = dict(o)
        o2["count"] = counts.get(oid(o), 0)
        payload_opts.append(o2)
    payload = {"showing": report.get("id"), "option_set": payload_opts, "upgrade_set": report.get("upgrade_set") or [],
               "form_response": None, "send_email": False, "first_name": HOLD_FIRST, "last_name": HOLD_LAST}
    detail = ", ".join(f"{counts[oid(o)]} {o.get('title', '').split(' - ')[0]}" for o in options if counts.get(oid(o)))
    return payload, f"BLOCK {blocked} ({detail}); website {web['ga']}+{web['vip']} vip, held {held_ga}+{held_vip} vip"


def main():
    dj = Dojour()
    try:
        # Holds must be made by the Sisyphus business login (user 320), the one Sam uses.
        print("Dojour login: user", dj.get("account/current/").get("id"))
    except Exception as e:
        print("Could not read the Dojour login:", e)
    web_counts = website_counts()
    made, failures = 0, []
    for item in dj.showings():
        inst = str(item.get("id") or item.get("event_instance_id") or "")
        if not inst or (ONLY and inst not in ONLY):
            continue
        dt = parse_show_datetime(item.get("start_dt"))
        if not dt or is_past_event(dt):
            continue
        report = dj.get(f"event_instances/{inst}/reserve_report/")
        # Same title rule as fetch_tickets.py, so it matches the Supabase rows.
        opt_title = ((item.get("option_set") or [{}])[0] or {}).get("title", "")
        title = clean_show_title(opt_title or item.get("title", ""))
        if not title:
            title = next((clean_show_title(r["event_title"]) for r in report.get("reservation_set") or []
                          if r.get("event_title")), "")
        if not title and report.get("option_set"):
            title = clean_show_title(report["option_set"][0].get("title", ""))
        date_str = format_show_date(dt)
        web = web_counts.get((title.lower(), date_str), {"ga": 0, "vip": 0})
        payload, line = plan_for(report, title, date_str, web)
        print(f"{inst} {title} | {date_str}: {line}")
        if ONLY:
            print("   options:", [(oid(o), sorted(o.keys()), o.get("title", "")[:30], o.get("limit"),
                                  o.get("remaining_count")) for o in report.get("option_set") or []])
        if not payload or not APPLY:
            continue
        r = dj.manual_create(payload)
        if r.status_code in (200, 201):
            made += 1
            print(f"   created hold {r.json().get('encrypted_pk')}")
        else:
            failures.append(inst)
            print(f"   FAILED {r.status_code}: {r.text[:500]}")
    print(f"{'Created' if APPLY else 'Would create'} holds; made {made}, failed {len(failures)}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
