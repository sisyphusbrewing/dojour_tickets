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
# 1. Title & Date Normalization Helpers
# ==============================================================================

def clean_show_title(raw_title: str) -> str:
    """
    Normalizes multi-line and multi-day Dojour/Shopify titles to comic names:
    'Alex Dragicevich /// Comedy - September 18 & 19' -> 'Alex Dragicevich'
    'Geoffrey Asmus // Sisyphus Brewing' -> 'Geoffrey Asmus'
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
    Converts timestamps, ISO strings, or DOM date text into the exact target:
    'Sat, Sep 19 • 7:00 PM' (America/Chicago time).
    """
    if not date_val:
        return ""

    # 1. Unix Epoch timestamp (seconds or milliseconds)
    if isinstance(date_val, (int, float)):
        if 1500000000 <= date_val <= 2500000000:
            dt = datetime.fromtimestamp(date_val, CENTRAL_TZ)
            return dt.strftime("%a, %b %-d • %-I:%M %p")
        elif 1500000000000 <= date_val <= 2500000000000:
            dt = datetime.fromtimestamp(date_val / 1000.0, CENTRAL_TZ)
            return dt.strftime("%a, %b %-d • %-I:%M %p")
        return ""

    raw_str = str(date_val).strip()

    # 2. Already formatted: "Sat, Sep 19 • 7:00 PM"
    if re.match(r'^[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2}\s+•\s+\d{1,2}:\d{2}\s+(?:AM|PM)$', raw_str):
        return raw_str

    # 3. Match DOM text: "Saturday, September 19th | 7:00pm - 9:00pm" or "Sat, Sep 19 @ 7:00pm"
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

    # 4. Match ISO-8601 timestamps
    try:
        iso_str = raw_str.replace("Z", "+00:00")
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


def deep_scan_date(obj, depth=0) -> str:
    """Recursively scans any dictionary or list for a valid performance date."""
    if depth > 5 or not obj:
        return ""

    preferred_keys = [
        "readable_time", "display_time", "start", "start_datetime", "starts_at",
        "start_time", "start_date", "datetime", "date", "date_string", "time",
        "when", "performance_time", "schedule_time", "doors_open"
    ]

    if isinstance(obj, dict):
        for k in preferred_keys:
            if k in obj:
                d = format_show_date(obj[k])
                if d:
                    return d

        for k, v in obj.items():
            if isinstance(v, (str, int, float)):
                d = format_show_date(v)
                if d:
                    return d

        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                d = deep_scan_date(v, depth + 1)
                if d:
                    return d

    elif isinstance(obj, list):
        for item in obj:
            d = deep_scan_date(item, depth + 1)
            if d:
                return d

    return ""


# ==============================================================================
# 2. Dojour Ticket & Schedule Fetcher (With 4-Tier Date Resolution)
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


def fetch_dojour_html_schedule_map(session: requests.Session) -> dict:
    """
    Scrapes https://dojour.us/admin-tools/reservations/all/?upcoming=true
    Directly extracts Schedule ID -> (Clean Title, 'Sat, Sep 19 • 7:00 PM').
    """
    html_map = {}
    try:
        url = "https://dojour.us/admin-tools/reservations/all/?upcoming=true"
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', resp.text, flags=re.DOTALL | re.IGNORECASE)
            for r in rows:
                m_id = re.search(r'/admin-tools/reservations/s/(\d+)', r)
                if not m_id:
                    continue
                inst_id = m_id.group(1)

                clean_text = re.sub(r'<[^>]+>', '\t', r)
                tokens = [t.strip() for t in clean_text.split('\t') if t.strip()]

                title = ""
                date_val = ""
                sold = 0

                for t in tokens:
                    parsed_date = format_show_date(t)
                    if parsed_date:
                        date_val = parsed_date
                    elif re.search(r'(\d+)/\d+', t):
                        m_sold = re.search(r'(\d+)/\d+', t)
                        if m_sold:
                            sold = int(m_sold.group(1))
                    elif not title and t.lower() not in ["comedy show", "comedy"] and t != "|":
                        title = clean_show_title(t)

                if inst_id:
                    html_map[inst_id] = {
                        "show_title": title,
                        "show_date": date_val,
                        "sold_count": sold
                    }
    except Exception as e:
        print(f"Notice: Dojour HTML table scraping: {e}")

    return html_map


