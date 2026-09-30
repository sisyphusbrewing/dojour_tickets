import os
import sys
import re
import json
from datetime import datetime, timedelta
import requests

# ---------------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT (Accepts SHOPIFY_CLIENT_SECRET automatically)
# ---------------------------------------------------------------------------
raw_store = os.environ.get("SHOPIFY_STORE", "").replace("https://", "").replace("/", "").strip()
if raw_store and not raw_store.endswith(".myshopify.com"):
    SHOPIFY_STORE = f"{raw_store}.myshopify.com"
else:
    SHOPIFY_STORE = raw_store

# Use SHOPIFY_ACCESS_TOKEN if present, otherwise fall back to SHOPIFY_CLIENT_SECRET
SHOPIFY_ACCESS_TOKEN = (
    os.environ.get("SHOPIFY_ACCESS_TOKEN") or 
    os.environ.get("SHOPIFY_CLIENT_SECRET") or 
    ""
).strip()

SHOW_TITLE = os.environ.get("SHOW_TITLE", "").strip()
SHOWTIMES_INPUT = os.environ.get("SHOW_DATE", "").strip() or os.environ.get("SHOWTIMES", "").strip()
SHOW_PRICE = os.environ.get("SHOW_PRICE", "20.00").strip()
SHOW_CAPACITY = os.environ.get("SHOW_CAPACITY", "75").strip()
SHOW_BIO = os.environ.get("SHOW_BIO", "").strip()
SHOW_IMAGE_URL = os.environ.get("SHOW_IMAGE_URL", "").strip()

VENUE_NAME = "Sisyphus Brewing"
COLLECTION_HANDLE = "comedy-and-events"

STANDARD_POLICY_HTML = """
<div style="margin-top: 24px; padding: 14px; border: 1px solid #334155; border-radius: 8px; background-color: #0f172a; color: #cbd5e1; font-size: 13px; line-height: 1.5;">
  <p style="margin: 0 0 6px 0; font-weight: bold; color: #f59e0b;">🎟️ Will-Call & Venue Policies:</p>
  <ul style="margin: 0; padding-left: 18px;">
    <li>All tickets are <strong>Will-Call</strong>. No physical tickets will be mailed.</li>
    <li>Simply check in at the door under the purchaser's name upon arrival.</li>
    <li>18+ recommended. Valid ID required for craft beer purchases.</li>
    <li>Location: Sisyphus Brewing Taproom & Comedy Theater (712 Ontario Ave W #100, Minneapolis, MN 55403).</li>
  </ul>
</div>
"""

# ---------------------------------------------------------------------------
# TEXT & BIO FORMATTER
# ---------------------------------------------------------------------------
def format_bio_html(raw_text):
    if not raw_text or not raw_text.strip():
        return "<p>Live stand-up comedy and events at Sisyphus Brewing.</p>"

    clean = raw_text.strip()
    if "<p>" in clean or "<br" in clean:
        return clean

    paragraphs = re.split(r'\n\s*\n', clean)
    html_parts = []

    for para in paragraphs:
        lines = [l.strip() for l in para.split('\n') if l.strip()]
        if not lines:
            continue

        if all(l.startswith(('•', '-', '*')) for l in lines):
            items = []
            for l in lines:
                cleaned_line = re.sub(r'^[-*•]\s*', '', l)
                items.append(f"<li>{cleaned_line}</li>")
            html_parts.append(f'<ul style="margin: 8px 0; padding-left: 20px;">{"".join(items)}</ul>')
        else:
            br_joined = "<br/>".join(lines)
            html_parts.append(f'<p style="margin-bottom: 12px; line-height: 1.6;">{br_joined}</p>')

    return "\n".join(html_parts)

# ---------------------------------------------------------------------------
# SHOWTIME PARSER
# ---------------------------------------------------------------------------
def parse_single_showtime(raw_str):
    raw_str = raw_str.strip()
    if not raw_str:
        return None

    if any(k in raw_str.lower() for k in ['pass', 'registration', 'general admission', 'class series']):
        return raw_str

    if " • " in raw_str and any(ampm in raw_str.upper() for ampm in ["AM", "PM"]):
        return raw_str

    now = datetime.now()
    cur_year = now.year

    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', raw_str, re.IGNORECASE)
    hours, mins, ampm = 19, 0, "PM"
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2)) if time_match.group(2) else 0
        ap = time_match.group(3).upper() if time_match.group(3) else None
        if ap:
            ampm = ap
            hours = h
        elif h in [7, 8, 9, 10, 11]:
            hours, ampm = h, "PM"
        elif h >= 12:
            hours, ampm = h % 12 or 12, "PM"
        else:
            hours = h
        mins = m

    date_part = raw_str
    if time_match:
        date_part = raw_str[:time_match.start()] + raw_str[time_match.end():]
    date_part = date_part.strip().strip(",").strip("•").strip("-")

    month_match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', date_part, re.IGNORECASE)
    day_match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', date_part)
    year_match = re.search(r'\b(20\d{2})\b', date_part)

    if month_match and day_match:
        month_str = month_match.group(1).capitalize()
        day = int(day_match.group(1))
        year = int(year_match.group(1)) if year_match else cur_year
        month_num = datetime.strptime(month_str, "%b").month
        try:
            dt = datetime(year, month_num, day)
            weekday_str = dt.strftime("%a")
            formatted_time = f"{hours}:{mins:02d} {ampm}"
            return f"{weekday_str}, {month_str} {day} • {formatted_time}"
        except ValueError:
            pass

    return raw_str

