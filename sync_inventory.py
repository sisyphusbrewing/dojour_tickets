"""
Sisyphus - mirror Dojour (and comp) ticket sales into Shopify inventory.

Tickets for the same show are sold in two places that don't talk to each
other: Dojour and the website (Shopify). Shopify only counts its own orders,
so its "seats left" drifts upward by however many Dojour sells, and a show can
oversell. This script runs after fetch_tickets.py (which writes every ticket
from both sources into the Supabase `tickets` table) and takes the
non-website tickets back out of the matching Shopify showtime.

How it stays honest across runs:
  * each showtime's General Admission variant carries a metafield
    custom.external_tickets = how many outside tickets have already been
    taken out of its Shopify count
  * every run compares that number with what Supabase says now and adjusts
    Shopify by the difference only (more Dojour sales -> fewer seats on the
    website; a Dojour refund -> seats come back)
  * a variant seen for the first time is NOT reduced. Its current Shopify
    count is trusted as already correct (shows that were balanced by hand),
    and today's outside count becomes the baseline. Only sales after that
    move the website count.

Dojour "Hold" reservations (no email, name contains "hold") are the venue
blocking its own seats, not sales, so they are ignored.

Safety: DRY_RUN=1 prints what would happen without changing anything.
"""
import os
import re
import sys
from collections import defaultdict

import requests

from show_dates import parse_show_datetime
from maintain_shows import Shopify, skip_reason

