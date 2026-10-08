import os
import sys
import re
import json
from datetime import datetime, timedelta
import requests

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
RAW_SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co"
SUPABASE_URL = RAW_SUPABASE_URL.replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE") or os.environ.get("SHOPIFY_SHOP", "")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN") or os.environ.get("SHOPIFY_PASSWORD", "")

DOJOUR_API_KEY = os.environ.get("DOJOUR_API_KEY") or os.environ.get("DOJOUR_TOKEN", "")
DOJOUR_ORG_ID = os.environ.get("DOJOUR_ORG_ID") or os.environ.get("DOJOUR_ORGANIZER_ID", "sisyphus-brewing")

GOOGLE_SHEET_WEBHOOK_URL = os.environ.get("GOOGLE_SHEET_WEBHOOK_URL", "")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

GRACE_PERIOD_SECONDS = 12 * 3600  # 12 hours after showtime before marking past

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

def parse_show_date_to_timestamp(date_str, now=None):
    if not date_str:
        return 0
    if now is None:
        now = datetime.now()

    # 1. Attempt ISO format
    try:
        if "T" in str(date_str):
            clean_iso = str(date_str).replace("Z", "+00:00")
            return datetime.fromisoformat(clean_iso).timestamp()
    except Exception:
        pass

    clean_str = str(date_str)
    m_match = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b', clean_str, re.I)
    d_match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', clean_str)
    y_match = re.search(r'\b(202\d)\b', clean_str)
    t_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', clean_str, re.I)

    if not m_match or not d_match:
        return 0

    month_str = m_match.group(1).lower()[:3]
    month_idx = MONTH_MAP.get(month_str, 1)
    day = int(d_match.group(1))

    hour = 19
    minute = 0
    if t_match:
        hour = int(t_match.group(1))
        minute = int(t_match.group(2)) if t_match.group(2) else 0
        ampm = t_match.group(3).upper()
        if ampm == 'PM' and hour < 12: hour += 12
        if ampm == 'AM' and hour == 12: hour = 0

    if y_match:
        year = int(y_match.group(1))
    else:
        year = now.year
        try:
            candidate = datetime(year, month_idx, day, hour, minute)
            # If the candidate date is more than 45 days in the past, it represents next year's show!
            # (e.g., today is October, show is in April: 6 months in the past -> must be next April)
            if (now - candidate).days > 45:
                year += 1
        except ValueError:
            pass

    try:
        return datetime(year, month_idx, day, hour, minute).timestamp()
    except Exception:
        return 0

