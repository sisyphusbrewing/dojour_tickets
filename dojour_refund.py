"""
Sisyphus - give a Dojour buyer part of their money back (a flat amount), without
cancelling their tickets.

Why: when a VIP / Reserved Seating buyer didn't get the VIP treatment, Sam refunds
the difference between VIP and General Admission (Sam, Nov 7 2026). Dojour's own
dashboard does this from the reservation's Refund page with "Return a flat amount";
this script sends that same request, so nobody has to click through it.

Run from GitHub: Actions -> "Dojour partial refund" -> Run workflow with the
reservation id (Dojour's 13-character code), the amount in dollars, and apply = true.
With apply left off it only prints what it would do.

Dojour refuses some write calls from cloud/GitHub IPs but accepts them from Sam's
own network (found Nov 5 2026). If GitHub gets a "permission" error, run the same
script on Sam's Mac:  DOJOUR_TOKEN=... python3 dojour_refund.py <reservation> <dollars> --apply

Env: DOJOUR_STATE or DOJOUR_TOKEN, RESERVATION, AMOUNT (dollars, e.g. 21.94),
     APPLY=1 to really refund, MAX_AMOUNT (dollars, default 100) as a safety cap.
"""
import json
import os
import sys

import requests

from fetch_tickets import get_dojour_token

API = "https://dojour.us/api/"


def to_cents(dollars) -> int:
    return int(round(float(str(dollars).replace("$", "").strip()) * 100))


def already_refunded(reservation: dict, refunds: list) -> int:
    """Cents already given back on this reservation (earlier refunds)."""
    total = 0
    for r in refunds or []:
        for key in ("amount", "refund_amount", "total"):
            if isinstance(r.get(key), (int, float)):
                total += int(r[key])
                break
    return total


def build_refund_body(reservation: dict, amount_cents: int, refunded_cents: int = 0,
                      max_cents: int = 10000) -> dict:
    """The body Dojour's Refund page posts for "Return a flat amount": every ticket
    stays (counts and prices unchanged), only comp_amount comes back to the buyer,
    to their card (not as Dojour credit)."""
    if amount_cents <= 0:
        raise ValueError("Refund amount must be more than $0.")
    if amount_cents > max_cents:
        raise ValueError(f"${amount_cents / 100:.2f} is over the ${max_cents / 100:.2f} safety cap.")
    if reservation.get("is_cancelled"):
        raise ValueError("That reservation is cancelled; nothing to refund.")
    paid = int((reservation.get("invoice") or {}).get("charge_amount") or 0)
    if amount_cents > paid - refunded_cents:
        raise ValueError(f"Buyer paid ${paid / 100:.2f} and already got ${refunded_cents / 100:.2f} back; "
                         f"can't refund ${amount_cents / 100:.2f}.")
    body = dict(reservation)
    options = []
    for opt in (reservation.get("option_set") or []) + (reservation.get("upgrade_set") or []):
        o = dict(opt)
        item = o.get("invoice_item") or {}
        units = int(item.get("unit_count") or 0)
        per_unit = (item.get("due") or 0) / units if units else 0
        o.update(reserve_count=o.get("count"), reserve_count_max=o.get("count"),
                 invoice_count=units, invoice_count_max=units,
                 invoice_price=per_unit, invoice_price_max=per_unit)
        options.append(o)
    body.update(full_option_set=options, add_comp=True, comp_amount=amount_cents,
                return_total=0, refund_amount=amount_cents, refund_fees=False,
                refund_as_credit=False)
    return body


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pk = (os.environ.get("RESERVATION") or (args[0] if args else "")).strip()
    amount = to_cents(os.environ.get("AMOUNT") or (args[1] if len(args) > 1 else "0"))
    apply = "--apply" in sys.argv or os.environ.get("APPLY", "").strip().lower() in ("1", "true", "yes")
    cap = to_cents(os.environ.get("MAX_AMOUNT") or "100")
    if not pk:
        sys.exit("Give the Dojour reservation id.")

    token = get_dojour_token()
    s = requests.Session()
    s.cookies.set("usertoken", token, domain="dojour.us")
    s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json",
                      "User-Agent": "Mozilla/5.0"})

    r = s.get(API + f"reservations/{pk}/", timeout=30)
    if r.status_code != 200:
        sys.exit(f"Couldn't read reservation {pk}: {r.status_code} {r.text[:300]}")
    res = r.json()
    rr = s.get(API + "reservation_refunds/", params={"reservation_id": pk}, timeout=30)
    refunds = (rr.json().get("results", []) if rr.status_code == 200 and isinstance(rr.json(), dict) else []) or []
    done = already_refunded(res, refunds)

    tickets = ", ".join(f"{o.get('count')} x {o.get('title')}" for o in res.get("option_set") or [])
    paid = (res.get("invoice") or {}).get("charge_amount") or 0
    initial = (res.get("last_name") or " ")[0]
    print(f"Reservation {pk}: {res.get('first_name')} {initial}. - {tickets}; paid ${paid / 100:.2f}; earlier refunds {len(refunds)} (${done / 100:.2f})")
    body = build_refund_body(res, amount, done, cap)
    print(f"Plan: return ${amount / 100:.2f} to the card, tickets stay as they are.")
    if not apply:
        print("Dry run only (set apply to really refund).")
        return

    p = s.post(API + f"reservations/{pk}/create_refund/", json=body, timeout=60)
    print("Dojour answered:", p.status_code)
    if p.status_code not in (200, 201):
        print(p.text[:800])
        sys.exit(1)
    rr = s.get(API + "reservation_refunds/", params={"reservation_id": pk}, timeout=30)
    after = rr.json().get("results", []) if rr.status_code == 200 and isinstance(rr.json(), dict) else []
    print(f"Refunds on this reservation now: {len(after)}")
    for x in after:
        print(json.dumps({k: v for k, v in x.items() if "email" not in k.lower()})[:600])


if __name__ == "__main__":
    main()