NAMESPACE, KEY = "custom", "external_tickets"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Supabase: outside tickets per show + showtime
# ---------------------------------------------------------------------------
def fetch_external_rows():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY.")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, offset, page = [], 0, 1000
    while True:
        resp = requests.get(
            f"{url}/rest/v1/tickets",
            params={"select": "show_title,show_date,tickets,source,guest_name,email",
                    "source": "neq.Website", "offset": offset, "limit": page},
            headers=headers, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def norm_title(title):
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def is_hold(row):
    return not (row.get("email") or "").strip() and "hold" in (row.get("guest_name") or "").lower()


def show_key(title, date_text):
    dt = parse_show_datetime(date_text, require_time=True)
    if not dt or not norm_title(title):
        return None
    return (norm_title(title), dt.isoformat())


def build_external_counts(rows):
    """{(normalized title, showtime iso): outside tickets}"""
    counts = defaultdict(int)
    for row in rows:
        if is_hold(row):
            continue
        key = show_key(row.get("show_title"), row.get("show_date"))
        if key:
            counts[key] += int(row.get("tickets") or 0)
    return dict(counts)


# ---------------------------------------------------------------------------
# Shopify: one General Admission variant per showtime
# ---------------------------------------------------------------------------
PRODUCTS_QUERY = """
query ShowInventory($cursor: String) {
  products(first: 50, after: $cursor, query: "status:active") {
    nodes {
      id title handle productType tags isGiftCard
      variants(first: 100) {
        nodes {
          id title inventoryQuantity
          selectedOptions { name value }
          inventoryItem { id }
          metafield(namespace: "%s", key: "%s") { value }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}""" % (NAMESPACE, KEY)


def fetch_products(shop):
    products, cursor = [], None
    while True:
        page = shop.gql(PRODUCTS_QUERY, {"cursor": cursor})["products"]
        products.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return products
        cursor = page["pageInfo"]["endCursor"]


def option(variant, *names):
    for opt in variant.get("selectedOptions") or []:
        if opt["name"].strip().lower() in names:
            return opt["value"]
    return None


def date_text(variant):
    return option(variant, "date & time", "date", "showtime", "date and time") or variant["title"]


def ticket_type(variant):
    return (option(variant, "ticket type", "type", "ticket") or "").lower()


def ga_variant(variants):
    """The variant outside sales come off. Dojour only sells general admission."""
    if len(variants) == 1:
        return variants[0]
    for v in variants:
        if re.search(r"general|\bga\b", ticket_type(v)):
            return v
    for v in variants:
        if "vip" not in ticket_type(v):
            return v
    return variants[0]


def plan_changes(products, external):
    """
    Returns (changes, baselines, unmatched).
      changes:   [{variant, title, showtime, before, after, recorded, external}]
      baselines: variants seen for the first time (metafield written, stock untouched)
      unmatched: external shows with no Shopify showtime
    """
    changes, baselines, matched = [], [], set()
    for product in products:
        if skip_reason(product):
            continue
        by_show = defaultdict(list)
        for v in product["variants"]["nodes"]:
            key = show_key(product["title"], date_text(v))
            if key:
                by_show[key].append(v)
        for key, variants in by_show.items():
            outside = external.get(key, 0)
            if key in external:
                matched.add(key)
            v = ga_variant(variants)
            meta = (v.get("metafield") or {}).get("value")
            recorded = int(meta) if meta not in (None, "") else None
            entry = {"variant": v, "title": product["title"], "showtime": date_text(v),
                     "before": v["inventoryQuantity"], "recorded": recorded, "external": outside}
            if recorded is None:
                entry["after"] = v["inventoryQuantity"]
                baselines.append(entry)
            elif outside != recorded:
                entry["after"] = max(v["inventoryQuantity"] - (outside - recorded), 0)
                changes.append(entry)
    unmatched = sorted(k for k in external if k not in matched)
    return changes, baselines, unmatched


# ---------------------------------------------------------------------------
# Writing back
# ---------------------------------------------------------------------------
def location_id(shop):
    nodes = shop.gql("{ locations(first: 5) { nodes { id name } } }")["locations"]["nodes"]
    if not nodes:
        sys.exit("No Shopify location found.")
    return nodes[0]["id"]


def set_stock(shop, loc, changes):
    if not changes:
        return
    quantities = [{"inventoryItemId": c["variant"]["inventoryItem"]["id"], "locationId": loc,
                   "quantity": c["after"]} for c in changes]
    result = shop.gql("""
      mutation SetStock($input: InventorySetQuantitiesInput!) {
        inventorySetQuantities(input: $input) { userErrors { field message } }
      }""", {"input": {"name": "available", "reason": "other",
                       "ignoreCompareQuantity": True, "quantities": quantities}})
    errors = result["inventorySetQuantities"]["userErrors"]
    if errors:
        raise RuntimeError(f"inventorySetQuantities: {errors}")


def set_recorded(shop, entries):
    for i in range(0, len(entries), 25):
        metafields = [{"ownerId": e["variant"]["id"], "namespace": NAMESPACE, "key": KEY,
                       "type": "number_integer", "value": str(e["external"])}
                      for e in entries[i:i + 25]]
        result = shop.gql("""
          mutation Record($metafields: [MetafieldsSetInput!]!) {
            metafieldsSet(metafields: $metafields) { userErrors { field message } }
          }""", {"metafields": metafields})
        errors = result["metafieldsSet"]["userErrors"]
        if errors:
            raise RuntimeError(f"metafieldsSet: {errors}")


def main():
    external = build_external_counts(fetch_external_rows())
    print(f"Outside tickets (Dojour, comps) for {len(external)} showtimes.")

    shop = Shopify()
    changes, baselines, unmatched = plan_changes(fetch_products(shop), external)

    for e in baselines:
        print(f"  baseline  {e['title']} / {e['showtime']}: {e['external']} outside tickets noted, "
              f"website stays at {e['before']}")
    for e in changes:
        print(f"  {e['title']} / {e['showtime']}: outside {e['recorded']} -> {e['external']}, "
              f"website {e['before']} -> {e['after']}")
    for key in unmatched:
        print(f"  no Shopify showtime for {key[0]} @ {key[1]} ({external[key]} outside tickets)")

    if not changes and not baselines:
        print("Shopify already matches Dojour.")
        return
    if DRY_RUN:
        print("DRY_RUN: nothing written.")
        return

    set_stock(shop, location_id(shop), changes)
    set_recorded(shop, changes + baselines)
    print(f"Updated {len(changes)} showtime(s), recorded baseline for {len(baselines)}.")


if __name__ == "__main__":
    main()
