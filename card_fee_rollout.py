"""
Sisyphus - add the $1 card-processing fee to every show already on sale.

Run by the "Card fee rollout" action, by hand only. Sam approved getting the
$4 fee ready on Nov 18 2026 ($3 to the comics as before, $1 to cover card
processing), and it goes live only after he OKs the checkout preview.

For every active show whose price includes the $3 fee (custom.ticket_fee =
3) and that doesn't have the $1 yet, it:
  * raises every showtime's price by $1 (so the first price anyone sees is
    the whole price, as the FTC and Minnesota all-in pricing rules want),
  * sets custom.ticket_fee to 4, custom.card_fee to 1 and
    custom.card_fee_since to the moment the price went up, so settlements
    and swaps know which tickets were sold at the old price,
  * rewrites the fee sentence at the bottom of the show's description.

Tickets already sold keep the price they paid. Free shows, classes and shows
without the fee are left alone. Running it twice changes nothing the second
time.

    python card_fee_rollout.py            shows what it would change
    GO=yes python card_fee_rollout.py     changes the prices
"""
import os
import re
import sys
from datetime import datetime, timezone

from maintain_shows import Shopify
from ticket_fee import COMICS_FEE, CARD_FEE, fee_line

GO = (os.environ.get("GO") or "").strip().lower() == "yes"
# Shows to leave at the $3 fee. Advice Column stays $8 (Sam, Nov 18 2026:
# "Go live, skip Advice Column"): on a cheap ticket the extra $1 is a big bite.
SKIP = {h.strip() for h in (os.environ.get("SKIP") or "advice-column").split(",") if h.strip()}

PRODUCTS = """query($c: String) { products(first: 100, after: $c, query: "status:active") {
  nodes { id handle title descriptionHtml
    fee: metafield(namespace: "custom", key: "ticket_fee") { value }
    card: metafield(namespace: "custom", key: "card_fee") { value }
    variants(first: 100) { nodes { id price compareAtPrice } } }
  pageInfo { hasNextPage endCursor } } }"""

UPDATE_VARIANTS = """mutation($id: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $id, variants: $variants) { userErrors { field message } } }"""
SET_FIELDS = """mutation($m: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $m) { userErrors { field message } } }"""
UPDATE_TEXT = """mutation($p: ProductUpdateInput!) {
  productUpdate(product: $p) { userErrors { field message } } }"""

# The sentence ticket_product_builder.py has put on every show since Oct 10.
OLD_LINE = re.compile(r"<p>\s*<strong>\s*💵\s*Price includes a \$3 ticketing fee\s*</strong>\s*[—–-]\s*"
                      r"100% of the fee goes to performers\.?\s*</p>")


def money(x):
    return f"{x:.2f}"


def plan(products, skip=()):
    """What to change: one entry per show that still has only the $3."""
    out = []
    for p in products:
        if p.get("handle") in skip:
            continue
        try:
            fee = float((p.get("fee") or {}).get("value") or 0)
            card = float((p.get("card") or {}).get("value") or 0)
        except ValueError:
            continue
        if abs(fee - COMICS_FEE) > 0.001 or card > 0:
            continue
        variants = [v for v in p["variants"]["nodes"] if float(v["price"]) > fee]
        if not variants:
            continue
        body = p.get("descriptionHtml") or ""
        new_body, n = OLD_LINE.subn(fee_line(COMICS_FEE + CARD_FEE, CARD_FEE), body)
        out.append({
            "id": p["id"], "handle": p["handle"],
            "variants": [{"id": v["id"], "price": money(float(v["price"]) + CARD_FEE),
                          **({"compareAtPrice": money(float(v["compareAtPrice"]) + CARD_FEE)}
                             if v.get("compareAtPrice") and float(v["compareAtPrice"]) > 0 else {})}
                         for v in variants],
            "old_prices": sorted({v["price"] for v in variants}),
            "body": new_body if n else None,
        })
    return out


def check(data, field):
    errors = data[field]["userErrors"]
    if errors:
        raise RuntimeError(f"{field}: {errors}")


def main():
    shop = Shopify()
    products, cursor = [], None
    while True:
        page = shop.gql(PRODUCTS, {"c": cursor})["products"]
        products += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    todo = plan(products, SKIP)
    if SKIP:
        print(f"Left alone on purpose: {', '.join(sorted(SKIP))}")
    print(f"{len(todo)} shows still have only the $3 fee.")
    for t in todo:
        new = sorted({v["price"] for v in t["variants"]})
        text = "fee sentence rewritten" if t["body"] else "fee sentence not found, text left as is"
        print(f"  {t['handle']}: {', '.join(t['old_prices'])} -> {', '.join(new)} ({len(t['variants'])} showtimes; {text})")
    if not GO:
        print("Nothing changed. Run with GO=yes to raise the prices.")
        return

    for t in todo:
        check(shop.gql(UPDATE_VARIANTS, {"id": t["id"], "variants": t["variants"]}), "productVariantsBulkUpdate")
        # Stamped just after the price went up: a ticket sold in those few
        # seconds counts as an old $3 ticket, which only ever favors the comics.
        since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        check(shop.gql(SET_FIELDS, {"m": [
            {"ownerId": t["id"], "namespace": "custom", "key": "ticket_fee", "type": "number_decimal",
             "value": money(COMICS_FEE + CARD_FEE)},
            {"ownerId": t["id"], "namespace": "custom", "key": "card_fee", "type": "number_decimal",
             "value": money(CARD_FEE)},
            {"ownerId": t["id"], "namespace": "custom", "key": "card_fee_since", "type": "date_time",
             "value": since}]}), "metafieldsSet")
        if t["body"]:
            check(shop.gql(UPDATE_TEXT, {"p": {"id": t["id"], "descriptionHtml": t["body"]}}), "productUpdate")
        print(f"  done: {t['handle']}")
    print(f"Raised {len(todo)} shows by ${CARD_FEE:.0f}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.exit(f"Card fee rollout stopped: {e}")
