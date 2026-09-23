import os
import re
import csv
import json
from datetime import datetime, timedelta
import zoneinfo
import requests

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")

# Sisyphus Brewing Venue Defaults
DEFAULT_ROOM_CAPACITY = 75
DEFAULT_TICKET_PRICE = "20.00"
VENUE_DISCLAIMER_HTML = """
<p><strong>🎟 100% Will-Call:</strong> No paper tickets needed. Check in under your name at the door.</p>
<hr/>
{bio_html}
<hr/>
<p style="font-size: 0.9em; color: #64748b;">
<strong>Venue Information & Policies:</strong><br/>
• Sisyphus Brewing Comedy Club & Taproom (712 Ontario Ave W, Minneapolis, MN).<br/>
• Must be 18+ to attend comedy shows.<br/>
• All sales are final unless the event is cancelled or rescheduled.<br/>
• You will receive an email confirmation upon purchase. Just give your name at the door upon arrival.
</p>
""".strip()


def get_shopify_headers() -> tuple[str, dict]:
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store:
        store = input("Enter myshopify store (e.g. sisyphusbrewing.myshopify.com): ").strip()

    if not store.endswith(".myshopify.com"):
        store = f"{store}.myshopify.com"

    token = os.environ.get("SHOPIFY_ACCESS_TOKEN") or os.environ.get("SHOPIFY_ADMIN_API_TOKEN")

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
        raise ValueError("Missing SHOPIFY_ACCESS_TOKEN or SHOPIFY_CLIENT_ID / SECRET.")

    headers = {
        "X-Shopify-Access-Token": token.strip(),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    return store, headers


def format_variant_datetime(dt: datetime) -> str:
    now = datetime.now(CENTRAL_TZ)
    if dt.year != now.year:
        return dt.strftime("%a, %b %-d, %Y • %-I:%M %p")
    return dt.strftime("%a, %b %-d • %-I:%M %p")


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


def parse_single_datetime(text: str) -> datetime | None:
    """Parses arbitrary strings like 'Oct 11 5pm', '2026-10-24 19:00', 'Nov 15 at 5:00 PM' into Central datetime."""
    now = datetime.now(CENTRAL_TZ)
    raw = text.strip()

    # Match month and day: e.g. Oct 11, October 11, 10/11
    month = None
    day = None
    year = now.year

    month_match = re.search(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b', raw, re.IGNORECASE)
    day_match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', raw)

    # Check 4-digit year
    year_match = re.search(r'\b(20\d{2})\b', raw)
    if year_match:
        year = int(year_match.group(1))

    if month_match and day_match:
        m_str = month_match.group(1)[:3].capitalize()
        month = datetime.strptime(m_str, "%b").month
        day = int(day_match.group(1))
    else:
        # Try MM/DD
        num_date = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', raw)
        if num_date:
            month = int(num_date.group(1))
            day = int(num_date.group(2))
            if num_date.group(3):
                y = int(num_date.group(3))
                year = y if y > 100 else y + 2000

    if not month or not day:
        return None

    # Resolve hour and minute
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', raw, re.IGNORECASE)
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2) or 0)
        ampm = time_match.group(3).upper()
        if ampm == "PM" and h < 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
    else:
        # Default to 7:00 PM if time omitted
        h, m = 19, 0

    if not year_match and month < now.month and (now.month - month) >= 8:
        year += 1

    try:
        return datetime(year, month, day, h, m, tzinfo=CENTRAL_TZ)
    except Exception:
        return None


def parse_freeform_showtimes(input_str: str) -> list[dict]:
    """
    Handles:
    - Lists: "Oct 11 5pm, Oct 18 5pm" or multi-line entries
    - Weekend shorthand: "Oct 24 weekend" -> Fri 7/9, Sat 7/9
    - Named passes: "Full 5-Week Class Pass" -> kept as titled variant
    """
    raw_entries = [line.strip() for line in re.split(r'[,\n;]+', input_str) if line.strip()]
    variants = []

    for entry in raw_entries:
        # Shortcut: "Oct 24 weekend"
        if "weekend" in entry.lower():
            parsed_dt = parse_single_datetime(entry)
            if parsed_dt:
                friday = parsed_dt
                saturday = friday + timedelta(days=1)
                for dt_base in [friday, saturday]:
                    for h, m in [(19, 0), (21, 0)]:
                        dt_show = dt_base.replace(hour=h, minute=m)
                        variants.append({
                            "title": format_variant_datetime(dt_show),
                            "datetime": dt_show
                        })
                continue

        parsed_dt = parse_single_datetime(entry)
        if parsed_dt:
            variants.append({
                "title": format_variant_datetime(parsed_dt),
                "datetime": parsed_dt
            })
        else:
            # Custom pass / General Admission / Non-dated item
            clean_title = entry.strip()
            variants.append({
                "title": clean_title,
                "datetime": datetime.now(CENTRAL_TZ)
            })

    return variants


