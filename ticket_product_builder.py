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
<hr style="margin: 16px 0; border: none; border-top: 1px solid #e2e8f0;"/>
{bio_html}
<hr style="margin: 16px 0; border: none; border-top: 1px solid #e2e8f0;"/>
<p style="font-size: 0.9em; color: #64748b; line-height: 1.5;">
<strong>Venue Information & Policies:</strong><br/>
• Sisyphus Brewing Comedy Club & Taproom (712 Ontario Ave W, Minneapolis, MN).<br/>
• Must be 18+ to attend comedy shows.<br/>
• All sales are final unless the event is cancelled or rescheduled.<br/>
• You will receive an email confirmation upon purchase. Just give your name at the door upon arrival.
</p>
""".strip()


def format_bio_html(bio_text: str) -> str:
    """
    Preserves text formatting, multiple paragraphs, and bullet points.
    Converts raw double newlines into clean semantic <p> blocks and
    dashed/bulleted lines into proper <ul><li> HTML lists.
    """
    if not bio_text or not bio_text.strip():
        return "<p>Live stand-up comedy and events at Sisyphus Brewing.</p>"

    clean = bio_text.strip()

    # If it already contains HTML tags from the web creator, preserve directly
    if "<p>" in clean or "<div>" in clean or "<br" in clean or "<ul>" in clean:
        return clean

    paragraphs = re.split(r'\n\s*\n', clean)
    html_blocks = []

    for para in paragraphs:
        lines = [line.strip() for line in para.split('\n') if line.strip()]
        if not lines:
            continue

        # Check if this paragraph is a bulleted list
        if all(re.match(r'^[-*•]\s+', l) for l in lines):
            items = "".join(f"<li>{re.sub(r'^[-*•]\s+', '', l)}</li>" for l in lines)
            html_blocks.append(f"<ul style='margin: 8px 0; padding-left: 20px; line-height: 1.6;'>{items}</ul>")
        else:
            para_content = "<br/>".join(lines)
            html_blocks.append(f"<p style='margin-bottom: 14px; line-height: 1.6;'>{para_content}</p>")

    return "\n".join(html_blocks)


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
    bio_html = format_bio_html(bio_text)
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


def check_and_process_supabase_queue():
    """
    Checks if there are pending shows created via the web app in Supabase
    and processes them directly into Shopify.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        return False

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    try:
        url = f"{supabase_url.rstrip('/')}/rest/v1/show_queue?status=eq.pending&order=created_at.asc&limit=1"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return False

        jobs = resp.json() or []
        if not jobs:
            return False

        job = jobs[0]
        job_id = job.get("id")
        title = job.get("title")
        showtimes_raw = job.get("showtimes") or "Oct 24 7pm"
        price = str(job.get("price") or DEFAULT_TICKET_PRICE)
        capacity = int(job.get("capacity") or DEFAULT_ROOM_CAPACITY)
        bio_html = job.get("bio_html") or ""
        image_url = job.get("image_url") or ""

        print(f"\n[Supabase Queue] Found pending show: '{title}'")
        variants = parse_freeform_showtimes(showtimes_raw)
        payload = build_shopify_product_payload(title, bio_html, variants, price, capacity, image_url)
        publish_to_shopify(payload, capacity)

        # Mark completed
        patch_url = f"{supabase_url.rstrip('/')}/rest/v1/show_queue?id=eq.{job_id}"
        requests.patch(patch_url, headers=headers, json={"status": "published"}, timeout=15)
        print(f"[Supabase Queue] Successfully processed show '{title}'.")
        return True
    except Exception as e:
        print(f"[Supabase Queue] Notice: {e}")
        return False


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


