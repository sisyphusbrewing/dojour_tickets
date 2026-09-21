import os
import re
import json
import sys
import requests
from datetime import datetime, timezone
import zoneinfo

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")


# ==============================================================================
# 1. Text & Date Normalization Helpers
# ==============================================================================

def clean_show_title(raw_title: str) -> str:
    """Normalizes titles to clean comic names."""
    if not raw_title:
        return ""

    title = raw_title.strip()
    if title.lower() in ["comedy show", "comedy", "stand-up comedy", "show"]:
        return ""

    for delimiter in ["///", "//", " - Comedy", " – Comedy"]:
        if delimiter in title:
            title = title.split(delimiter)[0].strip()

    title = re.sub(
        r'\s*[-–]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d+.*$',
        '',
        title,
        flags=re.IGNORECASE
    )
    title = re.sub(r'\s*[-–]\s*\d{1,2}/\d{1,2}.*$', '', title)
    return title.strip()


def format_show_date(date_val: str) -> str:
    """Converts timestamps to 'Sat, Sep 19 • 7:00 PM' (America/Chicago)."""
    if not date_val:
        return ""

    raw_str = str(date_val).strip()

    # Match DOM formatted strings: "Saturday, September 19th | 7:00pm - 9:00pm"
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

    # Match ISO-8601 timestamps
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
# 2. Dojour Ticket & Schedule Fetcher
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


def extract_instance_metadata(item: dict) -> dict:
    """Extracts instance ID, clean title, start date, and sold count."""
    ei = item.get("event_instance") if isinstance(item.get("event_instance"), dict) else {}
    sched = item.get("schedule") if isinstance(item.get("schedule"), dict) else {}
    ev = item.get("event") if isinstance(item.get("event"), dict) else {}

    # Extract instance / schedule ID
    inst_id = ""
    for url_key in ["url", "link", "admin_url", "report_url"]:
        for src in [item, ei, sched]:
            u = str(src.get(url_key, ""))
            m = re.search(r'/(?:s|event_instances|schedules)/(\d+)', u)
            if m:
                inst_id = m.group(1)
                break
        if inst_id:
            break

    if not inst_id:
        for src in [ei, sched, item]:
            for k in ["event_instance_id", "schedule_id", "instance_id", "id"]:
                val = src.get(k)
                if isinstance(val, (int, str)) and str(val).isdigit():
                    inst_id = str(val)
                    break
            if inst_id:
                break

    # Extract clean title
    raw_title = ""
    for src in [ev, item, ei, sched]:
        for k in ["title", "name", "event_title", "headline"]:
            val = src.get(k)
            if val and isinstance(val, str) and val.strip().lower() not in ["comedy show", "comedy", "show"]:
                raw_title = val.strip()
                break
        if raw_title:
            break

    show_title = clean_show_title(raw_title)

    # Extract date/time
    raw_date = ""
    for src in [ei, sched, item, ev]:
        for k in ["start", "start_datetime", "starts_at", "readable_time", "start_time", "datetime", "date"]:
            val = src.get(k)
            if val and isinstance(val, str) and len(val.strip()) > 3:
                raw_date = val.strip()
                break
        if raw_date:
            break

    show_date = format_show_date(raw_date)

    # Extract sold count
    sold_count = 0
    for k in ["reserved_count", "reserves_count", "num_reserves", "sold", "sold_count", "count"]:
        v = item.get(k)
        if isinstance(v, int):
            sold_count = v
            break
        elif isinstance(v, str) and v.isdigit():
            sold_count = int(v)
            break

    return {
        "instance_id": inst_id,
        "show_title": show_title,
        "show_date": show_date,
        "sold_count": sold_count
    }


def is_attendee_dict(d: dict) -> bool:
    """Verifies that a dictionary is an attendee/reservation record."""
    if not isinstance(d, dict):
        return False
    for nested in ["user", "guest", "customer"]:
        if isinstance(d.get(nested), dict):
            return True
    for field in ["name", "guest_name", "full_name", "first_name", "last_name", "email", "guest_email", "party_size", "tickets", "quantity", "num_tickets"]:
        if field in d:
            return True
    return False