def fetch_shopify_tickets():
    if not SHOPIFY_STORE or not SHOPIFY_ACCESS_TOKEN:
        print("Shopify credentials not configured.")
        return []

    store = SHOPIFY_STORE.replace("https://", "").replace("http://", "").rstrip("/")
    if not store.endswith(".myshopify.com") and "." not in store:
        store = f"{store}.myshopify.com"

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    # Fetch orders with status=any and paginate through all pages
    url = f"https://{store}/admin/api/2023-10/orders.json?status=any&limit=250"
    all_orders = []

    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"Shopify API error ({resp.status_code}): {resp.text}")
                break
            data = resp.json()
            orders = data.get("orders", [])
            all_orders.extend(orders)

            # Follow cursor pagination via Link header
            link_header = resp.headers.get("Link", "")
            next_url = None
            if link_header:
                links = link_header.split(",")
                for link in links:
                    if 'rel="next"' in link:
                        m = re.search(r'<([^>]+)>', link)
                        if m:
                            next_url = m.group(1)
                            break
            url = next_url
        except Exception as e:
            print(f"Exception fetching Shopify orders: {e}")
            break

    now = datetime.now()
    now_ts = now.timestamp()
    shopify_tickets = []

    for order in all_orders:
        if order.get("cancelled_at"):
            continue

        customer = order.get("customer") or {}
        first_name = (customer.get("first_name") or "").strip()
        last_name = (customer.get("last_name") or "").strip()
        guest_name = f"{first_name} {last_name}".strip()

        if not guest_name:
            shipping = order.get("shipping_address") or {}
            billing = order.get("billing_address") or {}
            guest_name = (shipping.get("name") or billing.get("name") or "").strip()

        if not guest_name:
            guest_name = order.get("name") or f"Guest #{order.get('id')}"

        email = (order.get("email") or customer.get("email") or "").strip()

        for item in order.get("line_items", []):
            quantity = int(item.get("quantity") or 1)
            product_title = (item.get("title") or "").strip()
            variant_title = (item.get("variant_title") or "").strip()
            item_name = (item.get("name") or "").strip()

            # Identify show title and show date
            show_title = product_title
            show_date = variant_title

            if not show_date or show_date.lower() == "default title":
                if " - " in item_name:
                    parts = item_name.split(" - ", 1)
                    show_title = parts[0].strip()
                    show_date = parts[1].strip()
                else:
                    show_date = product_title

            if not show_title or not show_date:
                continue

            ts = parse_show_date_to_timestamp(show_date, now)
            # Filter strictly upcoming shows (or within grace period)
            if ts and ts < (now_ts - GRACE_PERIOD_SECONDS):
                continue

            unique_id = f"shopify_{order.get('id')}_{item.get('id')}"
            shopify_tickets.append({
                "unique_id": unique_id,
                "show_title": show_title,
                "show_date": show_date,
                "guest_name": guest_name,
                "email": email,
                "tickets": quantity,
                "source": "Website"
            })

    print(f"Retrieved {len(shopify_tickets)} upcoming tickets from Shopify.")
    return shopify_tickets