def extract_guest_details(res: dict):
    """Extracts guest name, email, and party size from Dojour reservation records."""
    if not isinstance(res, dict):
        return "Guest", "", 1

    # 1. Guest Name
    name = ""
    for k in ["name", "guest_name", "full_name", "customer_name", "contact_name", "attendee_name"]:
        if res.get(k) and isinstance(res[k], str) and res[k].strip():
            name = res[k].strip()
            break

    if not name:
        for sub_key in ["user", "guest", "customer", "contact", "profile", "attendee"]:
            sub = res.get(sub_key)
            if isinstance(sub, dict):
                for k in ["name", "guest_name", "full_name", "customer_name"]:
                    if sub.get(k) and isinstance(sub[k], str) and sub[k].strip():
                        name = sub[k].strip()
                        break
                if not name:
                    first = (sub.get("first_name") or "").strip()
                    last = (sub.get("last_name") or "").strip()
                    if first or last:
                        name = f"{first} {last}".strip()
                if name:
                    break

    if not name:
        first = (res.get("first_name") or "").strip()
        last = (res.get("last_name") or "").strip()
        if first or last:
            name = f"{first} {last}".strip()

    if not name:
        name = "Guest"

    # 2. Email
    email = ""
    for k in ["email", "guest_email", "customer_email", "user_email", "contact_email"]:
        if res.get(k) and isinstance(res[k], str) and "@" in res[k]:
            email = res[k].strip()
            break

    if not email:
        for sub_key in ["user", "guest", "customer", "contact", "profile", "attendee"]:
            sub = res.get(sub_key)
            if isinstance(sub, dict):
                for k in ["email", "guest_email", "customer_email", "user_email"]:
                    if sub.get(k) and isinstance(sub[k], str) and "@" in sub[k]:
                        email = sub[k].strip()
                        break
                if email:
                    break

    # 3. Tickets
    tickets = 1
    for k in ["party_size", "tickets", "quantity", "num_tickets", "num_guests", "seats", "count", "ticket_count"]:
        val = res.get(k)
        if val is not None:
            try:
                t_val = int(val)
                if t_val > 0:
                    tickets = t_val
                    break
            except (ValueError, TypeError):
                pass

    return name, email, tickets


