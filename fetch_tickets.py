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
    """
    Normalizes multi-line and multi-day Dojour/Shopify titles to comic names:
    'Alex Dragicevich /// Comedy - September 18 & 19' -> 'Alex Dragicevich'
    'Advice Column /// Comedy - September 23rd' -> 'Advice Column'
    """
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


def format_show_date(date_val) -> str:
    """
    Converts timestamps, ISO strings (with +0000 or Z), or DOM text into:
    'Sat, Sep 19 • 7:00 PM' (America/Chicago time).
    """
    if not date_val:
        return ""

    # 1. Unix Epoch timestamp
    if isinstance(date_val, (int, float)):
        if 1500000000 <= date_val <= 2500000000:
            dt = datetime.fromtimestamp(date_val, CENTRAL_TZ)
            return dt.strftime("%a, %b %-d • %-I:%M %p")
        elif 1500000000000 <= date_val <= 2500000000000:
            dt = datetime.fromtimestamp(date_val / 1000.0, CENTRAL_TZ)
            return dt.strftime("%a, %b %-d • %-I:%M %p")
        return ""

    raw_str = str(date_val).strip()

    # 2. Already formatted: 'Sat, Sep 19 • 7:00 PM'
    if re.match(r'^[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}\s+•\s+\d{1,2}:\d{2}\s+(?:AM|PM)$', raw_str):
        return raw_str

    # 3. Match DOM text like 'Saturday, September 19th | 7:00pm - 9:00pm'
    dom_match = re.search(
        r'(?:([A-Za-z]+),\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+\d{4})?\s*(?:[|@•\-,\s]\s*|\s+at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        raw_str,
        re.IGNORECASE
    )
    if dom_match:
        weekday_raw, month_raw, day_raw, hour_raw, min_raw, ampm_raw = dom_match.groups()
        try:
            month = datetime.strptime(month_raw[:3], "%b").strftime("%b")
            day = str(int(day_raw))
            hour = str(int(hour_raw))
            minute = min_raw if min_raw else "00"
            ampm = ampm_raw.upper()

            if weekday_raw:
                weekday = weekday_raw[:3].capitalize()
            else:
                now_year = datetime.now(CENTRAL_TZ).year
                dt_temp = datetime.strptime(f"{now_year} {month} {day}", "%Y %b %d")
                weekday = dt_temp.strftime("%a")

            return f"{weekday}, {month} {day} • {hour}:{minute} {ampm}"
        except Exception:
            pass

    # 4. Match ISO-8601 timestamps (handles +0000, +00:00, and Z)
    try:
        iso_str = raw_str.replace("Z", "+00:00")
        if re.search(r'[+-]\d{4}$', iso_str):
            iso_str = iso_str[:-2] + ":" + iso_str[-2:]
        if " " in iso_str and "T" not in iso_str:
            iso_str = iso_str.replace(" ", "T")
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

    return ""


def extract_tickets_count(res: dict) -> int:
    """Extracts actual ticket quantity from a reservation."""
    # 1. full_ticket_set: list of ticket objects
    if isinstance(res.get("full_ticket_set"), list) and len(res["full_ticket_set"]) > 0:
        return len(res["full_ticket_set"])

    # 2. option_set inside reservation
    if isinstance(res.get("option_set"), list) and len(res["option_set"]) > 0:
        qty = 0
        for opt in res["option_set"]:
            if isinstance(opt, dict):
                q = opt.get("quantity") or opt.get("count") or opt.get("tickets") or opt.get("num_tickets") or 1
                try:
                    qty += int(q)
                except (ValueError, TypeError):
                    qty += 1
            elif isinstance(opt, (int, str)) and str(opt).isdigit():
                qty += int(opt)
            else:
                qty += 1
        if qty > 0:
            return qty

    # 3. Direct quantity / party_size keys
    for k in ["party_size", "tickets", "quantity", "num_tickets", "num_guests", "seats", "count"]:
        val = res.get(k)
        if val is not None:
            try:
                t = int(val)
                if t > 0:
                    return t
            except (ValueError, TypeError):
                pass

    return 1


# ==============================================================================
# 2. Dojour Ticket & Schedule Fetcher (Native reservation_set Ingestion)
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