def fetch_dojour_tickets():
    if not DOJOUR_ORG_ID:
        print("Dojour organizer ID not configured.")
        return []

    headers = {}
    if DOJOUR_API_KEY:
        headers["Authorization"] = f"Bearer {DOJOUR_API_KEY}"
        headers["Accept"] = "application/json"

    # 1. Fetch upcoming events
    events_url = f"https://api.dojour.us/organizations/{DOJOUR_ORG_ID}/events?status=upcoming"
    active_events = []
    try:
        resp = requests.get(events_url, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            active_events = data.get("events") or (data if isinstance(data, list) else [])
        else:
            alt_url = f"https://dojour.us/api/v1/organizations/{DOJOUR_ORG_ID}/events"
            resp2 = requests.get(alt_url, headers=headers, timeout=20)
            if resp2.status_code == 200:
                data2 = resp2.json()
                active_events = data2.get("events") or (data2 if isinstance(data2, list) else [])
    except Exception as e:
        print(f"Exception fetching Dojour events: {e}")

    print(f"Found {len(active_events)} upcoming active Dojour shows.")

    # 2. Fetch attendee reservations for each active show
    dojour_tickets = []
    now = datetime.now()
    now_ts = now.timestamp()

    for ev in active_events:
        event_id = ev.get("id")
        show_title = (ev.get("title") or ev.get("name") or "Dojour Event").strip()
        raw_date = ev.get("start_time") or ev.get("starts_at") or ev.get("date") or ""

        # Format readable show date if ISO
        ts = parse_show_date_to_timestamp(raw_date, now)
        if ts:
            dt = datetime.fromtimestamp(ts)
            show_date = dt.strftime("%a, %b %-d • %-I:%M %p")
        else:
            show_date = str(raw_date).strip()

        if ts and ts < (now_ts - GRACE_PERIOD_SECONDS):
            continue

        if not event_id:
            continue

        attendees_url = f"https://api.dojour.us/events/{event_id}/attendees"
        try:
            att_resp = requests.get(attendees_url, headers=headers, timeout=20)
            attendees = []
            if att_resp.status_code == 200:
                att_data = att_resp.json()
                attendees = att_data.get("attendees") or (att_data if isinstance(att_data, list) else [])

            for att in attendees:
                guest_name = (att.get("name") or att.get("guest_name") or "Dojour Guest").strip()
                email = (att.get("email") or "").strip()
                count = int(att.get("tickets") or att.get("quantity") or att.get("tickets_count") or 1)
                unique_id = f"dojour_{event_id}_{att.get('id', hash(guest_name + email))}"

                dojour_tickets.append({
                    "unique_id": unique_id,
                    "show_title": show_title,
                    "show_date": show_date,
                    "guest_name": guest_name,
                    "email": email,
                    "tickets": count,
                    "source": "Dojour"
                })
        except Exception as e:
            continue

    print(f"Retrieved {len(dojour_tickets)} upcoming Dojour attendee reservations.")
    return dojour_tickets

def upsert_to_supabase(records):
    if not records:
        print("No records to upsert.")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    # Batch in groups of 100
    batch_size = 100
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        url = f"{SUPABASE_URL}/rest/v1/tickets?on_conflict=unique_id"
        resp = requests.post(url, headers=headers, json=batch, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"Supabase upsert warning ({resp.status_code}): {resp.text}")

    print(f"Successfully upserted {len(records)} records into Supabase.")

def purge_past_shows():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    resp = requests.get(f"{SUPABASE_URL}/rest/v1/tickets?select=show_date,show_title", headers=headers, timeout=20)
    if resp.status_code != 200:
        return

    rows = resp.json() or []
    unique_shows = set()
    for r in rows:
        d = (r.get("show_date") or "").strip()
        t = (r.get("show_title") or "").strip()
        if d and t:
            unique_shows.add((d, t))

    now = datetime.now()
    now_ts = now.timestamp()
    stale_shows = []

    for d, t in unique_shows:
        ts = parse_show_date_to_timestamp(d, now)
        is_canceled = "canceled:" in t.lower() or "cancelled:" in t.lower()
        if is_canceled or (ts and ts < (now_ts - GRACE_PERIOD_SECONDS)):
            stale_shows.append((d, t))

    if stale_shows:
        print(f"Purging {len(stale_shows)} past/stale shows from Supabase...")
        for d, t in stale_shows:
            del_url = f"{SUPABASE_URL}/rest/v1/tickets?show_date=eq.{requests.utils.quote(d)}&show_title=eq.{requests.utils.quote(t)}"
            del_resp = requests.delete(del_url, headers=headers, timeout=15)
            if del_resp.status_code in (200, 204):
                print(f"  ✓ Purged past show: {d} • {t}")

def export_to_google_sheets(records):
    if not GOOGLE_SHEET_WEBHOOK_URL and not GOOGLE_SHEET_ID:
        print("Note: Set GOOGLE_SHEET_WEBHOOK_URL or GOOGLE_SHEET_ID to enable Google Sheets export.")
        return
    if GOOGLE_SHEET_WEBHOOK_URL:
        try:
            requests.post(GOOGLE_SHEET_WEBHOOK_URL, json={"tickets": records}, timeout=20)
        except Exception:
            pass

def main():
    print("Starting Sisyphus Ticket Consolidation to Supabase & Google Sheets...")

    # 1. Fetch from Shopify (status=any + full cursor pagination)
    shopify_tickets = fetch_shopify_tickets()

    # 2. Fetch from Dojour
    dojour_tickets = fetch_dojour_tickets()

    # 3. Consolidate
    consolidated = shopify_tickets + dojour_tickets
    print(f"Consolidated upcoming total: {len(consolidated)} tickets (strictly upcoming).")

    # 4. Upsert into Supabase
    upsert_to_supabase(consolidated)

    # 5. Export to Sheets
    export_to_google_sheets(consolidated)

    # 6. Purge past shows (with accurate year wrapping)
    purge_past_shows()

    print("Database and Sheet sync complete!")

if __name__ == "__main__":
    main()
