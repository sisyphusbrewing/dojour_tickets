import os
import re
import json
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

CENTRAL_TZ = ZoneInfo("America/Chicago")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Dojour Ticket Counts")
TAB_NAME = "Door List"
HEADERS = [
    "Unique ID", "Show Date", "Show Title", "Guest Name",
    "Email", "Tickets", "Source", "Checked In", "Check-In Time"
]

DOJOUR_RESERVATIONS_URL = "https://dojour.us/admin-tools/reservations/all/?upcoming=true"

# ==========================================
# 1. SHOPIFY INTEGRATION (WORKING)
# ==========================================

def get_shopify_access_token(shop: str, client_id: str, client_secret: str) -> str:
    if client_secret.startswith("shpat_"):
        return client_secret

    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }
    resp = requests.post(token_url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]

def parse_shopify_line_item(item: dict) -> tuple[str, str]:
    title = (item.get("title") or "").strip()
    variant = (item.get("variant_title") or "").strip()

    properties = {p.get("name", ""): p.get("value", "") for p in item.get("properties", [])}
    prop_date = properties.get("Show Date") or properties.get("Date") or properties.get("Showtime") or properties.get("Time")
    if prop_date:
        return title, prop_date

    date_markers = ["•", "PM", "AM", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if any(m in variant for m in date_markers):
        return title, variant

    if " - " in title:
        parts = title.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    if " • " in title:
        parts = title.split(" • ", 1)
        return parts[0].strip(), parts[1].strip()

    show_date = variant if variant and variant.lower() != "default title" else "TBD"
    return title, show_date

def fetch_shopify_tickets() -> list[list]:
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "371d53e3029e519f2e32dfde3eebff14")
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "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")
    shop = os.environ.get("SHOPIFY_STORE", "sisyphus-brewing.myshopify.com")

    if not client_id or not client_secret:
        print("[Shopify] Missing credentials, skipping Shopify sync.")
        return []

    token = get_shopify_access_token(shop, client_id, client_secret)
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    url = f"https://{shop}/admin/api/2024-04/orders.json?status=any&limit=250"
    shopify_rows = []
    ignored_patterns = [r"\bticket fee\b", r"\btip\b", r"\bgratuity\b", r"\bdonation\b", r"\bdeposit\b", r"\bservice fee\b"]
    total_orders_seen = 0

    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        orders = data.get("orders", [])
        total_orders_seen += len(orders)

        for order in orders:
            if order.get("cancelled_at"):
                continue
            if order.get("financial_status") not in ("paid", "authorized"):
                continue

            order_num = str(order.get("order_number") or order.get("id"))
            customer = order.get("customer") or {}
            first_name = customer.get("first_name") or order.get("billing_address", {}).get("first_name") or ""
            last_name = customer.get("last_name") or order.get("billing_address", {}).get("last_name") or ""
            guest_name = f"{first_name} {last_name}".strip()
            if not guest_name:
                guest_name = order.get("billing_address", {}).get("name") or "Shopify Guest"

            email = (order.get("email") or customer.get("email") or "").strip().lower()

            for item in order.get("line_items", []):
                raw_title = item.get("title", "")
                lower_title = raw_title.lower()

                if lower_title == "fee" or any(re.search(pat, lower_title) for pat in ignored_patterns):
                    continue

                show_title, show_date = parse_shopify_line_item(item)
                item_id = str(item.get("id"))
                tickets = int(item.get("quantity", 1))
                unique_id = f"shopify_{order_num}_{item_id}"

                shopify_rows.append([
                    unique_id,
                    show_date,
                    show_title,
                    guest_name,
                    email,
                    tickets,
                    "Website",
                    False,
                    ""
                ])

        link_header = resp.headers.get("Link")
        url = None
        if link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                url = match.group(1)

    print(f"[Shopify] Scanned {total_orders_seen} orders, extracted {len(shopify_rows)} ticket lines.")
    return shopify_rows

