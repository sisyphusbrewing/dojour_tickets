import os
import re
import json
import sys
import requests
from datetime import datetime, timezone, timedelta
import zoneinfo

# Optional gspread import for Service Account setup
try:
    import gspread
except ImportError:
    gspread = None

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")

# Events that ended more than GRACE_HOURS ago are excluded
# (Allows door staff to check people in late at night without the show disappearing)
GRACE_HOURS = 12


# ==============================================================================
# 1. Text & Date Normalization Helpers
# ==============================================================================

def clean_show_title(raw_title: str) -> str:
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


def parse_show_datetime(date_val) -> datetime | None:
    """
    Parses various date formats (epochs, ISO strings, human strings) into a
    timezone-aware datetime in America/Chicago.
    """
    if not date_val:
        return None

    # Epoch timestamp
    if isinstance(date_val, (int, float)):
        if 1500000000 <= date_val <= 2500000000:
            return datetime.fromtimestamp(date_val, CENTRAL_TZ)
        elif 1500000000000 <= date_val <= 2500000000000:
            return datetime.fromtimestamp(date_val / 1000.0, CENTRAL_TZ)
        return None

    raw_str = str(date_val).strip()
    now = datetime.now(CENTRAL_TZ)

    # Formats like: "Sat, Sep 19 • 7:00 PM" or "Sat, Nov 14, 2027 • 7:00 PM"
    m_formatted = re.match(
        r'^[A-Z][a-z]{2},\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+•\s+(\d{1,2}):(\d{2})\s+(AM|PM)$',
        raw_str,
        re.IGNORECASE
    )
    if m_formatted:
        month_s, day_s, year_s, hour_s, min_s, ampm = m_formatted.groups()
        try:
            year = int(year_s) if year_s else now.year
            dt_cand = datetime.strptime(
                f"{year} {month_s} {day_s} {hour_s}:{min_s} {ampm.upper()}",
                "%Y %b %d %I:%M %p"
            ).replace(tzinfo=CENTRAL_TZ)
            # If date is omitted and is >90 days in past, belongs to next year
            if not year_s and dt_cand < now - timedelta(days=90):
                dt_cand = dt_cand.replace(year=year + 1)
            return dt_cand
        except Exception:
            pass

    # DOM/Natural text: 'Saturday, September 19th | 7:00pm - 9:00pm' or 'Fri, Sep 18 • 8:00 PM'
    dom_match = re.search(
        r'(?:([A-Za-z]+),\s+)?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\s*(?:[|@•\-,\s]\s*|\s+at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        raw_str,
        re.IGNORECASE
    )
    if dom_match:
        weekday_raw, month_raw, day_raw, year_raw, hour_raw, min_raw, ampm_raw = dom_match.groups()
        try:
            month = month_raw[:3].capitalize()
            day = int(day_raw)
            hour = int(hour_raw)
            minute = int(min_raw) if min_raw else 0
            year = int(year_raw) if year_raw else now.year
            ampm = ampm_raw.upper()

            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

            month_num = datetime.strptime(month, "%b").month
            dt_cand = datetime(year, month_num, day, hour, minute, tzinfo=CENTRAL_TZ)

            # Year boundary adjustment when year is omitted
            if not year_raw and dt_cand < now - timedelta(days=180):
                dt_cand = dt_cand.replace(year=year + 1)
            return dt_cand
        except Exception:
            pass

    # ISO-8601 timestamps (handles +00:00, Z, etc.)
    try:
        iso_str = raw_str.replace("Z", "+00:00")
        if re.search(r'[+-]\d{4}$', iso_str):
            iso_str = iso_str[:-2] + ":" + iso_str[-2:]
        if " " in iso_str and "T" not in iso_str:
            iso_str = iso_str.replace(" ", "T")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is not None:
            return dt.astimezone(CENTRAL_TZ)
        return dt.replace(tzinfo=CENTRAL_TZ)
    except Exception:
        pass

    return None


