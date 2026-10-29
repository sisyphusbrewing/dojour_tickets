"""
Sisyphus - swap a customer's website tickets to another night (or show).

A customer who bought the wrong night goes to sisyphusbrewing.com/pages/exchange
(exchange/index.html), finds their order with its number + email and picks a new
showtime. The ticket-exchange edge function saves the request in Supabase
`ticket_exchanges` and starts the "Ticket exchange" action, which runs:

    python exchange_ticket.py <exchange id>

That edits the Shopify order in place (Shopify's own order editing):
  * the old tickets come off the order and their seats go back on sale
  * the new showtime's tickets go on, which takes those seats
  * the door list (Supabase `tickets`) moves them to the new night
  * the customer gets a short confirmation email from the box office

Only to another showtime of the same Shopify product, the same show's other
nights and ticket types (Sam, Oct 29 2026: "they can only move amongst the
same product").

Money (Sam: no refunds unless a show is cancelled or rescheduled):
  * same price            nothing changes
  * new tickets cheaper   no refund; an untouchable "Exchange credit" line on
                          the order keeps the total the same
  * new tickets pricier   refused (Sam, Oct 28 2026); the page says to email
                          the box office
  * a promo-code discount carries over at the same percentage

    python exchange_ticket.py --refresh

rewrites `exchange_showtimes`, the list of upcoming showtimes (price, seats
left) the page offers. The sync runs it every 4 hours and every swap runs it
again.

Needs SHOPIFY_* (with the write_order_edits scope), SUPABASE_URL / SUPABASE_KEY
(service key) and the box office SMTP secrets. DRY_RUN=1 checks everything and
changes nothing.
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import formataddr

import requests

from fetch_tickets import clean_show_title, format_show_date
from maintain_shows import Shopify, fetch_active_products, date_text, is_show, skip_reason
from show_dates import parse_show_datetime, CENTRAL_TZ

# Swaps close this long before the original show, and the new show must be at
# least this far off too. The edge function uses the same number.
CUTOFF_HOURS = 2

CREDIT_TITLE = "Exchange credit (no refund)"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or ""
SB = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}


COMMITTED = False   # set once Shopify has the edit, so a later error isn't reported as "nothing changed"


class Refused(Exception):
    """A swap we won't do. The message is shown to the customer."""


def num(gid):
    return int(str(gid).rsplit("/", 1)[-1])


def money(x):
    return f"${x:,.2f}".replace(".00", "")


def sb(method, path, **kw):
    resp = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers={**SB, **kw.pop("headers", {})},
                            timeout=30, **kw)
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase {method} {path}: {resp.status_code} {resp.text}")
    return resp.json() if resp.text else None


# ---------------------------------------------------------------------------
# Showtimes the page can offer
# ---------------------------------------------------------------------------
def ticket_type_of(variant):
    for opt in variant.get("selectedOptions") or []:
        if opt["name"].strip().lower() not in ("date & time", "date", "showtime", "date and time"):
            return opt["value"]
    return None