def generate_variants(showtimes_raw):
    raw_entries = re.split(r'[,;\n]+', showtimes_raw)
    variants = []
    seen = set()

    for item in raw_entries:
        item = item.strip()
        if not item:
            continue

        if "weekend" in item.lower():
            clean_date = re.sub(r'weekend', '', item, flags=re.IGNORECASE).strip()
            v1 = parse_single_showtime(f"{clean_date} 7pm")
            v2 = parse_single_showtime(f"{clean_date} 9pm")
            try:
                m_match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', clean_date, re.IGNORECASE)
                d_match = re.search(r'\b(\d{1,2})\b', clean_date)
                if m_match and d_match:
                    dt = datetime(datetime.now().year, datetime.strptime(m_match.group(1).capitalize(), "%b").month, int(d_match.group(1)))
                    sat_dt = dt + timedelta(days=1)
                    sat_str = sat_dt.strftime("%b %d")
                    v3 = parse_single_showtime(f"{sat_str} 7pm")
                    v4 = parse_single_showtime(f"{sat_str} 9pm")
                    for v in [v1, v2, v3, v4]:
                        if v and v not in seen:
                            seen.add(v)
                            variants.append(v)
                    continue
            except Exception:
                pass

        parsed = parse_single_showtime(item)
        if parsed and parsed not in seen:
            seen.add(parsed)
            variants.append(parsed)

    if not variants:
        variants = ["General Admission"]
    return variants