def auto_sort_collection_chronologically(store: str, headers: dict, collection_handle: str = "comedy-and-events"):
    """
    Finds the comedy collection and automatically rearranges all show products 
    in true chronological order (closest upcoming show at the top).
    """
    print(f"\n--- Chronologically Sorting Collection: '{collection_handle}' ---")
    graphql_url = f"https://{store}/admin/api/2024-01/graphql.json"

    # 1. Fetch collection products and their variant showtimes
    query = """
    query getComedyCollection {
      collections(first: 20) {
        nodes {
          id
          title
          handle
          sortOrder
          products(first: 100) {
            nodes {
              id
              title
              variants(first: 20) {
                nodes {
                  title
                }
              }
            }
          }
        }
      }
    }
    """

    try:
        resp = requests.post(graphql_url, headers=headers, json={"query": query}, timeout=20)
        if resp.status_code != 200:
            print(f"Could not query collection for sorting ({resp.status_code}): {resp.text}")
            return

        data = resp.json().get("data", {})
        collections = data.get("collections", {}).get("nodes", [])

        # Locate the comedy collection
        target_collection = None
        for col in collections:
            if col.get("handle") == collection_handle or "comedy" in col.get("title", "").lower():
                target_collection = col
                break

        if not target_collection:
            print(f"Collection '{collection_handle}' not found in Shopify. Skipping auto-sort.")
            return

        collection_id = target_collection["id"]
        products = target_collection.get("products", {}).get("nodes", [])

        if not products:
            print("No products currently in the collection to sort.")
            return

        # 2. Ensure collection sortOrder is set to MANUAL so custom order takes effect
        if target_collection.get("sortOrder") != "MANUAL":
            update_mutation = """
            mutation makeCollectionManual($input: CollectionInput!) {
              collectionUpdate(input: $input) {
                collection {
                  id
                  sortOrder
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """
            requests.post(graphql_url, headers=headers, json={
                "query": update_mutation,
                "variables": {"input": {"id": collection_id, "sortOrder": "MANUAL"}}
            }, timeout=15)

        # 3. Determine earliest show date for every product in the collection
        parsed_products = []
        now = datetime.now(CENTRAL_TZ)
        future_boundary = datetime.max.replace(tzinfo=CENTRAL_TZ)

        for prod in products:
            p_id = prod["id"]
            p_title = prod["title"]
            earliest_dt = future_boundary

            # Check variant dates
            for v in prod.get("variants", {}).get("nodes", []):
                v_title = v.get("title", "")
                dt = parse_single_datetime(v_title)
                if dt and dt < earliest_dt:
                    earliest_dt = dt

            # If not in variants, check product title
            if earliest_dt == future_boundary:
                dt_title = parse_single_datetime(p_title)
                if dt_title:
                    earliest_dt = dt_title

            parsed_products.append({
                "id": p_id,
                "title": p_title,
                "dt": earliest_dt
            })

        # Sort products: earliest upcoming shows first, non-dated items at bottom
        parsed_products.sort(key=lambda p: p["dt"])

        print("Target Chronological Order on Live Store:")
        moves = []
        for idx, p in enumerate(parsed_products):
            date_label = p["dt"].strftime("%b %-d, %Y") if p["dt"] != future_boundary else "Non-dated/Pass"
            print(f"  {idx + 1}. {p['title']} ({date_label})")
            moves.append({
                "id": p["id"],
                "newPosition": str(idx)
            })

        # 4. Apply reordering to Shopify
        reorder_mutation = """
        mutation reorderProducts($id: ID!, $moves: [MoveInput!]!) {
          collectionReorderProducts(id: $id, moves: $moves) {
            job {
              id
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        reorder_resp = requests.post(graphql_url, headers=headers, json={
            "query": reorder_mutation,
            "variables": {
                "id": collection_id,
                "moves": moves
            }
        }, timeout=20)

        if reorder_resp.status_code == 200:
            print("✓ Successfully sorted collection chronologically on your live store!")
        else:
            print(f"Reorder API response ({reorder_resp.status_code}): {reorder_resp.text}")

    except Exception as e:
        print(f"Notice: Auto-sort encountered an exception: {e}")


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

    # Automatically re-sort the comedy collection so the new show slots in chronologically!
    import time
    time.sleep(2)  # Give Shopify 2 seconds to index the newly created product
    auto_sort_collection_chronologically(store, headers)

    return created_product


def main():
    print("==========================================================")
    print("  SISYPHUS BREWING • FLEXIBLE SHOPIFY TICKET BUILDER     ")
    print("==========================================================")

    # 1. First check if a show was queued from the Web App via Supabase
    if check_and_process_supabase_queue():
        return

    # 2. Check environment input (GitHub Actions Web Form)
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

    # 3. Interactive Terminal fallback
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
