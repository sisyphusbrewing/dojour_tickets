"""
Sisyphus Brewing - ticket sales for one performer, Shopify + Dojour combined.

Run from GitHub: Actions -> "Show sales report" -> Run workflow, type the
performer's name (e.g. "Ryan Kahl"). Works for past shows too. The totals
appear on the run's summary page.
"""
import os
import sys
from collections import defaultdict

import requests

from fetch_tickets import get_dojour_token, extract_tickets_count, parse_show_datetime
from maintain_shows import Shopify

QUERY = (os.environ.get("SHOW_QUERY") or (sys.argv[1] if len(sys.argv) > 1 else "")).strip()
if not QUERY:
    sys.exit("Give a performer/show name, e.g. SHOW_QUERY='Ryan Kahl'.")
Q = QUERY.lower()
FEE_HANDLES = {"ticket-fee"}


def annotate(msg):
    print(f"::notice::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg)


# ---------------------------------------------------------------- Shopify
def shopify_sales():
    shop = Shopify()
    found = shop.gql("""query($q: String!) { products(first: 20, query: $q) {
        nodes { id legacyResourceId title status } } }""", {"q": QUERY})["products"]["nodes"]
    products = [p for p in found if Q in p["title"].lower()]
    rows = defaultdict(lambda: {"tickets": 0, "orders": 0, "gross": 0.0, "refunded_tickets": 0})
    for p in products:
        cursor = None
        while True:
            page = shop.gql("""query($q: String!, $c: String) {
              orders(first: 100, after: $c, query: $q) {
                nodes { cancelledAt lineItems(first: 50) { nodes {
                  product { id } variantTitle quantity currentQuantity
                  discountedTotalSet { shopMoney { amount } } } } }
                pageInfo { hasNextPage endCursor } } }""",
                            {"q": f"product_id:{p['legacyResourceId']}", "c": cursor})["orders"]
            for o in page["nodes"]:
                for li in o["lineItems"]["nodes"]:
                    if (li["product"] or {}).get("id") != p["id"]:
                        continue
                    date = (li["variantTitle"] or "").split(" / ")[0]
                    key = (p["title"], date)
                    live = 0 if o["cancelledAt"] else li["currentQuantity"]
                    rows[key]["tickets"] += live
                    rows[key]["refunded_tickets"] += li["quantity"] - live
                    rows[key]["orders"] += 1
                    if live:
                        rows[key]["gross"] += float(li["discountedTotalSet"]["shopMoney"]["amount"]) * live / li["quantity"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
    return products, rows


# ---------------------------------------------------------------- Dojour
def dojour_sales():
    token = get_dojour_token()
    s = requests.Session()
    s.cookies.set("usertoken", token, domain="dojour.us")
    s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"})

    instances = {}
    for extra in ("", "&upcoming=false", "&past=true"):
        url = f"https://dojour.us/api/event_instances/reserve_reports/?page_size=100{extra}"
        while url:
            r = s.get(url, timeout=30)
            if r.status_code != 200:
                break
            data = r.json()
            for item in (data.get("results", []) if isinstance(data, dict) else data):
                title = item.get("title") or ""
                if item.get("option_set"):
                    title = item["option_set"][0].get("title") or title
                iid = str(item.get("id") or item.get("event_instance_id") or "")
                if iid and Q in title.lower():
                    instances[iid] = (title, item.get("start_dt"))
            url = data.get("next") if isinstance(data, dict) else None

    rows = {}
    for iid, (title, start) in instances.items():
        r = s.get(f"https://dojour.us/api/event_instances/{iid}/reserve_report/", timeout=30)
        if r.status_code != 200:
            continue
        rep = r.json()
        tickets = orders = 0
        for res in rep.get("reservation_set", []):
            if not isinstance(res, dict) or res.get("is_cancelled") or res.get("waitlist") \
                    or res.get("is_on_waitlist") or res.get("checkout_complete") is False:
                continue
            tickets += extract_tickets_count(res)
            orders += 1
        dt = parse_show_datetime(start)
        rows[(title, dt.strftime("%a, %b %-d %Y • %-I:%M %p") if dt else start or "?")] = {"tickets": tickets, "orders": orders}
    return rows


def main():
    lines = [f"## Ticket sales: {QUERY}", ""]
    total = 0

    products, shop_rows = shopify_sales()
    lines += ["### Website (Shopify)", "| Show | Date | Tickets | Orders | Collected* |", "|---|---|---|---|---|"]
    for (title, date), r in sorted(shop_rows.items()):
        lines.append(f"| {title} | {date} | {r['tickets']} | {r['orders']} | ${r['gross']:,.2f} |")
        total += r["tickets"]
        if r["refunded_tickets"]:
            lines.append(f"| | ({r['refunded_tickets']} refunded/cancelled, not counted) | | | |")
    if not shop_rows:
        lines.append(f"| no orders found ({len(products)} matching product(s)) | | | | |")
    lines.append("\n*Ticket price only. Before Oct 10 the $3 fee was charged as a separate line and isn't included here.\n")

    try:
        dj_rows = dojour_sales()
        lines += ["### Dojour", "| Show | Date | Tickets | Orders |", "|---|---|---|---|"]
        for (title, date), r in sorted(dj_rows.items(), key=lambda kv: str(kv[0][1])):
            lines.append(f"| {title} | {date} | {r['tickets']} | {r['orders']} |")
            total += r["tickets"]
        if not dj_rows:
            lines.append("| none found | | | |")
        dj_total = sum(r["tickets"] for r in dj_rows.values())
    except Exception as e:
        lines.append(f"\n**Dojour couldn't be read:** {e}")
        dj_total = None

    shop_total = sum(r["tickets"] for r in shop_rows.values())
    lines += ["", f"**Total tickets: {total}** (website {shop_total}, Dojour {dj_total if dj_total is not None else 'n/a'})"]
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report + "\n")
    annotate(f"{QUERY}: {total} tickets total - website {shop_total}, Dojour {dj_total}")
    for (title, date), r in sorted(shop_rows.items()):
        annotate(f"Website | {title} | {date} | {r['tickets']} tickets, {r['orders']} orders, ${r['gross']:,.2f}")
    if dj_total is not None:
        for (title, date), r in dj_rows.items():
            annotate(f"Dojour | {title} | {date} | {r['tickets']} tickets, {r['orders']} orders")


if __name__ == "__main__":
    main()
