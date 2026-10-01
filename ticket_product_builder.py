import os
import re
import sys
import requests
from datetime import datetime

# ---------------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# ---------------------------------------------------------------------------
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").replace("https://", "").rstrip("/")
if SHOPIFY_STORE and not SHOPIFY_STORE.endswith(".myshopify.com"):
    SHOPIFY_STORE = f"{SHOPIFY_STORE}.myshopify.com"

CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")

# Support both naming conventions (SHOW_* and original workflow inputs)
TITLE = os.environ.get("SHOW_TITLE") or os.environ.get("COMEDIAN_NAME") or "Untitled Event"
SHOWTIMES_RAW = os.environ.get("SHOW_DATE") or os.environ.get("SHOWTIMES") or "General Admission"
PRICE = os.environ.get("SHOW_PRICE") or os.environ.get("TICKET_PRICE") or "20.00"
CAPACITY_RAW = os.environ.get("SHOW_CAPACITY") or os.environ.get("ROOM_CAPACITY") or "75"
BIO_RAW = os.environ.get("SHOW_BIO") or os.environ.get("BIO") or ""
IMAGE_URL = os.environ.get("SHOW_IMAGE_URL") or os.environ.get("IMAGE_URL") or ""

VENUE_NAME = "Sisyphus Brewing"
COLLECTION_HANDLE = "comedy-and-events"
API_VERSION = "2024-01"

# ---------------------------------------------------------------------------
# BULLETPROOF SHOWTIME PARSER
# ---------------------------------------------------------------------------
WEEKDAYS = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 
            'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}

def clean_variant_name(raw_str):
    """Formats and standardizes a single date/time string."""
    s = raw_str.strip().strip(",").strip("•").strip("-")
    s = re.sub(r'^(Sun|Mon|Tue|Wed|Thu|Fri|Sat),\s*', r'\1 ', s, flags=re.IGNORECASE)
    return s

def generate_variants(showtimes_raw):
    if not showtimes_raw or not showtimes_raw.strip():
        return ["General Admission"]

    if "|" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split("|") if c.strip()]
    elif ";" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split(";") if c.strip()]
    elif "\n" in showtimes_raw:
        chunks = [c.strip() for c in showtimes_raw.split("\n") if c.strip()]
    else:
        chunks = [c.strip() for c in showtimes_raw.split(",") if c.strip()]

    recombined = []
    pending_day = ""

    for chunk in chunks:
        clean_chunk = chunk.strip().lower().rstrip(",")
        if clean_chunk in WEEKDAYS:
            pending_day = chunk.strip().capitalize()
            continue

        if pending_day:
            full_str = f"{pending_day} {chunk.strip()}"
            pending_day = ""
        else:
            full_str = chunk.strip()

        cleaned = clean_variant_name(full_str)
        if cleaned and cleaned.lower() not in WEEKDAYS:
            recombined.append(cleaned)

    final_variants = []
    seen = set()
    for v in recombined:
        if v not in seen:
            seen.add(v)
            final_variants.append(v)

    return final_variants if final_variants else ["General Admission"]

# ---------------------------------------------------------------------------
# HTML DESCRIPTION FORMATTER
# ---------------------------------------------------------------------------
def format_description_html(raw_bio):
    if not raw_bio or not raw_bio.strip():
        return f"<p>Live comedy at {VENUE_NAME}. 100% Will-Call: check in under your name at the door.</p>"

    # If already HTML, return directly
    if "<p>" in raw_bio or "<br" in raw_bio:
        return raw_bio

    paragraphs = raw_bio.strip().split("\n\n")
    html_parts = []
    for para in paragraphs:
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        if not lines:
            continue
        # Convert bullet points into <ul>
        if all(l.startswith(("•", "-", "*")) for l in lines):
            items = "".join([f"<li>{re.sub(r'^[-*•]\s*', '', l)}</li>" for l in lines])
            html_parts.append(f"<ul style='margin: 8px 0; padding-left: 20px;'>{items}</ul>")
        else:
            html_parts.append(f"<p style='margin-bottom: 12px; line-height: 1.6;'>{'<br/>'.join(lines)}</p>")

    # Policy footer
    policy_footer = (
        "<hr style='margin: 20px 0; border: none; border-top: 1px solid #ddd;'/>"
        "<p><strong>🎟️ 100% Will-Call:</strong> No paper tickets needed. Check in under your name at the door.</p>"
        "<p><strong>📍 Venue:</strong> Sisyphus Brewing • 712 Ontario Ave W, Minneapolis, MN</p>"
    )
    return "\n".join(html_parts) + "\n" + policy_footer

