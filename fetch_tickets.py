import os
import re
import json
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
# 2. DOJOUR NORMALIZATION & EXTRACTION
# ==========================================

def clean_dojour_performer(raw_title: str) -> str:
    """
    Cleans raw Dojour titles:
    'Alex Dragicevich /// Comedy - September 18 & 19' -> 'Alex Dragicevich'
    'CANCELED: Emma Dalenberg /// Comedy - September 19' -> 'Emma Dalenberg'
    """
    t = raw_title.strip().lstrip("/").strip()
    t = re.sub(r"^(?:CANCELED|CANCELLED|POSTPONED)\s*:\s*", "", t, flags=re.IGNORECASE).strip()
    if "///" in t:
        t = t.split("///")[0].strip()
    if " - Comedy" in t or " ///" in t:
        t = re.split(r"\s+[-–—]\s+Comedy", t, flags=re.IGNORECASE)[0].strip()
    return t

def parse_dojour_datetime(date_str: str) -> str:
    """
    Normalizes strings like:
    'Saturday, September 19th | 7:00pm - 9:00pm'
    into:
    'Sat, Sep 19 • 7:00 PM'
    """
    if not date_str:
        return "TBD"

    cleaned = date_str.strip()

    # If already formatted, preserve it
    if re.match(r"^[A-Za-z]{3},\s+[A-Za-z]{3}\s+\d{1,2}\s+•\s+\d{1,2}:\d{2}\s+(?:AM|PM)$", cleaned):
        return cleaned

    # Strip ordinal suffixes: 1st, 2nd, 3rd, 19th, 20th
    cleaned_no_ord = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", cleaned)

    # Match: DayOfWeek, Month Day ... StartTime
    m = re.search(
        r"([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2})(?:,\s*(\d{4}))?\s*(?:[|\n\r•\t-]+)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))?",
        cleaned_no_ord,
        re.IGNORECASE
    )

    now = datetime.now()
    current_year = now.year

    if m:
        date_part = m.group(1).strip()
        year_part = m.group(2)
        time_part = m.group(3)

        if not time_part:
            tm = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))", cleaned_no_ord, re.IGNORECASE)
            time_part = tm.group(1) if tm else "7:00 PM"

        time_part = time_part.strip().upper()
        if ":" not in time_part:
            time_part = re.sub(r"(\d+)\s*(AM|PM)", r"\1:00 \2", time_part)
        else:
            time_part = re.sub(r"(\d+:\d{2})\s*(AM|PM)", r"\1 \2", time_part)

        if not year_part:
            try:
                month_name = date_part.split(",")[1].strip().split()[0]
                parsed_month = datetime.strptime(month_name, "%B").month
                year = current_year + 1 if parsed_month < now.month - 2 else current_year
            except Exception:
                year = current_year
        else:
            year = int(year_part)

        full_str = f"{date_part} {year} {time_part}"
        for fmt in ["%A, %B %d %Y %I:%M %p", "%A, %b %d %Y %I:%M %p"]:
            try:
                dt = datetime.strptime(full_str, fmt)
                dt_central = dt.replace(tzinfo=CENTRAL_TZ)
                return dt_central.strftime("%a, %b %-d • %-I:%M %p")
            except ValueError:
                continue

    # Fallback to ISO timestamps
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        dt_central = dt.astimezone(CENTRAL_TZ) if dt.tzinfo else dt.replace(tzinfo=CENTRAL_TZ)
        return dt_central.strftime("%a, %b %-d • %-I:%M %p")
    except Exception:
        pass

    return cleaned

def extract_instance_id_from_href(href: str) -> str | None:
    if not href:
        return None
    m = re.search(r"(?:event_instances|instances|reservations/s|reservations)/(\d+)", href)
    if m:
        return m.group(1)
    nums = re.findall(r"\d{4,}", href)
    return nums[-1] if nums else None

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
            if any(k in first for k in ("name", "first_name", "last_name", "email", "ticket_count", "quantity", "tickets")):
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

    email = res.get("email") or res.get("guest_email") or ""
    if not email and isinstance(res.get("user"), dict):
        email = res["user"].get("email") or ""
    email = email.strip().lower()

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

