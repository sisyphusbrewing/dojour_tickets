"""
Sisyphus - buyer email list for one performer's shows, Shopify + Dojour combined.

Run from GitHub: Actions -> "Buyer email list" -> Run workflow, type the performer's
name (e.g. "Ali Sultan"). One row per buyer per show night, cancelled/refunded orders
left out. Buyers who opted out of marketing are flagged (marketing_ok = no) so the list
can be filtered before it's handed to a comedian. The CSV is attached to the run as
buyer_list.csv and also printed in the log.
"""
import csv
import io
import os
import sys

import requests

from fetch_tickets import get_dojour_token, extract_tickets_count, parse_show_datetime
from maintain_shows import Shopify

QUERY = (os.environ.get("SHOW_QUERY") or (sys.argv[1] if len(sys.argv) > 1 else "")).strip()
# Optional YYYY-MM-DD: only shows on or after this date (a performer's latest run, not every visit).
SINCE = (os.environ.get("SINCE") or "").strip()
FIELDS = ["name", "email", "show", "qty", "source", "marketing_ok"]
# Dojour field names that look like a marketing opt-in; whichever exists is used.
DOJOUR_CONSENT_KEYS = ("email_subscription_consent", "accepts_marketing", "marketing_opt_in", "opt_in", "email_opt_in",
                       "subscribe", "subscribed", "newsletter", "mailing_list", "is_subscribed")


def shopify_rows(query):
    shop = Shopify()
    found = shop.gql("""query($q: String!) { products(first: 20, query: $q) {
        nodes { id legacyResourceId title } } }""", {"q": query})["products"]["nodes"]
    products = [p for p in found if query.lower() in p["title"].lower()]
    rows = []
    # The app has no read_customers scope; the order-level opt-in flag is tried first.
    consent_field = "customerAcceptsMarketing"
    try:
        shop.gql("{ orders(first: 1) { nodes { customerAcceptsMarketing } } }")
    except Exception as e:
        print(f"Shopify marketing flag unavailable ({str(e)[:120]}); marketing_ok left unknown")
        consent_field = ""
    for p in products:
        cursor = None
        while True:
            page = shop.gql("""query($q: String!, $c: String) {
              orders(first: 100, after: $c, query: $q) {
                nodes { cancelledAt email %s
                  billingAddress { name }
                  lineItems(first: 50) { nodes { product { id } variantTitle currentQuantity } } }
                pageInfo { hasNextPage endCursor } } }""" % consent_field,
                             {"q": f"product_id:{p['legacyResourceId']}", "c": cursor})["orders"]
            for o in page["nodes"]:
                if o["cancelledAt"]:
                    continue
                email = (o.get("email") or "").strip()
                name = (o.get("billingAddress") or {}).get("name") or ""
                flag = o.get("customerAcceptsMarketing")
                ok = "unknown" if flag is None else ("yes" if flag else "no")
                for li in o["lineItems"]["nodes"]:
                    if (li["product"] or {}).get("id") != p["id"] or not li["currentQuantity"]:
                        continue
                    show = (li["variantTitle"] or "").split(" / ")[0]
                    rows.append({"name": name, "email": email, "show": show, "qty": li["currentQuantity"],
                                 "source": "Website", "marketing_ok": ok})
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
    print(f"Shopify: {len(products)} product(s), {len(rows)} buyer rows")
    return rows


def dojour_rows(query):
    token = get_dojour_token()
    s = requests.Session()
    s.cookies.set("usertoken", token, domain="dojour.us")
    s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    q = query.lower()
    instances = {}
    for extra in ("", "&upcoming=false", "&past=true"):
        url = f"https://dojour.us/api/event_instances/reserve_reports/?page_size=100{extra}"
        while url:
            r = s.get(url, timeout=30)
            if r.status_code != 200:
                break
            data = r.json()
            for item in (data.get("results", []) if isinstance(data, dict) else data):
                opt = (item.get("option_set") or [{}])[0].get("title") or ""
                ev = item.get("event") if isinstance(item.get("event"), dict) else {}
                hay = " ".join(str(x) for x in (opt, item.get("title"), item.get("event_title"), ev.get("title"))).lower()
                iid = str(item.get("id") or item.get("event_instance_id") or "")
                dt = parse_show_datetime(item.get("start_dt"))
                if SINCE and dt and dt.strftime("%Y-%m-%d") < SINCE:
                    continue
                if iid and q in hay:
                    instances[iid] = item.get("start_dt")
            url = data.get("next") if isinstance(data, dict) else None
    rows, keys_seen = [], set()
    for iid, start in instances.items():
        r = s.get(f"https://dojour.us/api/event_instances/{iid}/reserve_report/", timeout=30)
        if r.status_code != 200:
            continue
        dt = parse_show_datetime(start)
        show = dt.strftime("%a, %b %-d %Y • %-I:%M %p") if dt else str(start)
        for res in r.json().get("reservation_set", []):
            if not isinstance(res, dict) or res.get("is_cancelled") or res.get("waitlist") \
                    or res.get("is_on_waitlist") or res.get("checkout_complete") is False:
                continue
            user = res.get("user") if isinstance(res.get("user"), dict) else {}
            keys_seen |= set(res) | {f"user.{k}" for k in user}
            name = f"{res.get('first_name') or user.get('first_name') or ''} " \
                   f"{res.get('last_name') or user.get('last_name') or ''}".strip() or res.get("name") or ""
            email = (res.get("email") or user.get("email") or "").strip()
            ok = "unknown"
            for src in (res, user):
                for k in DOJOUR_CONSENT_KEYS:
                    if k in src and src[k] is not None:
                        ok = "yes" if src[k] else "no"
            rows.append({"name": name, "email": email, "show": show, "qty": extract_tickets_count(res),
                         "source": "Dojour", "marketing_ok": ok})
    print(f"Dojour: {len(instances)} show(s), {len(rows)} buyer rows")
    print("Dojour reservation fields: " + ", ".join(sorted(keys_seen)))
    return rows


def main():
    if not QUERY:
        sys.exit("Give a performer name, e.g. SHOW_QUERY='Ali Sultan'.")
    rows = shopify_rows(QUERY) + dojour_rows(QUERY)
    # Merge repeat buyers for the same night (same email + show).
    merged = {}
    for r in rows:
        key = (r["email"].lower() or r["name"].lower(), r["show"])
        if key in merged:
            merged[key]["qty"] += r["qty"]
            if r["marketing_ok"] == "no":
                merged[key]["marketing_ok"] = "no"
        else:
            merged[key] = dict(r)
    out = sorted(merged.values(), key=lambda r: (r["show"], r["name"].lower()))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(out)
    with open("buyer_list.csv", "w", newline="") as f:
        f.write(buf.getvalue())
    emails = {r["email"].lower() for r in out if r["email"]}
    print(f"{len(out)} rows, {len(emails)} unique emails, {sum(r['qty'] for r in out)} tickets")
    print("----- buyer_list.csv -----")
    print(buf.getvalue())


if __name__ == "__main__":
    main()