def build_shopify_product_payload(comedian_name: str, bio_text: str, variants: list[dict], price: str, capacity: int, image_url: str = None) -> dict:
    bio_html = f"<p>{bio_text.strip()}</p>" if bio_text.strip() else "<p>Live stand-up comedy and events at Sisyphus Brewing.</p>"
    body_html = VENUE_DISCLAIMER_HTML.format(bio_html=bio_html)

    product_variants = []
    for idx, v in enumerate(variants):
        sku_date = v['datetime'].strftime('%m%d%H%M') if 'datetime' in v else str(idx)
        sku = f"SISY-{re.sub(r'[^A-Z0-9]', '', comedian_name.upper())[:8]}-{sku_date}"

        product_variants.append({
            "option1": v["title"],
            "price": price,
            "sku": sku,
            "inventory_management": "shopify",
            "inventory_policy": "deny",
            "requires_shipping": False,   # 100% Digital / Will-Call
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
    try:
        loc_resp = requests.get(f"https://{store}/admin/api/2024-01/locations.json", headers=headers, timeout=15)
        if loc_resp.status_code != 200:
            return
        locations = loc_resp.json().get("locations", [])
        if not locations:
            return
        location_id = locations[0]["id"]

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
    handle = created_product.get("handle")
    live_url = f"https://{store}/products/{handle}"

    print(f"✓ Successfully published! Live at: {live_url}")

    for v in created_product.get("variants", []):
        set_variant_inventory(store, headers, v.get("id"), v.get("inventory_item_id"), capacity)

    print(f"✓ Set inventory capacity to {capacity} per showtime/ticket option.")
    return created_product


def main():
    print("==========================================================")
    print("  SISYPHUS BREWING • FLEXIBLE SHOPIFY TICKET BUILDER     ")
    print("==========================================================")

    # Check environment input (GitHub Actions Web Form)
    title = os.environ.get("SHOW_TITLE", "").strip()

    if title:
        showtimes_raw = os.environ.get("SHOWTIMES_INPUT") or os.environ.get("SHOW_LAYOUT") or "Oct 24 7pm"
        price = os.environ.get("SHOW_PRICE", DEFAULT_TICKET_PRICE).replace("$", "").strip() or DEFAULT_TICKET_PRICE
        capacity = int(os.environ.get("SHOW_CAPACITY", DEFAULT_ROOM_CAPACITY) or DEFAULT_ROOM_CAPACITY)
        bio = os.environ.get("SHOW_BIO", "").strip()
        image_url = os.environ.get("SHOW_IMAGE_URL", "").strip()

        variants = parse_freeform_showtimes(showtimes_raw)
        if not variants:
            variants = [{"title": "General Admission", "datetime": datetime.now(CENTRAL_TZ)}]

        print(f"Title: {title}")
        print(f"Price: ${price} | Capacity per slot: {capacity}")
        print("Generated Variants:")
        for v in variants:
            print(f"  • {v['title']}")

        payload = build_shopify_product_payload(title, bio, variants, price, capacity, image_url)
        publish_to_shopify(payload, capacity)
        return

    # Interactive Terminal fallback
    comedian = input("\nEvent / Comedian / Show Title: ").strip()
    if not comedian:
        print("Title is required.")
        return

    price = input(f"Ticket Price (USD) [default: ${DEFAULT_TICKET_PRICE}]: ").strip() or DEFAULT_TICKET_PRICE
    price = price.replace("$", "").strip()

    capacity_in = input(f"Room Capacity / Ticket Limit [default: {DEFAULT_ROOM_CAPACITY}]: ").strip()
    capacity = int(capacity_in) if capacity_in.isdigit() else DEFAULT_ROOM_CAPACITY

    print("\nEnter showtimes, dates, or pass names (comma-separated):")
    print("  Examples: 'Oct 11 5pm' OR 'Oct 24 7pm, Oct 24 9pm' OR 'Full 5-Week Pass'")
    showtimes_in = input("Showtimes: ").strip() or "Oct 24 7pm"

    variants = parse_freeform_showtimes(showtimes_in)

    print("\nEnter bio / event description (Press Enter, then Ctrl+D or Ctrl+Z to finish):")
    bio_lines = []
    try:
        while True:
            bio_lines.append(input())
    except EOFError:
        pass
    bio = "\n".join(bio_lines).strip()

    image_url = input("\nPromo Image URL (optional, press Enter to skip): ").strip()

    payload = build_shopify_product_payload(comedian, bio, variants, price, capacity, image_url)
    publish_to_shopify(payload, capacity)


if __name__ == "__main__":
    main()