def refresh_showtimes(shop):
    now = datetime.now(timezone.utc)
    rows = []
    for p in fetch_active_products(shop):
        if not is_show(p) or skip_reason(p):
            continue
        for v in p["variants"]["nodes"]:
            dt = parse_show_datetime(date_text(v), require_time=True)
            if not dt or dt <= now:
                continue
            rows.append({
                "variant_id": num(v["id"]), "product_id": num(p["id"]),
                "show_title": clean_show_title(p["title"]) or p["title"],
                "date_text": format_show_date(dt), "ticket_type": ticket_type_of(v),
                "starts_at": dt.isoformat(), "price": float(v["price"]),
                "seats_left": max(int(v.get("inventoryQuantity") or 0), 0),
                "updated_at": now.isoformat(),
            })
    if DRY_RUN:
        print(f"DRY_RUN: would save {len(rows)} showtimes.")
        return
    if rows:
        sb("POST", "exchange_showtimes?on_conflict=variant_id", json=rows,
           headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
    keep = ",".join(str(r["variant_id"]) for r in rows) or "0"
    sb("DELETE", f"exchange_showtimes?variant_id=not.in.({keep})", headers={"Prefer": "return=minimal"})
    print(f"Saved {len(rows)} upcoming showtimes for exchanges.")


# ---------------------------------------------------------------------------
# Shopify reads and the order edit
# ---------------------------------------------------------------------------
ORDER_QUERY = """
query Order($q: String!) {
  orders(first: 1, query: $q) { nodes {
    id name email cancelledAt customer { email firstName }
    lineItems(first: 100) { nodes {
      id title variantTitle currentQuantity
      variant { id product { id } }
      originalUnitPriceSet { shopMoney { amount } }
      discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount } }
    } }
  } }
}"""

VARIANT_QUERY = """
query Variant($id: ID!) {
  productVariant(id: $id) {
    id title price inventoryQuantity selectedOptions { name value }
    inventoryItem { tracked }
    product { id title status handle tags productType isGiftCard }
  }
}"""

BEGIN = """mutation($id: ID!) { orderEditBegin(id: $id) {
  calculatedOrder { id } userErrors { field message } } }"""
SET_QTY = """mutation($id: ID!, $line: ID!, $qty: Int!) {
  orderEditSetQuantity(id: $id, lineItemId: $line, quantity: $qty, restock: true) { userErrors { field message } } }"""
ADD_VARIANT = """mutation($id: ID!, $variant: ID!, $qty: Int!) {
  orderEditAddVariant(id: $id, variantId: $variant, quantity: $qty, allowDuplicates: true) {
    calculatedLineItem { id } userErrors { field message } } }"""
ADD_DISCOUNT = """mutation($id: ID!, $line: ID!, $discount: OrderEditAppliedDiscountInput!) {
  orderEditAddLineItemDiscount(id: $id, lineItemId: $line, discount: $discount) { userErrors { field message } } }"""
ADD_CUSTOM = """mutation($id: ID!, $title: String!, $price: MoneyInput!) {
  orderEditAddCustomItem(id: $id, title: $title, quantity: 1, price: $price, taxable: true, requiresShipping: false) {
    userErrors { field message } } }"""
COMMIT = """mutation($id: ID!, $note: String) {
  orderEditCommit(id: $id, notifyCustomer: false, staffNote: $note) { order { id } userErrors { field message } } }"""


def run(shop, query, variables, field):
    data = shop.gql(query, variables)[field]
    errors = data.get("userErrors") or []
    if errors:
        msg = "; ".join(e["message"] for e in errors)
        raise RuntimeError(f"{field}: {msg}")
    return data


def find_order(shop, order_name, email):
    order = (shop.gql(ORDER_QUERY, {"q": f"name:{order_name}"})["orders"]["nodes"] or [None])[0]
    if not order or order["name"] != order_name:
        raise Refused("We couldn't find that order.")
    emails = {(order.get("email") or "").lower(), ((order.get("customer") or {}).get("email") or "").lower()}
    if email.lower() not in emails:
        raise Refused("That email doesn't match the order.")
    if order.get("cancelledAt"):
        raise Refused("That order was cancelled.")
    return order


def exchange(shop, ex):
    order = find_order(shop, ex["order_name"], ex["email"])
    old_line_id = int(ex["from_unique_id"].rsplit("_", 1)[-1])
    line = next((li for li in order["lineItems"]["nodes"] if num(li["id"]) == old_line_id), None)
    if not line or (line.get("currentQuantity") or 0) <= 0:
        raise Refused("Those tickets aren't on the order anymore. Maybe they were already swapped.")
    have = int(line["currentQuantity"])
    qty = int(ex.get("tickets") or have)
    if not 0 < qty <= have:
        raise Refused(f"That order has {have} of those tickets.")

    cutoff = datetime.now(timezone.utc) + timedelta(hours=CUTOFF_HOURS)
    old_dt = parse_show_datetime(line.get("variantTitle") or "", require_time=True)
    if not old_dt or old_dt <= cutoff:
        raise Refused(f"Swaps close {CUTOFF_HOURS} hours before the show.")

    door = sb("GET", f"tickets?unique_id=eq.{ex['from_unique_id']}&select=*")
    door = door[0] if door else None
    if door and (door.get("checked_in_count") or 0) > 0:
        raise Refused("Those tickets were already checked in at the door.")

    variant = shop.gql(VARIANT_QUERY, {"id": f"gid://shopify/ProductVariant/{ex['to_variant_id']}"})["productVariant"]
    if not variant or variant["product"]["status"] != "ACTIVE" or skip_reason(variant["product"]):
        raise Refused("That showtime isn't on sale.")
    if line.get("variant") and num(line["variant"]["id"]) == num(variant["id"]):
        raise Refused("Those are the tickets you already have.")
    new_dt = parse_show_datetime(date_text(variant), require_time=True)
    if not new_dt or new_dt <= cutoff:
        raise Refused("That showtime is too soon or already happened.")
    if not line.get("variant") or line["variant"]["product"]["id"] != variant["product"]["id"]:
        raise Refused("Tickets can only move to another night of the same show.")
    if (variant.get("inventoryItem") or {}).get("tracked", True) and (variant.get("inventoryQuantity") or 0) < qty:
        raise Refused("That showtime doesn't have enough seats left.")

    # What they paid per ticket vs what the new ones cost, keeping any promo percentage.
    original = float(line["originalUnitPriceSet"]["shopMoney"]["amount"])
    paid = float(line["discountedUnitPriceAfterAllDiscountsSet"]["shopMoney"]["amount"])
    ratio = paid / original if original > 0 else 1.0
    new_list = float(variant["price"])
    new_each = round(new_list * ratio, 2)
    diff = round((new_each - paid) * qty, 2)       # - they don't get back; + is refused
    if diff > 0.009:
        raise Refused(f"Those cost {money(diff)} more. Email the box office and we'll sort it out.")

    old_label = f"{clean_show_title(line['title'])}, {format_show_date(old_dt)}"
    new_title = clean_show_title(variant["product"]["title"]) or variant["product"]["title"]
    new_label = f"{new_title}, {format_show_date(new_dt)}"
    ttype = ticket_type_of(variant)
    print(f"{order['name']}: {qty} x {old_label} ({line['variantTitle']}) -> {new_label} / {ttype}; "
          f"paid {paid:.2f} each, new {new_each:.2f} each, difference {diff:+.2f}")
    if DRY_RUN:
        # Opening an edit and never committing changes nothing, and proves the app may edit orders.
        run(shop, BEGIN, {"id": order["id"]}, "orderEditBegin")
        print("DRY_RUN: checks passed and order editing is allowed; order not changed.")
        return {"diff": diff, "qty": qty, "old_label": old_label, "new_label": new_label}

    calc = run(shop, BEGIN, {"id": order["id"]}, "orderEditBegin")["calculatedOrder"]["id"]
    run(shop, SET_QTY, {"id": calc, "line": f"gid://shopify/CalculatedLineItem/{old_line_id}", "qty": have - qty},
        "orderEditSetQuantity")
    added = run(shop, ADD_VARIANT, {"id": calc, "variant": variant["id"], "qty": qty}, "orderEditAddVariant")
    if ratio < 0.995:
        run(shop, ADD_DISCOUNT, {"id": calc, "line": added["calculatedLineItem"]["id"], "discount": {
            "percentValue": round((1 - ratio) * 100, 2), "description": "Original discount"}}, "orderEditAddLineItemDiscount")
    if diff < -0.009:
        run(shop, ADD_CUSTOM, {"id": calc, "title": CREDIT_TITLE,
                               "price": {"amount": f"{-diff:.2f}", "currencyCode": "USD"}}, "orderEditAddCustomItem")
    run(shop, COMMIT, {"id": calc, "note": f"Self-serve exchange: {qty} x {old_label} -> {new_label}"}, "orderEditCommit")
    global COMMITTED
    COMMITTED = True
    print("Order edited.")

    after = find_order(shop, order["name"], ex["email"])
    new_line = max((li for li in after["lineItems"]["nodes"]
                    if li.get("variant") and num(li["variant"]["id"]) == num(variant["id"]) and li["currentQuantity"] > 0),
                   key=lambda li: num(li["id"]))

    # Door list: the new night gets a row, the old row shrinks or goes.
    order_num = num(order["id"])
    customer = order.get("customer") or {}
    sb("POST", "tickets?on_conflict=unique_id", headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=[{
        "unique_id": f"shopify_{order_num}_{num(new_line['id'])}",
        "show_date": format_show_date(new_dt), "show_title": new_title,
        "guest_name": (door or {}).get("guest_name") or customer.get("firstName") or "Guest",
        "email": (door or {}).get("email") or ex["email"],
        "tickets": qty, "ticket_type": ttype, "source": "Website",
        "order_name": order["name"], "variant_id": num(variant["id"]),
    }])
    if have - qty > 0:
        sb("PATCH", f"tickets?unique_id=eq.{ex['from_unique_id']}", json={"tickets": have - qty},
           headers={"Prefer": "return=minimal"})
    else:
        sb("DELETE", f"tickets?unique_id=eq.{ex['from_unique_id']}", headers={"Prefer": "return=minimal"})
    print("Door list updated.")
    return {"diff": diff, "qty": qty, "old_label": old_label, "new_label": new_label,
            "first_name": customer.get("firstName") or ""}


# ---------------------------------------------------------------------------
# Confirmation email
# ---------------------------------------------------------------------------
def send_confirmation(to, result, order_name):
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
    sender = (os.environ.get("FROM_EMAIL") or user).strip()
    if not user or not pw:
        print("No SMTP secrets; confirmation email skipped.")
        return
    tickets = "ticket" if result["qty"] == 1 else "tickets"
    lines = [f"Hi{' ' + result['first_name'] if result.get('first_name') else ''},", "",
             f"Done. Your {result['qty']} {tickets} moved from {result['old_label']} to {result['new_label']}.",
             "Same name at the door, new night.", ""]
    if result["diff"] < -0.009:
        lines += ["The new ones were cheaper. We don't do refunds on swaps, so call the difference a tip "
                  "for the comedians. They get 100% of the door anyway.", ""]
    lines += [f"Order {order_name}. Questions? Just reply.", "", "See you there,", "Sisyphus"]
    msg = MIMEText("\n".join(lines) + "\n", "plain", "utf-8")
    msg["Subject"] = f"Your tickets moved to {result['new_label']}"
    msg["From"] = formataddr((os.environ.get("FROM_NAME") or "Sisyphus Box Office", sender))
    msg["To"] = to
    msg["Reply-To"] = sender
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(user, pw)
        server.sendmail(sender, [to, sender], msg.as_string())
    print(f"Confirmation sent to {to} (copy to the box office).")


def finish(ex_id, status, message):
    print(f"{status}: {message}")
    if not DRY_RUN:
        sb("PATCH", f"ticket_exchanges?id=eq.{ex_id}", headers={"Prefer": "return=minimal"},
           json={"status": status, "message": message, "finished_at": datetime.now(timezone.utc).isoformat()})


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY.")
    shop = Shopify()
    if "--refresh" in sys.argv:
        refresh_showtimes(shop)
        return
    ex_id = next((a for a in sys.argv[1:] if not a.startswith("-")), "") or os.environ.get("EXCHANGE_ID", "")
    rows = sb("GET", f"ticket_exchanges?id=eq.{ex_id}&select=*") if ex_id else []
    if not rows:
        sys.exit(f"No exchange {ex_id!r}.")
    ex = rows[0]
    if ex["status"] != "queued" and not DRY_RUN:
        sys.exit(f"Exchange {ex_id} is already {ex['status']}.")
    if not DRY_RUN:
        sb("PATCH", f"ticket_exchanges?id=eq.{ex_id}", json={"status": "working"}, headers={"Prefer": "return=minimal"})

    try:
        result = exchange(shop, ex)
    except Refused as e:
        finish(ex_id, "failed", str(e))
        return
    except Exception as e:
        if COMMITTED:
            finish(ex_id, "done", "Your order is changed. Our door list may take a few hours to catch up; "
                                  "you're covered either way.")
        else:
            finish(ex_id, "failed", "Something went wrong on our end. Nothing was changed. "
                                    "Email the box office and we'll do it by hand.")
        raise SystemExit(f"Exchange failed: {e}")
    if DRY_RUN:
        return

    when = result["new_label"]
    finish(ex_id, "done", f"Done. You're on the list for {when}.")
    try:
        send_confirmation(ex["email"], result, ex["order_name"])
    except Exception as e:
        print(f"::warning::Confirmation email failed: {e}")
    try:
        refresh_showtimes(shop)
    except Exception as e:
        print(f"::warning::Showtime refresh failed: {e}")


if __name__ == "__main__":
    main()
