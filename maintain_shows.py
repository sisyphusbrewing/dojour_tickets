"""
Sisyphus Brewing - daily show maintenance.

Runs after the ticket sync. For every ACTIVE show in Shopify:
  * every showtime is over        -> the product is archived
  * some showtimes are over       -> just those dates are removed
                                     (past orders are not affected)
Recurring shows (tagged e.g. "recurring: 1st Wed 7:00 PM", see
recurring_events.py) get their next dates added first, so they never run out.
Then re-sorts the Comedy Tickets & Events collection by next show date, and
saves each showtime's exact start (custom.show_start, e.g.
"2026-11-20T20:00:00-06:00") so the theme can publish Google event listings.

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
import recurring_events

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
      options { name }
      variants(first: 100) {
        nodes {
          id title price inventoryQuantity selectedOptions { name value }
          metafield(namespace: "custom", key: "show_start") { value }
        }
      }
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
        if len(past) == len(variants) and recurring_events.has_recurring_tag(p.get("tags")):
            # New dates couldn't be added (warned above); never archive a recurring show.
            actions["unreadable"].append((p, ["no upcoming dates"]))
        elif len(past) == len(variants):
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


def start_time_updates(products, now):
    """Showtimes whose saved start time is missing or out of date. Pure - easy to test."""
    updates = []
    for p in products:
        if skip_reason(p):
            continue
        for v in p["variants"]["nodes"]:
            start = parse_show_datetime(date_text(v), now=now, require_time=True)
            if not start:
                continue
            value = start.isoformat()            # e.g. 2026-11-20T20:00:00-06:00
            current = (v.get("metafield") or {}).get("value")
            if current != value:
                updates.append({"ownerId": v["id"], "namespace": "custom", "key": "show_start",
                                "type": "single_line_text_field", "value": value})
    return updates


def save_start_times(shop, updates):
    for i in range(0, len(updates), 25):
        res = shop.gql("""
          mutation SetStarts($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) { metafields { id } userErrors { field message } }
          }""", {"metafields": updates[i:i + 25]})["metafieldsSet"]
        if res["userErrors"]:
            raise RuntimeError(res["userErrors"])


COLLECTION_ID = os.environ.get("SHOPIFY_COLLECTION_ID", "472787812387").strip()
_COLL_FIELDS = """
    id sortOrder
    products(first: 250, after: $cursor) {
      nodes { id title variants(first: 100) { nodes { title } } }
      pageInfo { hasNextPage endCursor }
    }"""
COLLECTION_BY_HANDLE = """
query Coll($handle: String!, $cursor: String) {
  collection: collectionByIdentifier(identifier: { handle: $handle }) {%s}
}""" % _COLL_FIELDS
COLLECTION_BY_ID = """
query CollById($id: ID!, $cursor: String) {
  collection(id: $id) {%s}
}""" % _COLL_FIELDS


# Anything tagged or typed like one of these is a show and belongs on the
# Comedy and Events page, whether the builder made it or it was made by hand.
SHOW_TAGS = {"comedy", "live event", "door-tickets", "comedy-ticket", "class", "free event", "ticket"}
SHOW_TYPES = {"tickets", "comedy ticket", "comedy", "free event", "class", "event"}
JOIN_COLLECTION = """
mutation Join($id: ID!, $coll: [ID!]) {
  productUpdate(product: { id: $id, collectionsToJoin: $coll }) { userErrors { field message } }
}"""


def is_show(product):
    tags = {t.lower() for t in product.get("tags") or []}
    if product.get("isGiftCard") or product["handle"] in SKIP_HANDLES or "no-collection" in tags:
        return False
    return bool(tags & SHOW_TAGS) or (product.get("productType") or "").lower() in SHOW_TYPES


def add_shows_to_collection(shop, products):
    """Put every active show in the Comedy and Events collection.

    The app can't read the collection (it sees 0 collections), so it can't tell
    who's already in. Joining is a no-op for products already there, so just
    join every show each run.
    """
    shows = [p for p in products if is_show(p)]
    if DRY_RUN:
        print(f"Would make sure {len(shows)} show(s) are in the Comedy and Events collection.")
        return
    coll = [f"gid://shopify/Collection/{COLLECTION_ID}"]
    failed = []
    for p in shows:
        try:
            errors = shop.gql(JOIN_COLLECTION, {"id": p["id"], "coll": coll})["productUpdate"]["userErrors"]
        except Exception as e:
            errors = [str(e)[:200]]
        if errors:
            failed.append(f"{p['title']}: {errors}")
    print(f"Comedy and Events collection: {len(shows) - len(failed)} show(s) in.")
    for f in failed:
        annotate("warning", f"Couldn't add to Comedy and Events - {f}")


def sort_key(product, now):
    """Next upcoming showtime; classes and undated items go to the end."""
    dates = [d for d in (parse_show_datetime(v["title"], now=now) for v in product["variants"]["nodes"]) if d]
    upcoming = [d for d in dates if d >= now - timedelta(hours=GRACE_HOURS)]
    if upcoming:
        return (0, min(upcoming), product["title"])
    return (1, datetime.max.replace(tzinfo=CENTRAL_TZ), product["title"])


def annotate(level, msg):
    """Print a GitHub Actions annotation (shows on the run summary page)."""
    print(f"::{level}::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"[{level}] {msg}")


def load_collection(shop):
    """Find the show collection by handle, then by id. Returns (collection, products)."""
    lookups = [("handle", COLLECTION_BY_HANDLE, {"handle": COLLECTION_HANDLE})]
    if COLLECTION_ID:
        lookups.append(("id", COLLECTION_BY_ID, {"id": f"gid://shopify/Collection/{COLLECTION_ID}"}))
    notes = []
    for how, query, base_vars in lookups:
        products, cursor, coll = [], None, None
        try:
            while True:
                coll = shop.gql(query, {**base_vars, "cursor": cursor})["collection"]
                if not coll:
                    break
                products.extend(coll["products"]["nodes"])
                if not coll["products"]["pageInfo"]["hasNextPage"]:
                    break
                cursor = coll["products"]["pageInfo"]["endCursor"]
        except Exception as e:
            notes.append(f"by {how}: error {str(e)[:200]}")
            continue
        if coll:
            return coll, products
        notes.append(f"by {how}: not visible")
    # Extra clues for why the app can't see it.
    try:
        count = shop.gql("{ collectionsCount { count } }")["collectionsCount"]["count"]
        notes.append(f"app sees {count} collection(s)")
    except Exception as e:
        notes.append(f"collectionsCount error {str(e)[:150]}")
    try:
        r = requests.get(f"https://{shop.store}/admin/api/{API_VERSION}/collections/{COLLECTION_ID}.json",
                         headers=shop.headers, timeout=20)
        notes.append(f"REST collection lookup HTTP {r.status_code}")
    except Exception as e:
        notes.append(f"REST error {e}")
    try:
        r = requests.get(f"https://{shop.store}/admin/oauth/access_scopes.json", headers=shop.headers, timeout=20)
        if r.ok:
            notes.append("scopes: " + ",".join(s["handle"] for s in r.json().get("access_scopes", [])))
    except Exception:
        pass
    annotate("notice", f"Collection order not changed (the website theme sorts shows by date itself) - collection '{COLLECTION_HANDLE}' not found. " + "; ".join(notes))
    return None, []


def sort_collection(shop, now):
    coll, products = load_collection(shop)
    if not coll:
        return

    current = [p["id"] for p in products]
    target = [p["id"] for p in sorted(products, key=lambda p: sort_key(p, now))]
    if current == target and coll["sortOrder"] == "MANUAL":
        annotate("notice", f"Show listing already in date order ({len(products)} products).")
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
        res = shop.gql("""mutation SetManual($input: CollectionInput!) {
                      collectionUpdate(input: $input) { collection { id } userErrors { field message } } }""",
                       {"input": {"id": coll["id"], "sortOrder": "MANUAL"}})["collectionUpdate"]
        if res["userErrors"]:
            annotate("warning", f"Couldn't switch collection to manual sort: {res['userErrors']}")
    errors = []
    for i in range(0, len(moves), 250):
        res = shop.gql("""mutation Reorder($id: ID!, $moves: [MoveInput!]!) {
                            collectionReorderProducts(id: $id, moves: $moves) { job { id } userErrors { field message } } }""",
                       {"id": coll["id"], "moves": moves[i:i + 250]})["collectionReorderProducts"]
        errors += res["userErrors"]
    if errors:
        annotate("warning", f"Sort errors: {errors}")
    else:
        annotate("notice", f"Show listing re-sorted by date ({len(moves)} move(s), {len(products)} products).")


# ---------------------------------------------------------------------------
def main():
    now = datetime.now(CENTRAL_TZ)
    print("=" * 60)
    print(f"SISYPHUS SHOW MAINTENANCE  {now:%a %b %-d, %Y %-I:%M %p}" + ("  [DRY RUN]" if DRY_RUN else ""))
    print("=" * 60)

    shop = Shopify()
    products = fetch_active_products(shop)

    additions, problems = recurring_events.plan_additions(products, now)
    for p, reason in problems:
        annotate("warning", f"Recurring show {p['title']}: {reason} - left alone")
    if additions:
        location_id = None if DRY_RUN else recurring_events.first_location_id(shop)
        for p, option, price, capacity, dates in additions:
            names = ", ".join(recurring_events.variant_name(d) for d in dates)
            print(f"  + add date(s) to {p['title']}: {names}")
            if not DRY_RUN:
                recurring_events.add_dates(shop, location_id, p, option, price, capacity, dates)
        if not DRY_RUN:
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

    updates = start_time_updates(fetch_active_products(shop) if not DRY_RUN else products, now)
    if updates:
        print(f"Saving exact start times for {len(updates)} showtime(s) (used for Google event listings).")
        if not DRY_RUN:
            save_start_times(shop, updates)

    current = fetch_active_products(shop) if not DRY_RUN else products
    for p, add, remove in recurring_events.plan_label_updates(current, now):
        print(f"  ~ card date for {p['title']}: {', '.join(add)}")
        if not DRY_RUN:
            recurring_events.apply_label_update(shop, p, add, remove)

    add_shows_to_collection(shop, current)
    sort_collection(shop, now)
    print("Done.")


if __name__ == "__main__":
    main()
