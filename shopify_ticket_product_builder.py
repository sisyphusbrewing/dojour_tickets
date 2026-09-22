import os
import re
import csv
import json
import base64
import requests
from datetime import datetime, timedelta
import zoneinfo

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")

# Sisyphus Brewing venue capacity & ticket defaults
DEFAULT_ROOM_CAPACITY = 75       # Standard theater seat capacity per showtime
DEFAULT_TICKET_PRICE = "20.00"   # Default GA ticket price in USD
VENUE_COLLECTION_HANDLE = "comedy-and-events"
VENUE_DISCLAIMER_HTML = """
<p><strong>🎟 100% Will-Call:</strong> No paper tickets needed. Check in under your name at the door.</p>
<hr/>
{bio_html}
<hr/>
<p style="font-size: 0.9em; color: #64748b;">
<strong>Show Information & Venue Policies:</strong><br/>
• This is a full capacity show at Sisyphus Brewing Comedy Club (712 Ontario Ave W, Minneapolis, MN).<br/>
• Must be 18+ to attend.<br/>
• All sales are final unless the event is cancelled or rescheduled.<br/>
• You will receive an email confirmation upon purchase. Just give your name at the door upon arrival.
</p>
""".strip()


def get_shopify_headers() -> tuple[str, dict]:
    """Resolves Shopify store domain and sets up authenticated REST headers."""
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store:
        store = input("Enter your myshopify store (e.g. sisyphus-brewing or sisyphusbrewing.myshopify.com): ").strip()
    
    if not store.endswith(".myshopify.com"):
        store = f"{store}.myshopify.com"

    # Check for direct Admin token first
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN") or os.environ.get("SHOPIFY_ADMIN_API_TOKEN")
    
    # Otherwise check client credentials grant
    if not token:
        client_id = os.environ.get("SHOPIFY_CLIENT_ID")
        client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
        if client_id and client_secret:
            token_url = f"https://{store}/admin/oauth/access_token"
            resp = requests.post(token_url, json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials"
            }, timeout=15)
            resp.raise_for_status()
            token = resp.json().get("access_token")

    if not token:
        raise ValueError("Missing Shopify credentials. Set SHOPIFY_ACCESS_TOKEN or SHOPIFY_CLIENT_ID/SECRET.")

    headers = {
        "X-Shopify-Access-Token": token.strip(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    return store, headers


def format_variant_datetime(dt: datetime) -> str:
    """
    Formats dates to strictly match the door check-in & sync system:
    Example: 'Fri, Oct 23 • 7:00 PM' or 'Fri, Oct 23, 2027 • 7:00 PM'
    """
    now = datetime.now(CENTRAL_TZ)
    if dt.year != now.year:
        return dt.strftime("%a, %b %-d, %Y • %-I:%M %p")
    return dt.strftime("%a, %b %-d • %-I:%M %p")


def build_show_schedule() -> list[dict]:
    """Interactively prompts user to assemble show dates and times with quick presets."""
    print("\n--- Show Schedule Builder ---")
    print("Choose a schedule layout:")
    print("  [1] Standard 2-Night Run (Fri 7pm, Fri 9pm, Sat 7pm, Sat 9pm)")
    print("  [2] Standard 2-Night Single Shows (Fri 7pm, Sat 7pm)")
    print("  [3] Single Night Double Header (e.g. Sat 7pm, Sat 9pm)")
    print("  [4] Single Show Only (e.g. Sun 6pm or Wed 7pm)")
    print("  [5] Custom schedule")

    choice = input("Select layout (1-5) [default: 1]: ").strip() or "1"
    variants = []

    if choice in ["1", "2"]:
        date_str = input("Enter Friday's date (YYYY-MM-DD or 'Oct 24'): ").strip()
        base_friday = parse_user_input_date(date_str)
        saturday = base_friday + timedelta(days=1)

        times = ["7:00 PM", "9:00 PM"] if choice == "1" else ["7:00 PM"]
        for t_str in times:
            h, m, ampm = parse_time_str(t_str)
            dt_fri = base_friday.replace(hour=h, minute=m)
            variants.append({"title": format_variant_datetime(dt_fri), "datetime": dt_fri})

        for t_str in times:
            h, m, ampm = parse_time_str(t_str)
            dt_sat = saturday.replace(hour=h, minute=m)
            variants.append({"title": format_variant_datetime(dt_sat), "datetime": dt_sat})

    elif choice == "3":
        date_str = input("Enter show date (YYYY-MM-DD or 'Oct 24'): ").strip()
        base_date = parse_user_input_date(date_str)
        for t_str in ["7:00 PM", "9:00 PM"]:
            h, m, ampm = parse_time_str(t_str)
            dt = base_date.replace(hour=h, minute=m)
            variants.append({"title": format_variant_datetime(dt), "datetime": dt})

    elif choice == "4":
        date_str = input("Enter show date (YYYY-MM-DD or 'Oct 24'): ").strip()
        time_str = input("Enter show time [default: 7:00 PM]: ").strip() or "7:00 PM"
        base_date = parse_user_input_date(date_str)
        h, m, _ = parse_time_str(time_str)
        dt = base_date.replace(hour=h, minute=m)
        variants.append({"title": format_variant_datetime(dt), "datetime": dt})

    else:
        num = int(input("How many show times? ") or "1")
        for i in range(num):
            d_str = input(f"Show #{i+1} date (YYYY-MM-DD or 'Oct 24'): ").strip()
            t_str = input(f"Show #{i+1} time (e.g. 7:00 PM): ").strip()
            base_date = parse_user_input_date(d_str)
            h, m, _ = parse_time_str(t_str)
            dt = base_date.replace(hour=h, minute=m)
            variants.append({"title": format_variant_datetime(dt), "datetime": dt})

    return variants


def parse_time_str(time_str: str) -> tuple[int, int, str]:
    clean = time_str.strip().upper()
    match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?', clean)
    if not match:
        return 19, 0, "PM"
    h = int(match.group(1))
    m = int(match.group(2) or 0)
    ampm = match.group(3) or "PM"
    if ampm == "PM" and h < 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return h, m, ampm


def parse_user_input_date(date_str: str) -> datetime:
    now = datetime.now(CENTRAL_TZ)
    # Check YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.replace(tzinfo=CENTRAL_TZ)

    # Check MM/DD or MM/DD/YYYY
    if re.match(r'^\d{1,2}/\d{1,2}(?:/\d{2,4})?$', date_str):
        parts = date_str.split('/')
        m, d = int(parts[0]), int(parts[1])
        y = int(parts[2]) if len(parts) > 2 else now.year
        if y < 100: y += 2000
        return datetime(y, m, d, tzinfo=CENTRAL_TZ)

    # Natural text like 'Oct 24' or 'October 24'
    m = re.search(r'([A-Za-z]+)\s*(\d{1,2})', date_str)
    if m:
        month_name = m.group(1)[:3].capitalize()
        month = datetime.strptime(month_name, "%b").month
        day = int(m.group(2))
        year = now.year
        if month < now.month:
            year += 1
        return datetime(year, month, day, tzinfo=CENTRAL_TZ)

    print(f"Could not parse '{date_str}', using today.")
    return now


def build_shopify_product_payload(comedian_name: str, bio_text: str, variants: list[dict], price: str, capacity: int, image_url: str = None) -> dict:
    """Prepares the exact JSON payload expected by Shopify Admin REST API."""
    bio_html = f"<p>{bio_text.strip()}</p>" if bio_text.strip() else "<p>Live stand-up comedy at Sisyphus Brewing.</p>"
    body_html = VENUE_DISCLAIMER_HTML.format(bio_html=bio_html)

    product_variants = []
    for v in variants:
        product_variants.append({
            "option1": v["title"],
            "price": price,
            "sku": f"SISY-{re.sub(r'[^A-Z0-9]', '', comedian_name.upper())[:8]}-{v['datetime'].strftime('%m%d%H%M')}",
            "inventory_management": "shopify",
            "inventory_policy": "deny",
            "requires_shipping": False,   # Will-Call digital ticket!
            "taxable": True
        })

    payload = {
        "product": {
            "title": comedian_name.strip(),
            "body_html": body_html,
            "vendor": "Sisyphus Brewing",
            "product_type": "Comedy",
            "tags": "Comedy, Tickets, Will Call, Minneapolis",
            "options": [
                {
                    "name": "Date & Time"
                }
            ],
            "variants": product_variants
        }
    }

    if image_url and image_url.startswith("http"):
        payload["product"]["images"] = [{"src": image_url}]

    return payload


def set_variant_inventory(store: str, headers: dict, variant_id: int, inventory_item_id: int, capacity: int):
    """Sets the available inventory seats for a given variant in Shopify."""
    try:
        # 1. Fetch primary location
        loc_resp = requests.get(f"https://{store}/admin/api/2024-01/locations.json", headers=headers, timeout=15)
        if loc_resp.status_code != 200:
            return
        locations = loc_resp.json().get("locations", [])
        if not locations:
            return
        location_id = locations[0]["id"]

        # 2. Set available inventory
        inv_payload = {
            "location_id": location_id,
            "inventory_item_id": inventory_item_id,
            "available": capacity
        }
        requests.post(
            f"https://{store}/admin/api/2024-01/inventory_levels/set.json",
            headers=headers,
            json=inv_payload,
            timeout=15
        )
    except Exception as e:
        print(f"  (Notice) Could not set inventory capacity: {e}")


def publish_to_shopify(payload: dict, capacity: int) -> dict:
    store, headers = get_shopify_headers()
    api_url = f"https://{store}/admin/api/2024-01/products.json"

    print(f"\nPublishing '{payload['product']['title']}' to https://{store}...")
    resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
    
    if resp.status_code not in [200, 201]:
        print(f"Shopify Error ({resp.status_code}): {resp.text}")
        resp.raise_for_status()

    created_product = resp.json().get("product", {})
    prod_id = created_product.get("id")
    handle = created_product.get("handle")
    live_url = f"https://{store}/products/{handle}"

    print(f"✓ Successfully published! Live at: {live_url}")

    # Set capacity per variant
    for v in created_product.get("variants", []):
        set_variant_inventory(store, headers, v.get("id"), v.get("inventory_item_id"), capacity)

    print(f"✓ Set inventory capacity to {capacity} tickets per showtime.")
    return created_product


def export_to_csv(comedian_name: str, bio_text: str, variants: list[dict], price: str, capacity: int, filename: str = "shopify_comedy_tickets.csv"):
    """Generates a standard Shopify Product Import CSV file."""
    handle = re.sub(r'[^a-z0-9]+', '-', comedian_name.lower()).strip('-')
    body_html = VENUE_DISCLAIMER_HTML.format(bio_html=f"<p>{bio_text.strip()}</p>")

    headers = [
        "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published",
        "Option1 Name", "Option1 Value", "Variant SKU", "Variant Grams", "Variant Inventory Tracker",
        "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service",
        "Variant Price", "Variant Requires Shipping", "Variant Taxable", "Status"
    ]

    rows = []
    for idx, v in enumerate(variants):
        sku = f"SISY-{re.sub(r'[^A-Z0-9]', '', comedian_name.upper())[:8]}-{v['datetime'].strftime('%m%d%H%M')}"
        rows.append({
            "Handle": handle,
            "Title": comedian_name if idx == 0 else "",
            "Body (HTML)": body_html if idx == 0 else "",
            "Vendor": "Sisyphus Brewing" if idx == 0 else "",
            "Product Category": "Arts & Entertainment > Event Tickets" if idx == 0 else "",
            "Type": "Comedy" if idx == 0 else "",
            "Tags": "Comedy, Tickets, Will Call, Minneapolis" if idx == 0 else "",
            "Published": "TRUE",
            "Option1 Name": "Date & Time",
            "Option1 Value": v["title"],
            "Variant SKU": sku,
            "Variant Grams": "0",
            "Variant Inventory Tracker": "shopify",
            "Variant Inventory Qty": capacity,
            "Variant Inventory Policy": "deny",
            "Variant Fulfillment Service": "manual",
            "Variant Price": price,
            "Variant Requires Shipping": "FALSE",
            "Variant Taxable": "TRUE",
            "Status": "active"
        })

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Saved {len(variants)} variants to CSV: {filename}")


def main():
    print("==========================================================")
    print("  SISYPHUS BREWING • STREAMLINED SHOPIFY TICKET BUILDER   ")
    print("==========================================================")

    comedian = input("\nComedian / Show Title (e.g. Liz Miele): ").strip()
    if not comedian:
        print("Show title is required.")
        return

    price = input(f"Ticket Price (USD) [default: ${DEFAULT_TICKET_PRICE}]: ").strip() or DEFAULT_TICKET_PRICE
    price = price.replace("$", "").strip()

    capacity_in = input(f"Room Capacity / Ticket Limit [default: {DEFAULT_ROOM_CAPACITY}]: ").strip()
    capacity = int(capacity_in) if capacity_in.isdigit() else DEFAULT_ROOM_CAPACITY

    print("\nPaste comedian bio (Press ENTER, then Ctrl+D or Ctrl+Z to finish):")
    bio_lines = []
    try:
        while True:
            line = input()
            bio_lines.append(line)
    except EOFError:
        pass
    bio = "\n".join(bio_lines).strip()

    image_url = input("\nComedian Promo Image URL (optional, leave blank to skip): ").strip()

    variants = build_show_schedule()
    if not variants:
        print("No showtimes defined.")
        return

    print("\n--- Summary of Showtimes to Create ---")
    for v in variants:
        print(f"  • {v['title']} (Capacity: {capacity}, Price: ${price})")

    payload = build_shopify_product_payload(comedian, bio, variants, price, capacity, image_url)

    print("\nPublishing Options:")
    print("  [1] Publish directly to Shopify Store right now (Recommended)")
    print("  [2] Export as Shopify Import CSV file")
    print("  [3] Dry-run (Print JSON payload only)")

    action = input("Select action (1-3) [default: 1]: ").strip() or "1"

    if action == "1":
        try:
            publish_to_shopify(payload, capacity)
        except Exception as e:
            print(f"Publish failed: {e}")
            fallback = input("Would you like to export as CSV instead? (y/n): ")
            if fallback.lower().startswith('y'):
                export_to_csv(comedian, bio, variants, price, capacity)
    elif action == "2":
        csv_file = f"{re.sub(r'[^a-z0-9]', '_', comedian.lower())}_tickets.csv"
        export_to_csv(comedian, bio, variants, price, capacity, csv_file)
    else:
        print("\n--- Prepared JSON Payload ---")
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()