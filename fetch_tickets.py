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

# ==========================================
# 1. SHOPIFY INTEGRATION
# ==========================================

def get_shopify_access_token(shop: str, client_id: str, client_secret: str) -> str:
    """
    Exchanges Client Credentials for an Admin API access token.
    If client_secret is already an access token (shpat_), returns it directly.
    """
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
    """
    Extracts clean performer name and show date from item title, variant, or properties.
    """
    title = (item.get("title") or "").strip()
    variant = (item.get("variant_title") or "").strip()

    # Check custom line item properties first
    properties = {p.get("name", ""): p.get("value", "") for p in item.get("properties", [])}
    prop_date = properties.get("Show Date") or properties.get("Date") or properties.get("Showtime") or properties.get("Time")
    if prop_date:
        return title, prop_date

    # Variant contains date indicators (e.g. 'Fri, Sep 18 • 7:00 PM')
    date_markers = ["•", "PM", "AM", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if any(m in variant for m in date_markers):
        return title, variant

    # Split combined titles (e.g. 'Alex Dragicevich - Fri, Sep 18 • 7:00 PM')
    if " - " in title:
        parts = title.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    if " • " in title:
        parts = title.split(" • ", 1)
        return parts[0].strip(), parts[1].strip()

    show_date = variant if variant and variant.lower() != "default title" else "TBD"
    return title, show_date

def fetch_shopify_tickets() -> list[list]:
    """
    Retrieves paid Shopify orders, filters out fee add-ons, and returns 9-column rows.
    """
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

    url = f"https://{shop}/admin/api/2024-04/orders.json?status=open&financial_status=paid&limit=250"
    shopify_rows = []
    ignored_addons = {"ticket fee", "fee", "tip", "gratuity", "donation", "deposit", "service fee"}

    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        orders = data.get("orders", [])

        for order in orders:
            if order.get("cancelled_at"):
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
                if any(addon in raw_title.lower() for addon in ignored_addons):
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

        # Follow cursor pagination via Link header
        link_header = resp.headers.get("Link")
        url = None
        if link_header:
            match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if match:
                url = match.group(1)

    print(f"[Shopify] Extracted {len(shopify_rows)} ticket lines.")
    return shopify_rows

# ==========================================
# 2. DOJOUR INTEGRATION
# ==========================================

def clean_dojour_title(raw_title: str) -> str:
    """
    Cleans Dojour title strings and strips ticket/capacity counts.
    """
    cleaned = re.sub(r"\d+/\d+.*?(spots left|remaining)?", "", raw_title, flags=re.IGNORECASE)
    cleaned = cleaned.split("///")[0]
    return re.sub(r"\s+", " ", cleaned).strip()

def format_dojour_date(raw_date_str: str) -> str:
    """
    Normalizes timestamps to Central Time: 'Fri, Sep 18 • 7:00 PM'.
    """
    if not raw_date_str:
        return "TBD"

    try:
        dt = datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))
        dt_central = dt.astimezone(CENTRAL_TZ)
        return dt_central.strftime("%a, %b %-d • %-I:%M %p")
    except Exception:
        try:
            dt = datetime.strptime(raw_date_str.strip(), "%b %d, %Y %I:%M %p")
            dt_central = dt.replace(tzinfo=CENTRAL_TZ)
            return dt_central.strftime("%a, %b %-d • %-I:%M %p")
        except Exception:
            return raw_date_str.strip()

