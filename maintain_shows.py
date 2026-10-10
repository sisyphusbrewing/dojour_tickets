"""
Sisyphus Brewing - daily show maintenance.

Runs after the ticket sync. For every ACTIVE show in Shopify:
  * every showtime is over        -> the product is archived
  * some showtimes are over       -> just those dates are removed
                                     (past orders are not affected)
Then re-sorts the Comedy Tickets & Events collection by next show date.

Left alone on purpose:
  * the Ticket Fee and Private Event Deposit products
  * anything tagged "no-auto-archive" or that looks like a class/workshop
  * any show with a date the script can't read (it is listed in the log)

Safety: DRY_RUN=1 prints what would happen without changing anything, and
the run stops if it would archive an unusually large number of shows at once
(override with FORCE=1 after checking the log).
"""
import os
import re
import sys
from datetime import datetime, timedelta

import requests

from show_dates import parse_show_datetime, CENTRAL_TZ

API_VERSION = "2025-07"
COLLECTION_HANDLE = "comedy-and-events"
GRACE_HOURS = 12                      # same grace window as the door list
SKIP_HANDLES = {"ticket-fee", "deposit"}
CLASS_PATTERN = re.compile(r"\b(class|classes|workshop|course)\b", re.IGNORECASE)
MAX_ARCHIVE_PER_RUN = int(os.environ.get("MAX_ARCHIVE_PER_RUN", "8"))

DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
FORCE = os.environ.get("FORCE", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Shopify connection (same credentials as the show builder)
# ---------------------------------------------------------------------------
def store_domain():
    store = os.environ.get("SHOPIFY_STORE", "").replace("https://", "").strip().rstrip("/")
    if store and not store.endswith(".myshopify.com"):
        store = f"{store}.myshopify.com"
    if not store:
        sys.exit("Missing SHOPIFY_STORE.")
    return store


def access_token(store):
    direct = os.environ.get("SHOPIFY_ACCESS_TOKEN") or os.environ.get("SHOPIFY_ADMIN_API_TOKEN")
    if direct:
        return direct.strip()
    cid = os.environ.get("SHOPIFY_CLIENT_ID")
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Missing SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET.")
    resp = requests.post(f"https://{store}/admin/oauth/access_token",
                         json={"client_id": cid, "client_secret": secret,
                               "grant_type": "client_credentials"}, timeout=20)
    resp.raise_for_status()
    return resp.json()["access_token"]


class Shopify:
    def __init__(self):
        self.store = store_domain()
        self.headers = {"X-Shopify-Access-Token": access_token(self.store),
                        "Content-Type": "application/json"}

    def gql(self, query, variables=None):
        resp = requests.post(f"https://{self.store}/admin/api/{API_VERSION}/graphql.json",
                             headers=self.headers, json={"query": query, "variables": variables or {}},
                             timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"Shopify error: {data['errors']}")
        return data["data"]


# ---------------------------------------------------------------------------
# Reading shows
# ---------------------------------------------------------------------------
PRODUCTS_QUERY = """
query ActiveShows($cursor: String) {
  products(first: 50, after: $cursor, query: "status:active") {
    nodes {
      id title handle productType tags isGiftCard
      variants(first: 100) { nodes { id title selectedOptions { name value } } }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""


def fetch_active_products(shop):
    products, cursor = [], None
    while True:
        page = shop.gql(PRODUCTS_QUERY, {"cursor": cursor})["products"]
        products.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return products
        cursor = page["pageInfo"]["endCursor"]


def date_text(variant):
    """The showtime part of a variant ("Sat, Oct 17 • 7:00 PM"), not the ticket type."""
    for opt in variant.get("selectedOptions") or []:
        if opt["name"].strip().lower() in ("date & time", "date", "showtime", "date and time"):
            return opt["value"]
    return variant["title"]


def skip_reason(product):
    tags = [t.lower() for t in product.get("tags") or []]
    if product.get("isGiftCard"):
        return "gift card"
    if product["handle"] in SKIP_HANDLES:
        return "fee/deposit product"
    if "no-auto-archive" in tags:
        return "tagged no-auto-archive"
    if (product.get("productType") or "").lower() == "class" or CLASS_PATTERN.search(product["title"]):
        return "class/workshop"
    return None


def plan(products, now):
    """Decide what to do with each product. Pure function - easy to test."""
    cutoff = now - timedelta(hours=GRACE_HOURS)
    actions = {"archive": [], "remove_dates": [], "unreadable": [], "skipped": []}

    for p in products:
        reason = skip_reason(p)
        if reason:
            actions["skipped"].append((p, reason))
            continue

        variants = p["variants"]["nodes"]
        dated = [(v, parse_show_datetime(date_text(v), now=now, require_time=True)) for v in variants]
        unreadable = [v for v, d in dated if d is None]
        if unreadable:
            # Never touch a show we can't fully read - a person should look at it.
            actions["unreadable"].append((p, [v["title"] for v in unreadable]))
            continue

        past = [(v, d) for v, d in dated if d < cutoff]
        if not past:
            continue
        if len(past) == len(variants):
            actions["archive"].append((p, max(d for _, d in dated)))
        else:
            actions["remove_dates"].append((p, past))
    return actions


# ---------------------------------------------------------------------------
# Making changes
# ---------------------------------------------------------------------------
def archive_product(shop, product):
    res = shop.gql("""
      mutation Archive($product: ProductUpdateInput!) {
        productUpdate(product: $product) { product { id status } userErrors { field message } }
      }""", {"product": {"id": product["id"], "status": "ARCHIVED"}})["productUpdate"]
    if res["userErrors"]:
        raise RuntimeError(res["userErrors"])


def remove_variants(shop, product, variant_ids):
    res = shop.gql("""
      mutation DeletePast($productId: ID!, $variantsIds: [ID!]!) {
        productVariantsBulkDelete(productId: $productId, variantsIds: $variantsIds) {
          product { id } userErrors { field message }
        }
      }""", {"productId": product["id"], "variantsIds": variant_ids})["productVariantsBulkDelete"]
    if res["userErrors"]:
        raise RuntimeError(res["userErrors"])


COLLECTION_QUERY = """
query Coll($handle: String!, $cursor: String) {
  collectionByIdentifier(identifier: { handle: $handle }) {
    id sortOrder
    products(first: 250, after: $cursor) {
      nodes { id title variants(first: 100) { nodes { title } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""


def sort_key(product, now):
    """Next upcoming showtime; classes and undated items go to the end."""
    dates = [d for d in (parse_show_datetime(v["title"], now=now) for v in product["variants"]["nodes"]) if d]
    upcoming = [d for d in dates if d >= now - timedelta(hours=GRACE_HOURS)]
    if upcoming:
        return (0, min(upcoming), product["title"])
    return (1, datetime.max.replace(tzinfo=CENTRAL_TZ), product["title"])


def sort_collection(shop, now):
    coll, products, cursor = None, [], None
    while True:
        coll = shop.gql(COLLECTION_QUERY, {"handle": COLLECTION_HANDLE, "cursor": cursor})["collectionByIdentifier"]
        if not coll:
            print(f"Collection '{COLLECTION_HANDLE}' not found - skipping sort.")
            return
        products.extend(coll["products"]["nodes"])
        if not coll["products"]["pageInfo"]["hasNextPage"]:
            break
        cursor = coll["products"]["pageInfo"]["endCursor"]

    current = [p["id"] for p in products]
    target = [p["id"] for p in sorted(products, key=lambda p: sort_key(p, now))]
    if current == target:
        print("Show listing is already in date order.")
        return

    moves, working = [], list(current)
    for i, pid in enumerate(target):
        if working.index(pid) != i:
            moves.append({"id": pid, "newPosition": str(i)})
            working.remove(pid)
            working.insert(i, pid)

    print(f"Re-sorting show listing ({len(moves)} move(s)).")
    if DRY_RUN:
        return
    if coll["sortOrder"] != "MANUAL":
        shop.gql("""mutation SetManual($input: CollectionInput!) {
                      collectionUpdate(input: $input) { collection { id } userErrors { field message } } }""",
                 {"input": {"id": coll["id"], "sortOrder": "MANUAL"}})
    for i in range(0, len(moves), 250):
        res = shop.gql("""mutation Reorder($id: ID!, $moves: [MoveInput!]!) {
                            collectionReorderProducts(id: $id, moves: $moves) { job { id } userErrors { field message } } }""",
                       {"id": coll["id"], "moves": moves[i:i + 250]})["collectionReorderProducts"]
        if res["userErrors"]:
            print(f"Sort warning: {res['userErrors']}")


# ---------------------------------------------------------------------------
def main():
    now = datetime.now(CENTRAL_TZ)
    print("=" * 60)
    print(f"SISYPHUS SHOW MAINTENANCE  {now:%a %b %-d, %Y %-I:%M %p}" + ("  [DRY RUN]" if DRY_RUN else ""))
    print("=" * 60)

    shop = Shopify()
    products = fetch_active_products(shop)
    actions = plan(products, now)
    print(f"Checked {len(products)} active products.")

    for p, reason in actions["skipped"]:
        print(f"  - skip  {p['title']}  ({reason})")
    for p, titles in actions["unreadable"]:
        print(f"  ! CHECK {p['title']}: couldn't read a date in {titles} - left alone")

    if len(actions["archive"]) > MAX_ARCHIVE_PER_RUN and not FORCE:
        print(f"STOPPED: would archive {len(actions['archive'])} shows at once (limit {MAX_ARCHIVE_PER_RUN}).")
        for p, last in actions["archive"]:
            print(f"    {p['title']} (last show {last:%b %-d, %Y})")
        print("If this is correct, re-run with FORCE=1.")
        sys.exit(1)

    for p, last in actions["archive"]:
        print(f"  ✓ archive  {p['title']}  (last show {last:%a %b %-d, %Y})")
        if not DRY_RUN:
            archive_product(shop, p)

    for p, past in actions["remove_dates"]:
        names = ", ".join(v["title"] for v, _ in past)
        print(f"  ✓ remove past date(s) from {p['title']}: {names}")
        if not DRY_RUN:
            remove_variants(shop, p, [v["id"] for v, _ in past])

    if not actions["archive"] and not actions["remove_dates"]:
        print("No past shows to clean up.")

    sort_collection(shop, now)
    print("Done.")


if __name__ == "__main__":
    main()