def extract_reservations_flexible(report_data) -> list:
    """Extracts attendee lists regardless of whether DRF wrapped them in 'results', 'reserves', etc."""
    if not report_data:
        return []
    if isinstance(report_data, list):
        return [item for item in report_data if isinstance(item, dict) and is_attendee_dict(item)]

    if isinstance(report_data, dict):
        # Check standard DRF list keys
        for key in ["results", "reserves", "reservations", "reserve_list", "attendees", "guests", "orders", "tickets", "data", "items"]:
            val = report_data.get(key)
            if isinstance(val, list) and len(val) > 0:
                attendees = [item for item in val if isinstance(item, dict) and is_attendee_dict(item)]
                if attendees:
                    return attendees
                if any(isinstance(x, dict) for x in val):
                    return [x for x in val if isinstance(x, dict)]

        # Search all dictionary values for a list of dicts
        for val in report_data.values():
            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                attendees = [item for item in val if is_attendee_dict(item)]
                if attendees:
                    return attendees

    return []


def parse_attendee_record(res: dict, instance_id: str, idx: int, show_date: str, show_title: str) -> list:
    """Maps an attendee reservation record into the 9-column sheet schema."""
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
        first = (res.get("first_name") or user.get("first_name") or guest.get("first_name") or customer.get("first_name") or "").strip()
        last = (res.get("last_name") or user.get("last_name") or guest.get("last_name") or customer.get("last_name") or "").strip()
        guest_name = f"{first} {last}".strip()

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
        guest_name if guest_name else "Dojour Guest",
        email,
        tickets_count,
        "Dojour",
        False,
        ""
    ]


def fetch_instance_reservations(instance_id: str, headers: dict) -> list:
    """Attempts candidate endpoints with pagination support to fetch all reservations."""
    candidate_urls = [
        f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/",
        f"https://dojour.us/api/event_instances/reserve_reports/{instance_id}/",
        f"https://dojour.us/api/schedules/{instance_id}/reserve_report/",
        f"https://dojour.us/api/event_instances/{instance_id}/reserve_report"
    ]

    for url in candidate_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = extract_reservations_flexible(data)

                # Follow pagination if present
                next_url = data.get("next") if isinstance(data, dict) else None
                while next_url:
                    page_resp = requests.get(next_url, headers=headers, timeout=15)
                    if page_resp.status_code == 200:
                        page_data = page_resp.json()
                        results.extend(extract_reservations_flexible(page_data))
                        next_url = page_data.get("next") if isinstance(page_data, dict) else None
                    else:
                        break
                return results
        except Exception:
            continue

    return []


def fetch_dojour_tickets_and_schedules():
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
                meta = extract_instance_metadata(item)
                inst_id = meta["instance_id"]
                if inst_id:
                    schedules[inst_id] = meta

            api_url = data.get("next") if isinstance(data, dict) else None
    except Exception as e:
        print(f"Error querying Dojour reserve_reports: {e}")

    print(f"Found {len(schedules)} upcoming Dojour show schedules.")
    dojour_door_rows = []

    # Fetch attendee reports for every upcoming show
    for idx, (instance_id, meta) in enumerate(schedules.items()):
        show_date = meta["show_date"]
        show_title = meta["show_title"]

        raw_attendees = fetch_instance_reservations(instance_id, headers)

        if raw_attendees:
            # Update sold count from actual reservations if report had data
            actual_tickets = sum(int(r.get("party_size") or r.get("tickets") or r.get("quantity") or 1) for r in raw_attendees if isinstance(r, dict))
            if actual_tickets > meta["sold_count"]:
                meta["sold_count"] = actual_tickets

            for a_idx, res in enumerate(raw_attendees):
                if isinstance(res, dict):
                    row = parse_attendee_record(res, instance_id, a_idx, show_date, show_title)
                    dojour_door_rows.append(row)

            print(f"  [{idx+1}/{len(schedules)}] {show_title or 'Show'} ({show_date or instance_id}): {len(raw_attendees)} reservations ({actual_tickets} tickets)")

    print(f"Retrieved {len(dojour_door_rows)} guest reservations from Dojour.")
    return dojour_door_rows, schedules


# ==============================================================================
# 3. Shopify Ticket Fetcher
# ==============================================================================

def get_shopify_access_token() -> str:
    direct_token = os.environ.get("SHOPIFY_ACCESS_TOKEN") or os.environ.get("SHOPIFY_ADMIN_API_TOKEN")
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

                    # Filter out non-event line items
                    full_desc = f"{item_title} {variant_title}".lower()
                    if any(term in full_desc for term in ["tip", "donation", "fee", "gratuity", "service charge", "room rental", "event deposit"]):
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
# 4. Google Sheets Sync (Door List + Sheet1 Summary)
# ==============================================================================