def format_show_date(dt: datetime | None) -> str:
    if not dt:
        return ""
    now = datetime.now(CENTRAL_TZ)
    # If the show is in a future year (e.g. 2027), retain the year in the label
    if dt.year != now.year:
        return dt.strftime("%a, %b %-d, %Y • %-I:%M %p")
    return dt.strftime("%a, %b %-d • %-I:%M %p")


def is_past_event(dt: datetime | None) -> bool:
    """Returns True if the event occurred before current Central Time minus grace period."""
    if not dt:
        return False
    cutoff = datetime.now(CENTRAL_TZ) - timedelta(hours=GRACE_HOURS)
    return dt < cutoff


def extract_tickets_count(res: dict) -> int:
    if isinstance(res.get("full_ticket_set"), list) and len(res["full_ticket_set"]) > 0:
        return len(res["full_ticket_set"])

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
# 2. Dojour Ticket Fetcher
# ==============================================================================

def get_dojour_token() -> str:
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


def fetch_dojour_tickets():
    token = get_dojour_token()
    session = requests.Session()
    session.cookies.set("usertoken", token, domain="dojour.us")
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    # Discover upcoming instance IDs
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

                show_dt = parse_show_datetime(item.get("start_dt"))
                if is_past_event(show_dt):
                    continue

                if inst_id not in instance_ids:
                    instance_ids.append(inst_id)

                opt_title = ""
                if item.get("option_set") and isinstance(item["option_set"], list) and len(item["option_set"]) > 0:
                    opt_title = item["option_set"][0].get("title", "")

                initial_meta[inst_id] = {
                    "show_title": clean_show_title(opt_title or item.get("title", "")),
                    "show_datetime": show_dt
                }

            api_url = data.get("next") if isinstance(data, dict) else None
    except Exception as e:
        print(f"Notice during Dojour schedule discovery: {e}")

    print(f"Found {len(instance_ids)} upcoming active Dojour shows.")
    dojour_tickets = []

    for inst_id in instance_ids:
        meta = initial_meta.get(inst_id, {"show_title": "", "show_datetime": None})
        report_url = f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
        report_data = None

        try:
            resp = session.get(report_url, headers=headers, timeout=15)
            if resp.status_code == 404:
                resp = session.get(f"https://dojour.us/api/event_instances/{inst_id}/reserve_report", headers=headers, timeout=15)
            if resp.status_code == 200:
                report_data = resp.json()
        except Exception as e:
            print(f"Error querying Dojour instance {inst_id}: {e}")

        if not report_data or not isinstance(report_data, dict):
            continue

        res_list = report_data.get("reservation_set", [])
        detected_title = meta["show_title"]
        detected_dt = meta["show_datetime"]

        if not detected_dt and res_list:
            for r in res_list:
                if r.get("start_dt"):
                    detected_dt = parse_show_datetime(r["start_dt"])
                    break

        # Double check past date
        if is_past_event(detected_dt):
            continue

        if not detected_title and res_list:
            for r in res_list:
                if r.get("event_title"):
                    detected_title = clean_show_title(r["event_title"])
                    break

        if not detected_title and report_data.get("option_set") and len(report_data["option_set"]) > 0:
            detected_title = clean_show_title(report_data["option_set"][0].get("title", ""))

        formatted_date = format_show_date(detected_dt)

        for r_idx, res in enumerate(res_list):
            if not isinstance(res, dict):
                continue
            if res.get("is_cancelled") is True:
                continue
            if res.get("waitlist") is True or res.get("is_on_waitlist") is True:
                continue
            if res.get("checkout_complete") is False:
                continue

            r_dt = parse_show_datetime(res.get("start_dt")) or detected_dt
            if is_past_event(r_dt):
                continue

            pk = str(res.get("encrypted_pk") or res.get("id") or r_idx)
            unique_id = f"dj_{inst_id}_{pk}"
            r_title = clean_show_title(res.get("event_title")) or detected_title

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

            email = (res.get("email") or "").strip()
            if not email and isinstance(res.get("user"), dict):
                email = (res["user"].get("email") or "").strip()

            tickets = extract_tickets_count(res)

            dojour_tickets.append({
                "unique_id": unique_id,
                "show_date": format_show_date(r_dt) or formatted_date,
                "show_title": r_title,
                "guest_name": guest_name,
                "email": email,
                "tickets": tickets,
                "source": "Dojour",
                "_sort_dt": r_dt or detected_dt
            })

    print(f"Retrieved {len(dojour_tickets)} upcoming Dojour attendee reservations.")
    return dojour_tickets