# ==========================================
# 2. DOJOUR INTEGRATION
# ==========================================

def clean_dojour_title(raw_title: str) -> str:
    cleaned = re.sub(r"\d+/\d+.*?(spots left|remaining)?", "", raw_title, flags=re.IGNORECASE)
    cleaned = cleaned.split("///")[0]
    return re.sub(r"\s+", " ", cleaned).strip()

def format_dojour_date(raw_date_str: str) -> str:
    if not raw_date_str:
        return "TBD"

    try:
        dt = datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))
        dt_central = dt.astimezone(CENTRAL_TZ)
        return dt_central.strftime("%a, %b %-d • %-I:%M %p")
    except Exception:
        for fmt in ["%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M:%S", "%a, %b %d, %Y %I:%M %p"]:
            try:
                dt = datetime.strptime(raw_date_str.strip(), fmt)
                dt_central = dt.replace(tzinfo=CENTRAL_TZ) if not dt.tzinfo else dt.astimezone(CENTRAL_TZ)
                return dt_central.strftime("%a, %b %-d • %-I:%M %p")
            except Exception:
                continue
        return raw_date_str.strip()

def extract_instance_id_from_href(href: str) -> str | None:
    if not href:
        return None
    m = re.search(r"(?:event_instances|instances|reservations/s|reservations)/(\d+)", href)
    if m:
        return m.group(1)
    nums = re.findall(r"\d{4,}", href)
    return nums[-1] if nums else None

def extract_event_meta(data: dict | list, fallback_text: str) -> tuple[str, str]:
    title = ""
    if isinstance(data, dict):
        title = data.get("event_title") or data.get("title")
        if not title and isinstance(data.get("event"), dict):
            title = data["event"].get("title")
        if not title and isinstance(data.get("event_instance"), dict):
            title = data["event_instance"].get("title")
    if not title:
        title = fallback_text.split("\n")[0]
    show_title = clean_dojour_title(title)

    raw_time = ""
    if isinstance(data, dict):
        raw_time = (
            data.get("starts_at") or
            data.get("start_time") or
            data.get("start") or
            data.get("date")
        )
        if not raw_time and isinstance(data.get("event_instance"), dict):
            raw_time = data["event_instance"].get("starts_at") or data["event_instance"].get("start_time")
        if not raw_time and isinstance(data.get("event"), dict):
            raw_time = data["event"].get("starts_at") or data["event"].get("start_time")

    if raw_time:
        show_date = format_dojour_date(str(raw_time))
    else:
        date_match = re.search(r"([A-Za-z]+\s+\d{1,2}(?:\s*&\s*\d{1,2})?(?:,\s*\d{4})?)", fallback_text)
        show_date = date_match.group(1).strip() if date_match else "TBD"

    return show_title, show_date

