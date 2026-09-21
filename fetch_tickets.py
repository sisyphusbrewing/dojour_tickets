import os
import re
import json
import sys
import requests
from datetime import datetime, timezone
import zoneinfo

# Google Sheets client
try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")


# ==============================================================================
# 1. Date & Title Formatting Helpers (Zero External Dependencies)
# ==============================================================================

def clean_show_title(raw_title: str) -> str:
    """
    Normalizes multi-line and multi-day Dojour/Shopify titles to clean comic names:
    'Alex Dragicevich /// Comedy - September 18 & 19' -> 'Alex Dragicevich'
    'Geoffrey Asmus // Sisyphus Brewing' -> 'Geoffrey Asmus'
    """
    if not raw_title:
        return ""

    title = raw_title.strip()

    for delimiter in ["///", "//", " - Comedy", " – Comedy"]:
        if delimiter in title:
            title = title.split(delimiter)[0].strip()

    # Strip trailing date ranges (e.g. ' - September 18 & 19' or ' - 9/18')
    title = re.sub(
        r'\s*[-–]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d+.*$',
        '',
        title,
        flags=re.IGNORECASE
    )
    title = re.sub(r'\s*[-–]\s*\d{1,2}/\d{1,2}.*$', '', title)

    return title.strip()


def format_show_date(date_val: str) -> str:
    """
    Converts ISO timestamps or DOM date strings into the unified format:
    'Sat, Sep 19 • 7:00 PM' (America/Chicago time).
    """
    if not date_val:
        return ""

    raw_str = str(date_val).strip()

    # 1. Parse DOM-style string: "Saturday, September 19th | 7:00pm - 9:00pm" or "Sat, Sep 19 • 7:00 PM"
    dom_match = re.search(
        r'(?:([A-Za-z]+),\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+\d{4})?\s*(?:[|@•\-]\s*|\s+at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        raw_str,
        re.IGNORECASE
    )
    if dom_match:
        weekday_raw, month_raw, day_raw, hour_raw, min_raw, ampm_raw = dom_match.groups()
        month = datetime.strptime(month_raw[:3], "%b").strftime("%b")
        day = str(int(day_raw))
        hour = str(int(hour_raw))
        minute = min_raw if min_raw else "00"
        ampm = ampm_raw.upper()

        if weekday_raw:
            weekday = weekday_raw[:3].capitalize()
        else:
            try:
                now_year = datetime.now(CENTRAL_TZ).year
                dt_temp = datetime.strptime(f"{now_year} {month} {day}", "%Y %b %d")
                weekday = dt_temp.strftime("%a")
            except Exception:
                weekday = ""

        if weekday:
            return f"{weekday}, {month} {day} • {hour}:{minute} {ampm}"
        return f"{month} {day} • {hour}:{minute} {ampm}"

    # 2. Parse ISO-8601 timestamps (handles 'Z', offsets, and naive formats)
    try:
        iso_str = raw_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(CENTRAL_TZ)
        else:
            dt = dt.replace(tzinfo=CENTRAL_TZ)

        weekday = dt.strftime("%a")
        month = dt.strftime("%b")
        day = str(dt.day)
        hour = str(int(dt.strftime("%I")))
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p")
        return f"{weekday}, {month} {day} • {hour}:{minute} {ampm}"
    except Exception:
        pass

    return raw_str


# ==============================================================================
# 2. Dojour Ticket Fetcher
# ==============================================================================