# ==============================================================================
# 3. Shopify Ticket Fetcher (With Strict Past Event Filtering)
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

    # Only look at orders from the last 90 days to avoid scanning years of history
    created_at_min = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://{store}/admin/api/2024-01/orders.json?status=any&limit=250&created_at_min={created_at_min}"
    shopify_tickets = []

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

                    # Gather candidates to resolve show date
                    date_cands = [variant_title]
                    for prop in item.get("properties", []):
                        if any(k in prop.get("name", "").lower() for k in ["date", "time", "show"]):
                            date_cands.insert(0, str(prop.get("value", "")))
                    date_cands.append(item_title)

                    show_dt = None
                    for cand in date_cands:
                        parsed = parse_show_datetime(cand)
                        if parsed:
                            show_dt = parsed
                            break

                    # CRITICAL FILTER: Skip if the show is already in the past!
                    if is_past_event(show_dt):
                        continue

                    # If date couldn't be parsed at all, also avoid leaking stale products
                    if not show_dt:
                        continue

                    formatted_date = format_show_date(show_dt)
                    item_id = str(item.get("id"))
                    unique_id = f"shopify_{order_id}_{item_id}"
                    tickets_count = int(item.get("quantity", 1))

                    shopify_tickets.append({
                        "unique_id": unique_id,
                        "show_date": formatted_date,
                        "show_title": show_title,
                        "guest_name": guest_name,
                        "email": email,
                        "tickets": tickets_count,
                        "source": "Website",
                        "_sort_dt": show_dt
                    })

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

    print(f"Retrieved {len(shopify_tickets)} upcoming tickets from Shopify.")
    return shopify_tickets


# ==============================================================================
# 4. Supabase Upsert Sync & Cleanup
# ==============================================================================

def sync_to_google_sheets(tickets: list):
    """
    Syncs the consolidated ticket list to Google Sheets.
    Supports either:
      1. GOOGLE_SHEET_WEBHOOK_URL (Google Apps Script Web App - simplest, no GCP keys)
      2. gspread with GOOGLE_SHEET_ID and service account credentials
    """
    if not tickets:
        return

    # Method A: Google Apps Script Webhook (Recommended & Simplest)
    webhook_url = os.environ.get("GOOGLE_SHEET_WEBHOOK_URL")
    if webhook_url:
        print("Syncing ticket roster to Google Sheets via Webhook...")
        try:
            resp = requests.post(webhook_url, json={"tickets": tickets}, timeout=30)
            if resp.status_code == 200:
                print("Successfully synced records to Google Sheets via Webhook.")
                return
            else:
                print(f"Google Sheet Webhook returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Error calling Google Sheet Webhook: {e}")

    # Method B: gspread with Service Account
    sheet_id = os.environ.get("GOOGLE_SHEET_ID") or os.environ.get("GOOGLE_SHEET_NAME")
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not sheet_id:
        print("Note: Set GOOGLE_SHEET_WEBHOOK_URL or GOOGLE_SHEET_ID to enable Google Sheets export.")
        return

    if not gspread:
        print("gspread library not installed. Run 'pip install gspread' or use GOOGLE_SHEET_WEBHOOK_URL.")
        return

    try:
        if sa_json:
            if os.path.exists(sa_json):
                gc = gspread.service_account(filename=sa_json)
            else:
                sa_data = json.loads(sa_json)
                gc = gspread.service_account_from_dict(sa_data)
        elif os.path.exists("credentials.json"):
            gc = gspread.service_account(filename="credentials.json")
        else:
            print("No service account credentials found for gspread.")
            return

        # Open sheet by key or name
        if sheet_id.isalnum() and len(sheet_id) > 25:
            sh = gc.open_by_key(sheet_id)
        else:
            sh = gc.open(sheet_id)

        worksheet = sh.get_worksheet(0)
        worksheet.clear()

        headers = ["Unique ID", "Show Date", "Show Title", "Guest Name", "Email", "Tickets", "Source"]
        rows = [headers]
        for t in tickets:
            rows.append([
                t.get("unique_id", ""),
                t.get("show_date", ""),
                t.get("show_title", ""),
                t.get("guest_name", ""),
                t.get("email", ""),
                t.get("tickets", 1),
                t.get("source", "")
            ])

        worksheet.update(rows)
        print(f"Successfully wrote {len(tickets)} rows to Google Sheet '{sh.title}'.")
    except Exception as e:
        print(f"Error syncing to Google Sheet via gspread: {e}")