def parse_reservations_from_payload(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    priority_keys = [
        "reserves", "reservations", "reserve_report", "reports", "report",
        "attendees", "guests", "guest_list", "guestlist", "ticket_holders",
        "tickets", "rsvps", "orders", "results", "items", "data"
    ]
    for key in priority_keys:
        val = data.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            nested = parse_reservations_from_payload(val)
            if nested:
                return nested

    for key, val in data.items():
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
            first = val[0]
            if any(k in first for k in ("name", "first_name", "last_name", "email", "ticket_count", "quantity", "tickets", "spots")):
                return val

    return []

def parse_guest_record(res: dict, instance_id: str, index: int, show_date: str, show_title: str) -> list:
    res_id = str(
        res.get("id") or
        res.get("reservation_id") or
        res.get("reserve_id") or
        res.get("pk") or
        index
    )
    unique_id = f"dj_{instance_id}_{res_id}"

    # Name
    name = res.get("name") or res.get("guest_name") or res.get("full_name") or ""
    if not name:
        fname = res.get("first_name") or res.get("firstname") or ""
        lname = res.get("last_name") or res.get("lastname") or ""
        name = f"{fname} {lname}".strip()
    if not name and isinstance(res.get("user"), dict):
        u = res["user"]
        name = u.get("name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
    if not name:
        name = "Dojour Guest"

    # Email
    email = res.get("email") or res.get("guest_email") or ""
    if not email and isinstance(res.get("user"), dict):
        email = res["user"].get("email") or ""
    email = email.strip().lower()

    # Tickets
    tickets = (
        res.get("ticket_count") or
        res.get("quantity") or
        res.get("tickets") or
        res.get("count") or
        res.get("spots") or
        res.get("num_tickets") or
        1
    )
    try:
        tickets = int(tickets)
    except (ValueError, TypeError):
        tickets = 1

    return [
        unique_id,
        show_date,
        show_title,
        name.strip(),
        email,
        tickets,
        "Dojour",
        False,
        ""
    ]

def extract_dojour_token(storage_state: dict) -> str | None:
    # 1. From usertoken cookie
    for cookie in storage_state.get("cookies", []):
        if cookie.get("name") == "usertoken":
            token = cookie.get("value", "").strip('"').strip("'")
            if token:
                return token
    return None

def fetch_dojour_tickets_with_session(token: str, schedules: list[dict]) -> list[list]:
    """
    Directly fetches all reservation reports via HTTP using Dojour's Token Authentication.
    """
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "Referer": "https://dojour.us/admin-tools/reservations/all/?upcoming=true",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })

    dojour_rows = []
    logged_first = False

    for idx, item in enumerate(schedules):
        instance_id = item["instance_id"]
        report_url = item["report_url"]

        try:
            resp = session.get(report_url, timeout=15)
        except Exception as e:
            print(f"[Dojour] Network error for schedule {instance_id}: {e}")
            continue

        if resp.status_code != 200:
            if idx < 3:
                print(f"[Dojour] HTTP {resp.status_code} fetching report for schedule {instance_id}")
            continue

        try:
            data = resp.json()
        except Exception:
            continue

        if not logged_first:
            keys = list(data.keys()) if isinstance(data, dict) else f"list(len={len(data)})"
            print(f"[Dojour Debug] Sample schedule {instance_id} JSON structure: {keys}")
            logged_first = True

        show_title, show_date = extract_event_meta(data, item["raw_text"])
        reservations = parse_reservations_from_payload(data)

        for i, res in enumerate(reservations):
            row = parse_guest_record(res, instance_id, i, show_date, show_title)
            dojour_rows.append(row)

    print(f"[Dojour] Extracted {len(dojour_rows)} total reservations across {len(schedules)} schedules.")
    return dojour_rows

def discover_schedules_playwright(context) -> tuple[list[dict], str | None]:
    page = context.new_page()
    page.set_viewport_size({"width": 1920, "height": 1080})

    captured_token = None

    def on_request(req):
        nonlocal captured_token
        auth_header = req.headers.get("authorization")
        if auth_header and "Token " in auth_header and not captured_token:
            captured_token = auth_header.replace("Token ", "").strip()

    page.on("request", on_request)
    page.goto(DOJOUR_RESERVATIONS_URL, wait_until="networkidle")

    # Expand list
    prev_discovered = 0
    no_growth_count = 0

    for attempt in range(1, 20):
        # Click "Load More"
        for sel in ["button:has-text('Load More')", "a:has-text('Load More')", ".load-more"]:
            elem = page.locator(sel).first
            if elem.count() and elem.is_visible():
                try:
                    elem.click(timeout=1500)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    pass

        rows = page.locator("tr, div.reservation-row, [role='row']").all()
        if rows:
            try:
                rows[-1].scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass

        page.evaluate("""() => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight > el.clientHeight && el.clientHeight > 50) {
                    el.scrollTop = el.scrollHeight;
                    el.dispatchEvent(new Event('scroll', { bubbles: true }));
                }
            });
        }""")
        page.wait_for_timeout(1000)

        # Count schedules
        current_rows = len(page.locator("tr, div.reservation-row, [role='row']").all())
        if current_rows > prev_discovered:
            prev_discovered = current_rows
            no_growth_count = 0
        else:
            no_growth_count += 1
            if no_growth_count >= 3:
                break

    # Extract schedule info
    schedules_by_id = {}
    for row in page.locator("tr, div.reservation-row, [role='row']").all():
        row_text = row.inner_text()
        for link in row.locator("a").all():
            href = link.get_attribute("href") or ""
            link_text = link.inner_text()
            inst_id = extract_instance_id_from_href(href)
            if inst_id and ("reservations" in href or "spots" in link_text or "/" in link_text):
                if inst_id not in schedules_by_id:
                    schedules_by_id[inst_id] = {
                        "instance_id": inst_id,
                        "raw_text": row_text,
                        "report_url": f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
                    }

    page.close()
    print(f"[Dojour] Discovered {len(schedules_by_id)} upcoming schedules.")
    return list(schedules_by_id.values()), captured_token