def get_dojour_token() -> str:
    """Extracts Django usertoken from DOJOUR_STATE JSON or DOJOUR_TOKEN env var."""
    token = os.environ.get("DOJOUR_TOKEN")
    if token:
        return token.strip()

    state_val = os.environ.get("DOJOUR_STATE", "")
    state_data = {}
    if state_val:
        if os.path.exists(state_val):
            with open(state_val, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        else:
            try:
                state_data = json.loads(state_val)
            except Exception:
                pass

    if not state_data and os.path.exists("dojour_state.json"):
        with open("dojour_state.json", "r", encoding="utf-8") as f:
            state_data = json.load(f)

    for cookie in state_data.get("cookies", []):
        if cookie.get("name") == "usertoken":
            return cookie.get("value")

    raise ValueError("Could not find 'usertoken' cookie in DOJOUR_STATE or DOJOUR_TOKEN.")


def extract_reservations_list(data) -> list:
    """Extracts the list of reservations from various Dojour payload shapes."""
    if not data:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in [
            "reserves",
            "reservations",
            "reserve_list",
            "reserve_reports",
            "attendees",
            "guests",
            "orders",
            "tickets",
            "results",
            "data",
            "items"
        ]:
            if key in data and isinstance(data[key], list):
                return data[key]

        # Dynamic inspection: look for any list containing dictionaries
        for v in data.values():
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                return v

        for v in data.values():
            if isinstance(v, list):
                return v

    return []


def get_instance_id_from_item(item: dict) -> str:
    """Extracts instance/schedule ID from Dojour API objects or URLs."""
    for url_key in ["url", "link", "admin_url", "report_url"]:
        u = str(item.get(url_key, ""))
        m = re.search(r'/(?:s|event_instances)/(\d+)', u)
        if m:
            return m.group(1)

    for key in ["event_instance", "instance", "schedule"]:
        val = item.get(key)
        if isinstance(val, dict) and "id" in val:
            return str(val["id"])
        elif isinstance(val, (int, str)) and str(val).isdigit():
            return str(val)

    for key in ["event_instance_id", "instance_id", "schedule_id", "id"]:
        val = item.get(key)
        if isinstance(val, (int, str)) and str(val).isdigit():
            return str(val)

    return ""


def parse_dojour_reservation(res: dict, instance_id: str, idx: int, show_date: str, show_title: str) -> list:
    """Maps a Dojour reservation dict to the 9-column sheet schema."""
    res_id = str(res.get("id") or res.get("reserve_id") or res.get("reservation_id") or idx)
    unique_id = f"dj_{instance_id}_{res_id}"

    user = res.get("user") if isinstance(res.get("user"), dict) else {}
    guest = res.get("guest") if isinstance(res.get("guest"), dict) else {}
    customer = res.get("customer") if isinstance(res.get("customer"), dict) else {}

    guest_name = (
        res.get("name")
        or res.get("guest_name")
        or res.get("full_name")
        or res.get("customer_name")
        or user.get("name")
        or user.get("full_name")
        or guest.get("name")
        or customer.get("name")
        or ""
    )
    if not guest_name:
        first = (
            res.get("first_name")
            or user.get("first_name")
            or guest.get("first_name")
            or customer.get("first_name")
            or ""
        ).strip()
        last = (
            res.get("last_name")
            or user.get("last_name")
            or guest.get("last_name")
            or customer.get("last_name")
            or ""
        ).strip()
        guest_name = f"{first} {last}".strip()
    if not guest_name:
        guest_name = "Guest"

    email = (
        res.get("email")
        or res.get("guest_email")
        or res.get("customer_email")
        or user.get("email")
        or guest.get("email")
        or customer.get("email")
        or ""
    ).strip()

    tickets = (
        res.get("party_size")
        or res.get("tickets")
        or res.get("quantity")
        or res.get("num_tickets")
        or res.get("num_guests")
        or res.get("seats")
        or res.get("count")
        or 1
    )
    try:
        tickets_count = int(tickets)
    except (ValueError, TypeError):
        tickets_count = 1

    return [
        unique_id,
        show_date,
        show_title,
        guest_name,
        email,
        tickets_count,
        "Dojour",
        False,
        ""
    ]


def fetch_dojour_tickets() -> list:
    token = get_dojour_token()
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    schedules = {}
    api_url = "https://dojour.us/api/event_instances/reserve_reports/?page_size=100&upcoming=true"

    try:
        while api_url:
            resp = requests.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"Notice: Dojour reserve_reports returned status {resp.status_code}")
                break
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data

            for item in results:
                inst_id = get_instance_id_from_item(item)
                if not inst_id:
                    continue

                raw_title = ""
                if isinstance(item.get("event"), dict):
                    raw_title = item["event"].get("title") or item["event"].get("name") or ""
                if not raw_title:
                    raw_title = item.get("title") or item.get("name") or item.get("event_title") or ""

                raw_date = (
                    item.get("start")
                    or item.get("start_datetime")
                    or item.get("starts_at")
                    or item.get("start_time")
                    or item.get("date")
                    or item.get("datetime")
                    or item.get("date_string")
                )

                schedules[inst_id] = {
                    "show_title": clean_show_title(raw_title),
                    "show_date": format_show_date(raw_date),
                    "embedded_reserves": extract_reservations_list(item)
                }

            api_url = data.get("next") if isinstance(data, dict) else None
    except Exception as e:
        print(f"Error querying Dojour reserve_reports: {e}")

    dojour_rows = []

    for instance_id, meta in schedules.items():
        show_date = meta["show_date"]
        show_title = meta["show_title"]
        reservations = meta.get("embedded_reserves", [])

        # If reservations were not inlined in the list endpoint, fetch the instance report
        if not reservations:
            report_url = f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/"
            try:
                resp = requests.get(report_url, headers=headers, timeout=20)
                if resp.status_code == 404:
                    resp = requests.get(
                        f"https://dojour.us/api/event_instances/{instance_id}/reserve_report",
                        headers=headers,
                        timeout=20
                    )

                if resp.status_code == 200:
                    report_data = resp.json()
                    reservations = extract_reservations_list(report_data)
                elif resp.status_code != 200:
                    print(f"Notice: Instance {instance_id} ({show_title}) returned status {resp.status_code}")
            except Exception as e:
                print(f"Error fetching reserve report for instance {instance_id}: {e}")
                continue

        for idx, res in enumerate(reservations):
            if not isinstance(res, dict):
                continue
            row = parse_dojour_reservation(res, instance_id, idx, show_date, show_title)
            dojour_rows.append(row)

    print(f"Retrieved {len(dojour_rows)} tickets from Dojour across {len(schedules)} shows.")
    return dojour_rows