def discover_schedules_playwright(context) -> tuple[list[dict], str | None]:
    """
    Scrapes the upcoming table and extracts title and showtime from td[0] and td[1].
    """
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

    # Expand full list
    prev_count = 0
    no_growth = 0
    for _ in range(15):
        for sel in ["button:has-text('Load More')", "a:has-text('Load More')", ".load-more"]:
            elem = page.locator(sel).first
            if elem.count() and elem.is_visible():
                try:
                    elem.click(timeout=1500)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    pass

        rows = page.locator("tr, [role='row']").all()
        if rows:
            try:
                rows[-1].scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        current_count = len(rows)
        if current_count > prev_count:
            prev_count = current_count
            no_growth = 0
        else:
            no_growth += 1
            if no_growth >= 3:
                break

    schedules_by_id = {}
    for row in page.locator("tr, [role='row']").all():
        tds = row.locator("td").all()
        if len(tds) < 2:
            continue

        raw_title = tds[0].inner_text().strip()
        raw_date = tds[1].inner_text().strip()

        # Find schedule link (e.g. /admin-tools/reservations/s/79963)
        links = row.locator("a").all()
        inst_id = None
        for link in links:
            href = link.get_attribute("href") or ""
            inst_id = extract_instance_id_from_href(href)
            if inst_id:
                break

        if inst_id and inst_id not in schedules_by_id:
            show_title = clean_dojour_performer(raw_title)
            show_date = parse_dojour_datetime(raw_date)

            schedules_by_id[inst_id] = {
                "instance_id": inst_id,
                "show_title": show_title,
                "show_date": show_date,
                "report_url": f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
            }

    page.close()
    print(f"[Dojour] Discovered and parsed {len(schedules_by_id)} upcoming schedules.")
    return list(schedules_by_id.values()), captured_token

def fetch_dojour_tickets_with_session(token: str, schedules: list[dict]) -> list[list]:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "Referer": "https://dojour.us/admin-tools/reservations/all/?upcoming=true",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })

    dojour_rows = []
    for item in schedules:
        instance_id = item["instance_id"]
        report_url = item["report_url"]
        show_title = item["show_title"]
        show_date = item["show_date"]

        try:
            resp = session.get(report_url, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
        except Exception:
            continue

        reservations = parse_reservations_from_payload(data)
        for i, res in enumerate(reservations):
            row = parse_guest_record(res, instance_id, i, show_date, show_title)
            dojour_rows.append(row)

    print(f"[Dojour] Extracted {len(dojour_rows)} total reservations across {len(schedules)} schedules.")
    return dojour_rows

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
    shopify_rows = fetch_shopify_tickets()

    dojour_state = os.environ.get("DOJOUR_STATE")
    dojour_rows = []

    if dojour_state:
        try:
            storage_state = json.loads(dojour_state)
        except Exception:
            storage_state = dojour_state

        token = None
        if isinstance(storage_state, dict):
            for cookie in storage_state.get("cookies", []):
                if cookie.get("name") == "usertoken":
                    token = cookie.get("value", "").strip('"').strip("'")
                    break

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state)
            schedules, captured_token = discover_schedules_playwright(context)
            browser.close()

        active_token = captured_token or token
        if active_token:
            print(f"[Dojour] Authenticated with token: {active_token[:8]}...")
            dojour_rows = fetch_dojour_tickets_with_session(active_token, schedules)
        else:
            print("[Dojour] Error: Could not resolve auth token.")

    all_rows = shopify_rows + dojour_rows
    sync_to_google_sheet(all_rows)

if __name__ == "__main__":
    main()