# ---------------------------------------------------------------------------
# SHOPIFY AUTHENTICATION (CLIENT CREDENTIALS)
# ---------------------------------------------------------------------------
def get_shopify_access_token():
    print(f"Authenticating with Shopify ({SHOPIFY_STORE})...")
    if not CLIENT_ID or not CLIENT_SECRET or not SHOPIFY_STORE:
        print("❌ Missing SHOPIFY_STORE, SHOPIFY_CLIENT_ID, or SHOPIFY_CLIENT_SECRET environment variables!")
        sys.exit(1)

    url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    resp = requests.post(url, json=payload)
    if resp.status_code != 200:
        print(f"❌ Failed to obtain Shopify access token ({resp.status_code}): {resp.text}")
        sys.exit(1)

    token = resp.json().get("access_token")
    print("✓ Successfully authenticated with Shopify API!")
    return token

def get_shopify_headers(token):
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

# ---------------------------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("SISYPHUS BREWING • SHOPIFY TICKET CREATOR")
    print("=" * 60)
    print(f"Show Title:    {TITLE}")
    print(f"Raw Dates:     {SHOWTIMES_RAW}")
    print(f"Price:         ${PRICE}")
    print(f"Capacity:      {CAPACITY_RAW}")
    print(f"Image URL:     {IMAGE_URL[:50]}..." if IMAGE_URL else "Image URL:     None")
    print("-" * 60)

    token = get_shopify_access_token()
    headers = get_shopify_headers(token)

    # 1. Parse Variants
    variant_titles = generate_variants(SHOWTIMES_RAW)
    print(f"Generated {len(variant_titles)} variant(s): {variant_titles}")

    try:
        capacity_num = int(CAPACITY_RAW)
    except ValueError:
        capacity_num = 75

    try:
        price_clean = f"{float(re.sub(r'[^0-9.]', '', str(PRICE))):.2f}"
    except ValueError:
        price_clean = "20.00"

    variants_payload = []
    for vt in variant_titles:
        variants_payload.append({
            "option1": vt,
            "price": price_clean,
            "inventory_management": "shopify",
            "inventory_policy": "deny",
            "requires_shipping": False
        })

    # 2. Format Body
    body_html = format_description_html(BIO_RAW)

    # 3. Build Product Payload
    product_payload = {
        "product": {
            "title": TITLE,
            "body_html": body_html,
            "vendor": VENUE_NAME,
            "product_type": "Tickets",
            "tags": f"Comedy, Ticket, Live Event, {TITLE}",
            "options": [{"name": "Date & Time"}],
            "variants": variants_payload,
            "status": "active"
        }
    }

    if IMAGE_URL and IMAGE_URL.startswith("http"):
        product_payload["product"]["images"] = [{"src": IMAGE_URL}]

    # 4. Create Product via Shopify REST API
    create_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json"
    print("Creating product in Shopify...")
    resp = requests.post(create_url, headers=headers, json=product_payload)

    if resp.status_code not in (200, 201):
        print(f"❌ Product creation failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    created_product = resp.json().get("product", {})
    product_id = created_product.get("id")
    handle = created_product.get("handle")
    print(f"✓ Product created successfully! ID: {product_id} (Handle: {handle})")

    # 5. Set Inventory Quantity per Variant
    print("Setting ticket capacity...")
    loc_resp = requests.get(f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/locations.json", headers=headers)
    if loc_resp.status_code == 200:
        locations = loc_resp.json().get("locations", [])
        if locations:
            location_id = locations[0]["id"]
            for v in created_product.get("variants", []):
                inv_item_id = v.get("inventory_item_id")
                if inv_item_id:
                    set_inv_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/inventory_levels/set.json"
                    requests.post(set_inv_url, headers=headers, json={
                        "location_id": location_id,
                        "inventory_item_id": inv_item_id,
                        "available": capacity_num
                    })
            print(f"✓ Capacity set to {capacity_num} tickets per variant at location {locations[0].get('name')}.")

    # 6. Add Product to Collection
    print(f"Adding product to collection '{COLLECTION_HANDLE}'...")
    col_resp = requests.get(f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections.json?handle={COLLECTION_HANDLE}", headers=headers)
    col_id = None
    if col_resp.status_code == 200 and col_resp.json().get("custom_collections"):
        col_id = col_resp.json()["custom_collections"][0]["id"]

    if col_id:
        collect_resp = requests.post(
            f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/collects.json",
            headers=headers,
            json={"collect": {"collection_id": col_id, "product_id": product_id}}
        )
        if collect_resp.status_code in (200, 201):
            print(f"✓ Added to collection '{COLLECTION_HANDLE}'!")
    else:
        print(f"ℹ️ Collection '{COLLECTION_HANDLE}' not found or is automated; skipping collect.")

    print("=" * 60)
    print(f"🎉 SUCCESS! '{TITLE}' is now live on https://{SHOPIFY_STORE}/products/{handle}")
    print("=" * 60)

if __name__ == "__main__":
    main()