def open_target_spreadsheet(gc):
    sheet_id = (
        os.environ.get("SPREADSHEET_ID")
        or os.environ.get("GOOGLE_SHEET_ID")
        or os.environ.get("SHEET_ID")
        or os.environ.get("GOOGLE_SPREADSHEET_ID")
        or os.environ.get("SPREADSHEET_KEY")
    )
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME") or os.environ.get("SPREADSHEET_NAME")
    doc = None

    if sheet_id:
        sheet_id = sheet_id.strip()
        try:
            if "docs.google.com" in sheet_id:
                doc = gc.open_by_url(sheet_id)
            else:
                doc = gc.open_by_key(sheet_id)
        except Exception:
            pass

    if not doc and sheet_name:
        try:
            doc = gc.open(sheet_name.strip())
        except Exception:
            pass

    if not doc:
        try:
            all_docs = gc.openall()
            for d in all_docs:
                titles = [w.title.strip().lower() for w in d.worksheets()]
                if "door list" in titles:
                    doc = d
                    break
            if not doc and len(all_docs) > 0:
                doc = all_docs[0]
        except Exception:
            pass

    if not doc:
        raise ValueError("Could not locate Google Spreadsheet. Please verify service account permissions.")
    return doc


def sync_to_google_sheet(tickets: list, schedules: dict):
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
    doc = open_target_spreadsheet(gc)

    # --------------------------------------------------------------------------
    # Sync Tab 1: "Door List" (Guest Check-In)
    # --------------------------------------------------------------------------
    try:
        ws_door = doc.worksheet("Door List")
    except Exception:
        ws_door = doc.get_worksheet(0)

    existing_data = ws_door.get_all_values()
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

    merged_door_rows = []
    for t in tickets:
        row_copy = list(t)
        uid = row_copy[0]
        if uid in checkin_map:
            row_copy[7] = checkin_map[uid][0]
            row_copy[8] = checkin_map[uid][1]
        merged_door_rows.append(row_copy)

    merged_door_rows.sort(key=lambda r: (r[1], r[2], r[3].lower()))

    door_headers = [
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

    door_payload = [door_headers] + merged_door_rows
    ws_door.clear()
    try:
        ws_door.update(values=door_payload, range_name="A1", value_input_option="USER_ENTERED")
    except TypeError:
        try:
            ws_door.update("A1", door_payload, value_input_option="USER_ENTERED")
        except Exception:
            ws_door.update(door_payload)

    print(f"Successfully synced {len(merged_door_rows)} records to '{ws_door.title}'.")

    # --------------------------------------------------------------------------
    # Sync Tab 2: "Sheet1" (Show Title, Show Date, Dojour Sold)
    # --------------------------------------------------------------------------
    ws_summary = None
    for w in doc.worksheets():
        if w.title.strip().lower() == "sheet1":
            ws_summary = w
            break

    if ws_summary:
        summary_rows = []
        for inst_id, meta in schedules.items():
            stitle = meta["show_title"]
            sdate = meta["show_date"]
            sold = meta["sold_count"]
            summary_rows.append([stitle, sdate, sold])

        summary_rows.sort(key=lambda r: (r[1], r[0]))
        summary_payload = [["Show Title", "Show Date", "Dojour Sold"]] + summary_rows

        ws_summary.clear()
        try:
            ws_summary.update(values=summary_payload, range_name="A1", value_input_option="USER_ENTERED")
        except TypeError:
            try:
                ws_summary.update("A1", summary_payload, value_input_option="USER_ENTERED")
            except Exception:
                ws_summary.update(summary_payload)

        print(f"Successfully synced {len(summary_rows)} show counts to 'Sheet1'.")


# ==============================================================================
# 5. Main Execution Entry Point
# ==============================================================================

def main():
    print("Starting Sisyphus Brewing Ticket Consolidation...")
    shopify_tickets = []
    dojour_tickets = []
    dojour_schedules = {}

    try:
        shopify_tickets = fetch_shopify_tickets()
    except Exception as e:
        print(f"Warning: Shopify sync error: {e}")

    try:
        dojour_tickets, dojour_schedules = fetch_dojour_tickets_and_schedules()
    except Exception as e:
        print(f"Warning: Dojour sync error: {e}")

    all_tickets = shopify_tickets + dojour_tickets
    print(f"Consolidated total: {len(all_tickets)} door list tickets.")

    if not all_tickets and not dojour_schedules:
        print("No ticket records or schedules found. Skipping update.")
        return

    sync_to_google_sheet(all_tickets, dojour_schedules)
    print("Consolidation process complete.")


if __name__ == "__main__":
    main()
