"""
Sisyphus - every website (Shopify) show night, kept in Supabase show_nights.

The daily sync deletes past showtimes from Shopify and archives finished
shows, so this runs first and saves each night while it's still there. It
also reads the last 75 days of orders, which keep the showtime on each line,
so nights already removed come back too. Dojour nights live in show_history;
pay_shows() (the get-paid-for-a-show form, payme/) merges the two.

    python show_nights.py      (SHOPIFY_* and SUPABASE_URL / SUPABASE_KEY set)
"""
import os
from datetime import datetime, timedelta, timezone

import requests

from maintain_shows import Shopify, fetch_active_products, date_text, is_show, SKIP_HANDLES
from show_dates import parse_show_datetime

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
DAYS_BACK = 75

ORDERS_QUERY = """
query Orders($q: String!, $cursor: String) {
  orders(first: 100, after: $cursor, query: $q) {
    nodes { createdAt lineItems(first: 50) { nodes {
      variantTitle product { title handle productType tags isGiftCard } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""


def nights_from_products(shop):
    nights = set()
    for p in fetch_active_products(shop):
        if not is_show(p):
            continue
        for v in p["variants"]["nodes"]:
            dt = parse_show_datetime(date_text(v), require_time=True)
            if dt:
                nights.add((p["title"].strip(), dt))
    return nights


def nights_from_orders(shop):
    nights, cursor = set(), None
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    while True:
        page = shop.gql(ORDERS_QUERY, {"q": f"created_at:>={since}", "cursor": cursor})["orders"]
        for o in page["nodes"]:
            bought = datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00"))
            for li in o["lineItems"]["nodes"]:
                p = li.get("product")
                if not p or p["handle"] in SKIP_HANDLES or not is_show(p):
                    continue
                # A ticket's year is the one nearest the day it was bought.
                dt = parse_show_datetime((li.get("variantTitle") or "").split(" / ")[0], now=bought, require_time=True)
                if dt:
                    nights.add((p["title"].strip(), dt))
        if not page["pageInfo"]["hasNextPage"]:
            return nights
        cursor = page["pageInfo"]["endCursor"]


def main():
    shop = Shopify()
    nights = nights_from_products(shop) | nights_from_orders(shop)
    rows = [{"title": t, "starts_at": dt.isoformat(), "source": "Shopify"} for t, dt in sorted(nights, key=lambda x: x[1])]
    print(f"{len(rows)} website show nights")
    if not rows:
        return
    r = requests.post(f"{SUPABASE_URL}/rest/v1/show_nights", json=rows, timeout=60,
                      params={"on_conflict": "title,starts_at"},
                      headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                               "Prefer": "resolution=merge-duplicates,return=minimal"})
    r.raise_for_status()
    print("Saved to show_nights")


if __name__ == "__main__":
    main()