# ==========================================
# 3. GOOGLE SHEETS STATE-PRESERVING SYNC
# ==========================================

def sync_to_google_sheet(new_rows: list[list]):
    sa_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    if not sa_env:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT secret.")

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if os.path.isfile(sa_env):
        creds = Credentials.from_service_account_file(sa_env, scopes=scopes)
    else:
        creds = Credentials.from_service_account_info(json.loads(sa_env), scopes=scopes)

    client = gspread.authorize(creds)
    sheet_id = os.environ.get("SPREADSHEET_ID")
    spreadsheet = client.open_by_key(sheet_id) if sheet_id else client.open(SHEET_NAME)
    worksheet = spreadsheet.worksheet(TAB_NAME)

    existing_records = worksheet.get_all_values()
    check_in_memory = {}

    if len(existing_records) > 1:
        for row in existing_records[1:]:
            if len(row) >= 9:
                u_id = row[0].strip()
                checked_in = row[7].strip().upper() == "TRUE"
                check_in_time = row[8].strip()
                check_in_memory[u_id] = (checked_in, check_in_time)

    final_rows = [HEADERS]
    for row in new_rows:
        if len(row) != 9:
            row = (row + [""] * 9)[:9]

        u_id = row[0].strip()
        if u_id in check_in_memory:
            preserved_status, preserved_time = check_in_memory[u_id]
            row[7] = preserved_status
            row[8] = preserved_time

        final_rows.append(row)

    worksheet.clear()
    worksheet.update(values=final_rows, range_name="A1", value_input_option="USER_ENTERED")
    print(f"[Google Sheets] Updated '{TAB_NAME}' with {len(final_rows) - 1} records.")

# ==========================================
# 4. MAIN ORCHESTRATOR
# ==========================================

def main():
    # 1. Fetch Shopify Tickets
    shopify_rows = fetch_shopify_tickets()

    # 2. Fetch Dojour Tickets
    dojour_state = os.environ.get("DOJOUR_STATE")
    dojour_rows = []

    if dojour_state:
        try:
            storage_state = json.loads(dojour_state)
        except Exception:
            storage_state = dojour_state

        token = extract_dojour_token(storage_state) if isinstance(storage_state, dict) else None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state)
            schedules, captured_token = discover_schedules_playwright(context)
            browser.close()

        active_token = captured_token or token
        if active_token:
            print(f"[Dojour] Authenticating using Token: {active_token[:8]}...")
            dojour_rows = fetch_dojour_tickets_with_session(active_token, schedules)
        else:
            print("[Dojour] ERROR: Could not resolve Dojour auth token.")
    else:
        print("[Dojour] Warning: DOJOUR_STATE is missing.")

    # 3. Consolidate and Sync to Google Sheet
    all_rows = shopify_rows + dojour_rows
    sync_to_google_sheet(all_rows)

if __name__ == "__main__":
    main()