def sync_to_supabase(tickets: list):
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    chunk_size = 300
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/tickets?on_conflict=unique_id"

    for i in range(0, len(tickets), chunk_size):
        chunk = tickets[i:i + chunk_size]
        resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
        if resp.status_code not in [200, 201]:
            print(f"Supabase upsert error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()

    print(f"Successfully upserted {len(tickets)} records into Supabase.")


def cleanup_past_shows_from_supabase():
    """
    Scans the tickets table in Supabase and deletes rows for shows that are
    now in the past so the door dropdown only contains current and upcoming shows.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }

    try:
        # Fetch distinct shows currently in Supabase
        endpoint = f"{supabase_url.rstrip('/')}/rest/v1/tickets?select=show_date"
        resp = requests.get(endpoint, headers=headers, timeout=20)
        if resp.status_code != 200:
            return

        all_dates = set(r["show_date"] for r in resp.json() if r.get("show_date"))
        past_dates = []

        for d_str in all_dates:
            dt = parse_show_datetime(d_str)
            if dt and is_past_event(dt):
                past_dates.append(d_str)

        if not past_dates:
            return

        print(f"Purging {len(past_dates)} expired show dates from Supabase door list...")
        for p_date in past_dates:
            del_url = f"{supabase_url.rstrip('/')}/rest/v1/tickets?show_date=eq.{requests.utils.quote(p_date)}"
            del_resp = requests.delete(del_url, headers=headers, timeout=20)
            if del_resp.status_code in [200, 204]:
                print(f"  - Removed past show: {p_date}")
    except Exception as e:
        print(f"Notice during past show cleanup: {e}")


# ==============================================================================
# 5. Main Execution
# ==============================================================================

def main():
    print("Starting Sisyphus Ticket Consolidation to Supabase & Google Sheets...")
    shopify_tickets = []
    dojour_tickets = []

    try:
        shopify_tickets = fetch_shopify_tickets()
    except Exception as e:
        print(f"Shopify sync error: {e}")

    try:
        dojour_tickets = fetch_dojour_tickets()
    except Exception as e:
        print(f"Dojour sync error: {e}")

    all_tickets = shopify_tickets + dojour_tickets

    # Sort strictly chronologically by show date so earlier shows come first
    # and 2027 shows appear at the very bottom
    max_future_dt = datetime.max.replace(tzinfo=CENTRAL_TZ)
    all_tickets.sort(key=lambda t: t.get("_sort_dt") or max_future_dt)

    # Clean up the internal sorting key before database & sheets insertion
    for t in all_tickets:
        t.pop("_sort_dt", None)

    print(f"Consolidated upcoming total: {len(all_tickets)} tickets (chronologically ordered).")

    if all_tickets:
        # Sync to Supabase
        sync_to_supabase(all_tickets)
        # Sync to Google Sheets
        sync_to_google_sheets(all_tickets)
    else:
        print("No upcoming ticket records found.")

    # Clean up past shows so the door staff doesn't see old shows in the dropdown
    cleanup_past_shows_from_supabase()
    print("Database and Sheet sync complete!")


if __name__ == "__main__":
    main()