def fetch_dojour_tickets_and_schedules():
    token = get_dojour_token()
    session = requests.Session()
    session.cookies.set("usertoken", token, domain="dojour.us")
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # Step 1: Pre-populate from HTML table (Schedule ID -> Date/Title)
    schedules = fetch_dojour_html_schedule_map(session)

    # Step 2: Query API reserve_reports endpoint
    api_url = "https://dojour.us/api/event_instances/reserve_reports/?page_size=100&upcoming=true"
    try:
        while api_url:
            resp = session.get(api_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                break
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data

            for item in results:
                # Resolve instance ID
                inst_id = ""
                for url_k in ["url", "link", "report_url"]:
                    m = re.search(r'/(?:s|event_instances)/(\d+)', str(item.get(url_k, "")))
                    if m:
                        inst_id = m.group(1)
                        break
                if not inst_id:
                    ei = item.get("event_instance")
                    if isinstance(ei, dict) and ei.get("id"):
                        inst_id = str(ei["id"])
                    elif isinstance(ei, (int, str)) and str(ei).isdigit():
                        inst_id = str(ei)
                    elif item.get("id"):
                        inst_id = str(item["id"])

                if not inst_id:
                    continue

                # Title
                ev = item.get("event") if isinstance(item.get("event"), dict) else {}
                raw_title = ev.get("title") or ev.get("name") or item.get("event_title") or item.get("title") or ""
                clean_t = clean_show_title(raw_title)

                # Date
                scanned_date = deep_scan_date(item)

                # Sold count
                sold = item.get("reserved_count") or item.get("reserves_count") or item.get("sold") or item.get("count") or 0
                try:
                    sold_int = int(sold)
                except (ValueError, TypeError):
                    sold_int = 0

                if inst_id not in schedules:
                    schedules[inst_id] = {
                        "show_title": clean_t,
                        "show_date": scanned_date,
                        "sold_count": sold_int
                    }
                else:
                    if clean_t and not schedules[inst_id]["show_title"]:
                        schedules[inst_id]["show_title"] = clean_t
                    if scanned_date and not schedules[inst_id]["show_date"]:
                        schedules[inst_id]["show_date"] = scanned_date
                    if sold_int > schedules[inst_id]["sold_count"]:
                        schedules[inst_id]["sold_count"] = sold_int

            api_url = data.get("next") if isinstance(data, dict) else None
    except Exception as e:
        print(f"Notice: Dojour reserve_reports API: {e}")

    print(f"Found {len(schedules)} upcoming Dojour show schedules.")
    dojour_door_rows = []

    # Step 3: For each show, resolve dates & pull guest reservations
    for idx, (instance_id, meta) in enumerate(schedules.items()):
        show_title = meta.get("show_title", "")
        show_date = meta.get("show_date", "")

        # Fallback query to direct event_instance if date or title is missing
        if not show_date or not show_title:
            try:
                inst_resp = session.get(f"https://dojour.us/api/event_instances/{instance_id}/", headers=headers, timeout=10)
                if inst_resp.status_code == 200:
                    inst_data = inst_resp.json()
                    if not show_date:
                        show_date = deep_scan_date(inst_data)
                        meta["show_date"] = show_date
                    if not show_title:
                        ev_inst = inst_data.get("event") if isinstance(inst_data.get("event"), dict) else {}
                        show_title = clean_show_title(ev_inst.get("title") or inst_data.get("title") or "")
                        meta["show_title"] = show_title
            except Exception:
                pass

        # Query reservation report
        report_url = f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/"
        report_data = None
        try:
            r_resp = session.get(report_url, headers=headers, timeout=15)
            if r_resp.status_code == 404:
                r_resp = session.get(f"https://dojour.us/api/event_instances/{instance_id}/reserve_report", headers=headers, timeout=15)
            if r_resp.status_code == 200:
                report_data = r_resp.json()
        except Exception as e:
            print(f"Notice: Instance {instance_id} report: {e}")

        # Scan report_data for show date if still unpopulated
        if not show_date and report_data:
            show_date = deep_scan_date(report_data)
            meta["show_date"] = show_date

        # Extract reservation records
        res_list = []
        if isinstance(report_data, list):
            res_list = report_data
        elif isinstance(report_data, dict):
            for k in ["results", "reserves", "reservations", "reserve_list", "attendees", "guests", "orders", "tickets", "data"]:
                if k in report_data and isinstance(report_data[k], list) and len(report_data[k]) > 0:
                    res_list = report_data[k]
                    break
            if not res_list:
                for v in report_data.values():
                    if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                        res_list = v
                        break

        # Generate Door List rows for this show
        show_ticket_count = 0
        for a_idx, res in enumerate(res_list):
            if not isinstance(res, dict):
                continue

            res_id = str(res.get("id") or res.get("reserve_id") or res.get("reservation_id") or a_idx)
            unique_id = f"dj_{instance_id}_{res_id}"
            g_name, g_email, g_tickets = extract_guest_details(res)
            show_ticket_count += g_tickets

            row = [
                unique_id,       # Col A: Unique ID
                show_date,       # Col B: Show Date ('Sat, Sep 19 • 7:00 PM')
                show_title,      # Col C: Show Title ('Alex Dragicevich')
                g_name,          # Col D: Guest Name
                g_email,         # Col E: Email
                g_tickets,       # Col F: Tickets
                "Dojour",        # Col G: Source
                False,           # Col H: Checked In
                ""               # Col I: Check-In Time
            ]
            dojour_door_rows.append(row)

        if show_ticket_count > meta["sold_count"]:
            meta["sold_count"] = show_ticket_count

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