# ==============================================================================
# 3. Shopify Ticket Fetcher
# ==============================================================================

def get_shopify_access_token() -> str:
    direct_token = (
        os.environ.get("SHOPIFY_ACCESS_TOKEN")
        or os.environ.get("SHOPIFY_ADMIN_API_TOKEN")
    )
    if direct_token:
        return direct_token.strip()

    client_id = os.environ.get("SHOPIFY_CLIENT_ID")
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store.endswith(".myshopify.com"):
        store = f"{store}.myshopify.com"

    if not client_id or not client_secret:
        raise ValueError("Missing SHOPIFY_CLIENT_ID or SHOPIFY_CLIENT_SECRET.")

    token_url = f"https://{store}/admin/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    }
    resp = requests.post(token_url, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json().get("access_token")


def fetch_shopify_tickets() -> list:
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store:
        print("SHOPIFY_STORE not configured. Skipping Shopify sync.")
        return []
    if not store.endswith(".myshopify.com"):
        store = f"{store}.myshopify.com"

    try:
        token = get_shopify_access_token()
    except Exception as e:
        print(f"Shopify auth error: {e}")
        return []

    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

    url = f"https://{store}/admin/api/2024-01/orders.json?status=any&limit=250"
    shopify_rows = []

    try:
        while url:
            resp = requests.get(url, headers=headers, timeout=25)
            resp.raise_for_status()
            data = resp.json()
            orders = data.get("orders", [])

            for order in orders:
                if order.get("cancelled_at"):
                    continue
                if order.get("financial_status") not in ["paid", "partially_refunded", "authorized", "pending"]:
                    continue

                order_id = str(order.get("id"))
                customer = order.get("customer") or {}
                guest_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                if not guest_name:
                    billing = order.get("billing_address") or {}
                    guest_name = billing.get("name") or order.get("email") or "Guest"

                email = customer.get("email") or order.get("email") or ""

                for item in order.get("line_items", []):
                    item_title = item.get("title") or ""
                    variant_title = item.get("variant_title") or ""

                    # Ignore tips, fees, gratuity, and donations
                    full_desc = f"{item_title} {variant_title}".lower()
                    if any(term in full_desc for term in ["tip", "donation", "fee", "gratuity", "service charge"]):
                        continue

                    show_title = clean_show_title(item_title)

                    date_cands = [variant_title]
                    for prop in item.get("properties", []):
                        if any(k in prop.get("name", "").lower() for k in ["date", "time", "show"]):
                            date_cands.insert(0, str(prop.get("value", "")))
                    date_cands.append(item_title)

                    show_date = ""
                    for cand in date_cands:
                        parsed_d = format_show_date(cand)
                        if "•" in parsed_d or re.search(r'\d{1,2}:\d{2}', parsed_d):
                            show_date = parsed_d
                            break

                    item_id = str(item.get("id"))
                    unique_id = f"shopify_{order_id}_{item_id}"
                    tickets_count = int(item.get("quantity", 1))

                    shopify_rows.append([
                        unique_id,
                        show_date,
                        show_title,
                        guest_name,
                        email,
                        tickets_count,
                        "Website",
                        False,
                        ""
                    ])

            link_header = resp.headers.get("Link", "")
            next_url = None
            if link_header:
                for link_part in link_header.split(","):
                    if 'rel="next"' in link_part:
                        match = re.search(r'<(.*?)>', link_part)
                        if match:
                            next_url = match.group(1)
            url = next_url

    except Exception as e:
        print(f"Error fetching Shopify orders: {e}")

    print(f"Retrieved {len(shopify_rows)} tickets from Shopify.")
    return shopify_rows


# ==============================================================================
# 4. Google Sheets Sync (Auto-Discovery & State Persistence)
# ==============================================================================

def get_spreadsheet_and_worksheet(gc):
    """
    Locates the target spreadsheet using IDs, names, or automatic search
    across all sheets shared with the service account.
    """
    sheet_id = (
        os.environ.get("SPREADSHEET_ID")
        or os.environ.get("GOOGLE_SHEET_ID")
        or os.environ.get("SHEET_ID")
        or os.environ.get("GOOGLE_SPREADSHEET_ID")
        or os.environ.get("SPREADSHEET_KEY")
    )
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME") or os.environ.get("SPREADSHEET_NAME")

    doc = None

    # 1. Open by ID or URL if specified
    if sheet_id:
        sheet_id = sheet_id.strip()
        try:
            if "docs.google.com" in sheet_id:
                doc = gc.open_by_url(sheet_id)
            else:
                doc = gc.open_by_key(sheet_id)
        except Exception as e:
            print(f"Notice: Could not open via ID/URL '{sheet_id}': {e}")

    # 2. Open by explicit document name
    if not doc and sheet_name:
        try:
            doc = gc.open(sheet_name.strip())
        except Exception as e:
            print(f"Notice: Could not open via sheet name '{sheet_name}': {e}")

    # 3. Fallback: Search all spreadsheets shared with the Service Account
    if not doc:
        try:
            all_docs = gc.openall()
            print(f"Found {len(all_docs)} spreadsheet(s) shared with service account.")

            # Search for a spreadsheet containing a "Door List" worksheet
            for d in all_docs:
                try:
                    titles = [w.title.strip().lower() for w in d.worksheets()]
                    if "door list" in titles:
                        doc = d
                        print(f"Auto-selected spreadsheet with 'Door List' tab: '{doc.title}'")
                        break
                except Exception:
                    continue

            # Check document titles for relevant keywords
            if not doc:
                for d in all_docs:
                    if any(k in d.title.lower() for k in ["door list", "sisyphus", "ticket", "check"]):
                        doc = d
                        print(f"Auto-selected spreadsheet by title: '{doc.title}'")
                        break

            # If only one spreadsheet is shared with this service account, use it
            if not doc and len(all_docs) == 1:
                doc = all_docs[0]
                print(f"Using single shared spreadsheet: '{doc.title}'")
            elif not doc and len(all_docs) > 0:
                doc = all_docs[0]
                print(f"Defaulting to first shared spreadsheet: '{doc.title}'")
        except Exception as e:
            print(f"Notice: Could not search shared spreadsheets: {e}")

    if not doc:
        raise ValueError(
            "Could not locate Google Spreadsheet. Please ensure the spreadsheet is shared with "
            "the service account email and optionally set SPREADSHEET_ID in repository secrets."
        )

    # Find the "Door List" tab
    ws = None
    try:
        ws = doc.worksheet("Door List")
    except Exception:
        for w in doc.worksheets():
            if w.title.strip().lower() == "door list":
                ws = w
                break
        if not ws:
            ws = doc.get_worksheet(0)
            print(f"Warning: 'Door List' tab not found, falling back to first tab '{ws.title}'.")

    return doc, ws


def sync_to_google_sheet(tickets: list):
    if not gspread or not Credentials:
        raise ImportError("gspread and google-auth are required for Google Sheet sync.")

    sa_val = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")
    if not sa_val:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT environment variable.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    if os.path.exists(sa_val):
        creds = Credentials.from_service_account_file(sa_val, scopes=scopes)
    else:
        info = json.loads(sa_val)
        creds = Credentials.from_service_account_info(info, scopes=scopes)

    gc = gspread.authorize(creds)
    _, ws = get_spreadsheet_and_worksheet(gc)

    # Read existing rows to preserve check-in states (Cols H and I)
    existing_data = ws.get_all_values()
    checkin_map = {}

    if len(existing_data) > 1:
        for row in existing_data[1:]:
            if not row or not row[0]:
                continue
            uid = row[0].strip()
            checked_in = row[7].strip().upper() if len(row) > 7 else "FALSE"
            checkin_time = row[8].strip() if len(row) > 8 else ""

            is_checked = checked_in in ["TRUE", "YES", "1"]
            checkin_map[uid] = (is_checked, checkin_time)

    # Merge preserved check-in states
    merged_rows = []
    for t in tickets:
        row_copy = list(t)
        uid = row_copy[0]
        if uid in checkin_map:
            row_copy[7] = checkin_map[uid][0]
            row_copy[8] = checkin_map[uid][1]
        merged_rows.append(row_copy)

    # Sort tickets by Show Date, Show Title, then Guest Name
    merged_rows.sort(key=lambda r: (r[1], r[2], r[3].lower()))

    headers = [
        "Unique ID",
        "Show Date",
        "Show Title",
        "Guest Name",
        "Email",
        "Tickets",
        "Source",
        "Checked In",
        "Check-In Time"
    ]

    payload = [headers] + merged_rows
    ws.clear()

    # Supports gspread v5 and v6
    try:
        ws.update(values=payload, range_name="A1", value_input_option="USER_ENTERED")
    except TypeError:
        try:
            ws.update("A1", payload, value_input_option="USER_ENTERED")
        except Exception:
            ws.update(payload)

    print(f"Successfully synced {len(merged_rows)} records to '{ws.title}' tab.")


# ==============================================================================
# 5. Entry Point
# ==============================================================================

def main():
    print("Starting Sisyphus Brewing Ticket Consolidation...")
    shopify_tickets = []
    dojour_tickets = []

    try:
        shopify_tickets = fetch_shopify_tickets()
    except Exception as e:
        print(f"Warning: Shopify sync error: {e}")

    try:
        dojour_tickets = fetch_dojour_tickets()
    except Exception as e:
        print(f"Warning: Dojour sync error: {e}")

    all_tickets = shopify_tickets + dojour_tickets
    print(f"Consolidated total: {len(all_tickets)} tickets.")

    if not all_tickets:
        print("No tickets found from either source. Skipping sheet overwrite.")
        return

    sync_to_google_sheet(all_tickets)
    print("Ticket sync complete.")


if __name__ == "__main__":
    main()