# ---------------------------------------------------------------------------
# SHOPIFY API CLIENT
# ---------------------------------------------------------------------------
def get_shopify_headers():
    return {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def get_primary_location_id():
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/locations.json"
    resp = requests.get(url, headers=get_shopify_headers())
    if resp.status_code == 200:
        locs = resp.json().get("locations", [])
        if locs:
            return locs[0]["id"]
    return None

def set_variant_inventory(inventory_item_id, location_id, capacity):
    if not inventory_item_id or not location_id:
        return
    try:
        connect_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/inventory_levels/connect.json"
        requests.post(connect_url, headers=get_shopify_headers(), json={
            "location_id": location_id,
            "inventory_item_id": inventory_item_id
        })
        set_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/inventory_levels/set.json"
        requests.post(set_url, headers=get_shopify_headers(), json={
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": int(capacity)
        })
    except Exception as e:
        print(f"  ⚠️️ Could not set inventory: {e}")

# ---------------------------------------------------------------------------
# CHRONOLOGICAL COLLECTION REORDERING (GraphQL)
# ---------------------------------------------------------------------------
def reorder_collection_chronologically():
    print(f"\nSorting '{COLLECTION_HANDLE}' collection chronologically...")
    col_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/custom_collections.json?handle={COLLECTION_HANDLE}"
    resp = requests.get(col_url, headers=get_shopify_headers())
    if resp.status_code != 200 or not resp.json().get("custom_collections"):
        col_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/smart_collections.json?handle={COLLECTION_HANDLE}"
        resp = requests.get(col_url, headers=get_shopify_headers())

    cols = resp.json().get("custom_collections") or resp.json().get("smart_collections") or []
    if not cols:
        print(f"  ℹ️ Collection '{COLLECTION_HANDLE}' not found; skipping collection reorder.")
        return

    collection_id = cols[0]["id"]
    products_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/collections/{collection_id}/products.json?limit=250"
    p_resp = requests.get(products_url, headers=get_shopify_headers())
    if p_resp.status_code != 200:
        return

    products = p_resp.json().get("products", [])
    now = datetime.now()
    cur_year = now.year

    def get_product_timestamp(prod):
        for var in prod.get("variants", []):
            title = var.get("title", "")
            m_match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', title, re.IGNORECASE)
            d_match = re.search(r'\b(\d{1,2})\b', title)
            y_match = re.search(r'\b(20\d{2})\b', title)
            if m_match and d_match:
                m = datetime.strptime(m_match.group(1).capitalize(), "%b").month
                d = int(d_match.group(1))
                y = int(y_match.group(1)) if y_match else cur_year
                try:
                    return datetime(y, m, d).timestamp()
                except ValueError:
                    pass
        return float('inf')

    products.sort(key=get_product_timestamp)
    reordered_ids = [f"gid://shopify/Product/{p['id']}" for p in products]

    mutation = """
    mutation collectionReorderProducts($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        userErrors {
          field
          message
        }
      }
    }
    """
    moves = [{"id": pid, "newPosition": str(idx)} for idx, pid in enumerate(reordered_ids)]
    graphql_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json"
    g_resp = requests.post(graphql_url, headers=get_shopify_headers(), json={
        "query": mutation,
        "variables": {
            "id": f"gid://shopify/Collection/{collection_id}",
            "moves": moves
        }
    })

    if g_resp.status_code == 200 and not g_resp.json().get("errors"):
        print(f"  ✓ Collection '{COLLECTION_HANDLE}' successfully sorted chronologically!")
    else:
        print(f"  ℹ️ Collection reorder response: {g_resp.text[:120]}")

# ---------------------------------------------------------------------------
# PUBLISH PRODUCT
# ---------------------------------------------------------------------------
def publish_to_shopify(payload, capacity):
    create_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
    headers = get_shopify_headers()

    print(f"\nPublishing '{payload['product']['title']}' to https://{SHOPIFY_STORE}...")
    resp = requests.post(create_url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        print(f"Shopify Error ({resp.status_code}): {resp.text}")
        resp.raise_for_status()

    created_prod = resp.json()["product"]
    prod_id = created_prod["id"]
    print(f"  ✓ Live product created! (ID: {prod_id})")

    loc_id = get_primary_location_id()
    if loc_id:
        for v in created_prod.get("variants", []):
            inv_id = v.get("inventory_item_id")
            set_variant_inventory(inv_id, loc_id, capacity)
        print(f"  ✓ Inventory capacity set to {capacity} tickets per variant.")

    reorder_collection_chronologically()
    print(f"\n🎉 Successfully created and scheduled: {created_prod['title']}")
    print(f"👉 View live: https://{SHOPIFY_STORE}/products/{created_prod['handle']}")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("==========================================================")
    print("  SISYPHUS BREWING • SHOPIFY TICKET BUILDER               ")
    print("==========================================================")

    if not SHOPIFY_STORE or not SHOPIFY_ACCESS_TOKEN:
        if not SHOPIFY_STORE:
            print("❌ Error: SHOPIFY_STORE secret is missing from environment.")
        if not SHOPIFY_ACCESS_TOKEN:
            print("❌ Error: SHOPIFY_CLIENT_SECRET or SHOPIFY_ACCESS_TOKEN secret is missing.")
        sys.exit(1)

    print(f"Store target: https://{SHOPIFY_STORE}")
    print(f"Token present: {'Yes' if SHOPIFY_ACCESS_TOKEN else 'No'}")

    title = SHOW_TITLE or "Stand-Up Comedy Show"
    raw_showtimes = SHOWTIMES_INPUT or "Oct 24 7pm"
    price = SHOW_PRICE or "20.00"
    capacity = int(SHOW_CAPACITY) if SHOW_CAPACITY.isdigit() else 75
    raw_bio = SHOW_BIO
    image_url = SHOW_IMAGE_URL

    variant_names = generate_variants(raw_showtimes)
    formatted_body = format_bio_html(raw_bio) + STANDARD_POLICY_HTML

    variants_payload = []
    for var_name in variant_names:
        variants_payload.append({
            "option1": var_name,
            "price": price,
            "sku": f"TIX-{re.sub(r'[^A-Z0-9]', '', title.upper())[:10]}-{re.sub(r'[^A-Z0-9]', '', var_name.upper())[:10]}",
            "inventory_management": "shopify",
            "inventory_policy": "deny",
            "requires_shipping": False,
            "taxable": True
        })

    product_data = {
        "title": title,
        "body_html": formatted_body,
        "vendor": VENUE_NAME,
        "product_type": "Tickets",
        "tags": f"Comedy, Ticket, Live Event, {title}",
        "options": [{"name": "Date & Time"}],
        "variants": variants_payload,
        "status": "active"
    }

    if image_url and image_url.startswith("http"):
        product_data["images"] = [{"src": image_url}]

    payload = {"product": product_data}
    publish_to_shopify(payload, capacity)

if __name__ == "__main__":
    main()