def fetch_dojour_tickets_and_schedules():
    token = get_dojour_token()
    session = requests.Session()
    session.cookies.set("usertoken", token, domain="dojour.us")
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 1. Discover all upcoming instances from reserve_reports summary
    api_url = "https://dojour.us/api/event_instances/reserve_reports/?page_size=100&upcoming=true"
    instance_ids = []
    initial_meta = {}

    try:
        while api_url:
            resp = session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                break
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data

            for item in results:
                inst_id = str(item.get("id") or item.get("event_instance_id") or "")
                if not inst_id:
                    continue

                if inst_id not in instance_ids:
                    instance_ids.append(inst_id)

                # Pre-extract title and sold count if present
                opt_title = ""
                if item.get("option_set") and isinstance(item["option_set"], list) and len(item["option_set"]) > 0:
                    opt_title = item["option_set"][0].get("title", "")

                initial_meta[inst_id] = {
                    "show_title": clean_show_title(opt_title or item.get("title", "")),
                    "show_date": format_show_date(item.get("start_dt")),
                    "sold_count": int(item.get("active_count") or item.get("complete_count") or 0)
                }

            api_url = data.get("next") if isinstance(data, dict) else None
    except Exception as e:
        print(f"Notice during schedule discovery: {e}")

    # Fallback to HTML table if list endpoint returned nothing
    if not instance_ids:
        try:
            page_url = "https://dojour.us/admin-tools/reservations/all/?upcoming=true"
            resp = session.get(page_url, timeout=20)
            if resp.status_code == 200:
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', resp.text, flags=re.DOTALL | re.IGNORECASE)
                for r in rows:
                    m_id = re.search(r'/admin-tools/reservations/s/(\d+)', r)
                    if m_id:
                        inst_id = m_id.group(1)
                        if inst_id not in instance_ids:
                            instance_ids.append(inst_id)
                        tokens = [t.strip() for t in re.sub(r'<[^>]+>', '\t', r).split('\t') if t.strip()]
                        for t in tokens:
                            p_date = format_show_date(t)
                            if p_date:
                                initial_meta[inst_id] = {"show_title": "", "show_date": p_date, "sold_count": 0}
        except Exception as e:
            print(f"Notice during HTML fallback: {e}")

    print(f"Found {len(instance_ids)} upcoming Dojour show schedules.")
    dojour_door_rows = []
    final_schedules = {}

    # 2. Query each instance's reserve_report to get the true reservation_set
    for idx, inst_id in enumerate(instance_ids):
        meta = initial_meta.get(inst_id, {"show_title": "", "show_date": "", "sold_count": 0})
        report_url = f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
        report_data = None

        try:
            resp = session.get(report_url, headers=headers, timeout=15)
            if resp.status_code == 404:
                resp = session.get(f"https://dojour.us/api/event_instances/{inst_id}/reserve_report", headers=headers, timeout=15)
            if resp.status_code == 200:
                report_data = resp.json()
        except Exception as e:
            print(f"Error querying instance {inst_id}: {e}")

        if not report_data or not isinstance(report_data, dict):
            final_schedules[inst_id] = meta
            continue

        # Extract reservation_set
        res_list = report_data.get("reservation_set", [])

        # Update sold count from report
        active_cnt = report_data.get("active_count") or report_data.get("complete_count") or len(res_list)
        meta["sold_count"] = int(active_cnt)

        # Detect show title & start date from reservation_set or option_set
        detected_title = meta["show_title"]
        detected_date = meta["show_date"]

        if not detected_date and res_list:
            for r in res_list:
                if r.get("start_dt"):
                    detected_date = format_show_date(r["start_dt"])
                    break

        if not detected_title and res_list:
            for r in res_list:
                if r.get("event_title"):
                    detected_title = clean_show_title(r["event_title"])
                    break

        if not detected_title and report_data.get("option_set") and len(report_data["option_set"]) > 0:
            detected_title = clean_show_title(report_data["option_set"][0].get("title", ""))

        # If date is still missing, query instance detail endpoint
        if not detected_date:
            try:
                inst_resp = session.get(f"https://dojour.us/api/event_instances/{inst_id}/", headers=headers, timeout=10)
                if inst_resp.status_code == 200:
                    inst_json = inst_resp.json()
                    detected_date = format_show_date(inst_json.get("start_dt"))
                    if not detected_title:
                        detected_title = clean_show_title(inst_json.get("event", {}).get("title") or inst_json.get("title", ""))
            except Exception:
                pass

        meta["show_title"] = detected_title
        meta["show_date"] = detected_date
        final_schedules[inst_id] = meta

        # Process each completed attendee reservation
        show_valid_count = 0
        for r_idx, res in enumerate(res_list):
            if not isinstance(res, dict):
                continue

            # Skip cancelled, waitlisted, or incomplete checkouts
            if res.get("is_cancelled") is True:
                continue
            if res.get("waitlist") is True or res.get("is_on_waitlist") is True:
                continue
            if res.get("checkout_complete") is False:
                continue

            pk = str(res.get("encrypted_pk") or res.get("id") or r_idx)
            unique_id = f"dj_{inst_id}_{pk}"

            # Date and Title for this specific reservation
            r_date = format_show_date(res.get("start_dt")) or detected_date
            r_title = clean_show_title(res.get("event_title")) or detected_title

            # Guest Name
            first = (res.get("first_name") or "").strip()
            last = (res.get("last_name") or "").strip()
            guest_name = f"{first} {last}".strip()
            if not guest_name:
                user = res.get("user") if isinstance(res.get("user"), dict) else {}
                u_first = (user.get("first_name") or "").strip()
                u_last = (user.get("last_name") or "").strip()
                guest_name = f"{u_first} {u_last}".strip()
            if not guest_name:
                guest_name = res.get("name") or "Guest"

            # Email
            email = (res.get("email") or "").strip()
            if not email and isinstance(res.get("user"), dict):
                email = (res["user"].get("email") or "").strip()

            # Tickets
            tickets = extract_tickets_count(res)

            row = [
                unique_id,       # Col A: Unique ID
                r_date,          # Col B: Show Date ('Wed, Sep 23 • 7:00 PM')
                r_title,         # Col C: Show Title ('Advice Column')
                guest_name,      # Col D: Guest Name
                email,           # Col E: Email
                tickets,         # Col F: Tickets
                "Dojour",        # Col G: Source
                False,           # Col H: Checked In
                ""               # Col I: Check-In Time
            ]
            dojour_door_rows.append(row)
            show_valid_count += 1

        if show_valid_count > 0:
            print(f"  [{idx+1}/{len(instance_ids)}] {detected_title} ({r_date}): {show_valid_count} reservations ({active_cnt} tickets sold)")

    print(f"Retrieved {len(dojour_door_rows)} total Dojour attendee reservations.")
    return dojour_door_rows, final_schedules