def discover_all_schedules(page) -> list[dict]:
    """
    Overcomes the 9-schedule limit by continuously scrolling document and internal wrappers.
    """
    page.goto("https://dojour.us/admin-tools/reservations/", wait_until="networkidle")

    last_count = 0
    stable_cycles = 0

    while stable_cycles < 3:
        links = page.locator("a[href*='/api/event_instances/'], a[href*='/reserve_report/']").all()
        current_count = len(links)

        if current_count > last_count:
            last_count = current_count
            stable_cycles = 0
        else:
            stable_cycles += 1

        page.evaluate("""() => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('div, main, section, table').forEach(el => {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }""")
        page.wait_for_timeout(1000)

    schedules = []
    rows = page.locator("tr, div.reservation-row, .event-instance-row").all()

    for row in rows:
        text = row.inner_text()
        report_link = row.locator("a[href*='reserve_report']").first
        if not report_link.count():
            continue

        href = report_link.get_attribute("href")
        instance_match = re.search(r"/event_instances/(\d+)/", href)
        if not instance_match:
            continue

        instance_id = instance_match.group(1)
        schedules.append({
            "instance_id": instance_id,
            "raw_text": text,
            "report_url": f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/"
        })

    unique_schedules = {s["instance_id"]: s for s in schedules}.values()
    print(f"[Dojour] Discovered {len(unique_schedules)} unique schedules.")
    return list(unique_schedules)

def fetch_dojour_tickets(context) -> list[list]:
    """
    Extracts reservations from all discovered Dojour schedules into the 9-column schema.
    """
    page = context.new_page()
    schedules = discover_all_schedules(page)
    dojour_rows = []

    for item in schedules:
        report_url = item["report_url"]
        response = context.request.get(report_url)
        if response.status != 200:
            continue

        data = response.json()
        raw_title = data.get("event_title") or data.get("title") or item["raw_text"].split("\n")[0]
        show_title = clean_dojour_title(raw_title)

        raw_time = data.get("starts_at") or data.get("start_time") or ""
        show_date = format_dojour_date(raw_time)

        reservations = data if isinstance(data, list) else data.get("reservations", data.get("reports", []))

        for res in reservations:
            res_id = str(res.get("id") or res.get("reservation_id") or "")
            unique_id = f"dj_{item['instance_id']}_{res_id}"

            name = (res.get("name") or f"{res.get('first_name', '')} {res.get('last_name', '')}").strip()
            email = (res.get("email") or "").strip().lower()
            tickets = int(res.get("ticket_count") or res.get("quantity") or 1)

            dojour_rows.append([
                unique_id,
                show_date,
                show_title,
                name,
                email,
                tickets,
                "Dojour",
                False,
                ""
            ])

    page.close()
    print(f"[Dojour] Extracted {len(dojour_rows)} reservations.")
    return dojour_rows

# ==========================================
# 3. GOOGLE SHEETS STATE-PRESERVING SYNC
# ==========================================

def sync_to_google_sheet(new_rows: list[list]):
    """
    Loads existing data, preserves Columns H (Checked In) and I (Check-In Time),
    and atomically refreshes the 'Door List' worksheet.
    """
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

    # 1. Fetch current rows to preserve door check-in states
    existing_records = worksheet.get_all_values()
    check_in_memory = {}

    if len(existing_records) > 1:
        for row in existing_records[1:]:
            if len(row) >= 9:
                u_id = row[0].strip()
                checked_in = row[7].strip().upper() == "TRUE"
                check_in_time = row[8].strip()
                check_in_memory[u_id] = (checked_in, check_in_time)

    # 2. Reconcile check-in data into the newly scraped rows
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

    # 3. Overwrite sheet atomically
    worksheet.clear()
    worksheet.update(final_rows, "A1", value_input_option="USER_ENTERED")
    print(f"[Google Sheets] Updated '{TAB_NAME}' with {len(final_rows) - 1} records.")

# ==========================================
# 4. MAIN ORCHESTRATOR
# ==========================================

def main():
    # 1. Fetch Shopify ticket records
    shopify_rows = fetch_shopify_tickets()

    # 2. Fetch Dojour ticket records
    dojour_state = os.environ.get("DOJOUR_STATE")
    dojour_rows = []

    if dojour_state:
        try:
            storage_state = json.loads(dojour_state)
        except Exception:
            storage_state = dojour_state

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state)
            dojour_rows = fetch_dojour_tickets(context)
            browser.close()
    else:
        print("[Dojour] Warning: DOJOUR_STATE is missing. Skipping Dojour extraction.")

    # 3. Consolidate and sync
    all_rows = shopify_rows + dojour_rows
    sync_to_google_sheet(all_rows)

if __name__ == "__main__":
    main()