# ==============================================================================
# 3. Shopify Ticket Fetcher (Intact)
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
                        if parsed_d:
                            show_date = parsed_d
                            break

                    item_id = str(item.get("id"))
                    unique_id = f"shopify_{order_id}_{item_id}"
                    tickets_count = int(item.get("quantity", 1))

                    shopify_rows.append([
                        unique_id,       # Col A: Unique ID
                        show_date,       # Col B: Show Date
                        show_title,      # Col C: Show Title
                        guest_name,      # Col D: Guest Name
                        email,           # Col E: Email
                        tickets_count,   # Col F: Tickets
                        "Website",       # Col G: Source
                        False,           # Col H: Checked In
                        ""               # Col I: Check-In Time
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
# 4. Google Sheets Sync (Preserving Columns H & I)
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
    # Tab 1: "Door List" (Guest Check-In)
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

    # Sort door list by Show Date (Col B), Show Title (Col C), then Guest Name (Col D)
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
    # Tab 2: "Sheet1" (Summary Tab: Title, Date, Sold)
    # --------------------------------------------------------------------------
    ws_summary = None
    for w in doc.worksheets():
        if w.title.strip().lower() == "sheet1":
            ws_summary = w
            break

    if ws_summary:
        summary_rows = []
        for inst_id, meta in schedules.items():
            stitle = meta.get("show_title", "")
            sdate = meta.get("show_date", "")
            sold = meta.get("sold_count", 0)
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
