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
# 1. SHOPIFY INTEGRATION
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
    m = re.search(r"(?:event_instances|instances|reservations)/(\d+)", href)
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

def discover_all_schedules(page) -> list[dict]:
    """
    Loads all upcoming reservations directly and expands the full table.
    """
    page.goto(DOJOUR_RESERVATIONS_URL, wait_until="networkidle")
    current_url = page.url
    print(f"[Dojour] Loaded page: {current_url}")

    if "login" in current_url.lower():
        print("[Dojour] ERROR: Redirected to login page. DOJOUR_STATE secret is expired or invalid.")
        return []

    schedules_by_id = {}
    prev_discovered = 0
    no_growth_count = 0

    for attempt in range(1, 20):
        # 1. Click explicit "Load More" / pagination controls if present
        for sel in [
            "button:has-text('Load More')", "button:has-text('Show More')", "button:has-text('More')",
            "a:has-text('Load More')", "a:has-text('Show More')", ".load-more"
        ]:
            elem = page.locator(sel).first
            if elem.count() and elem.is_visible():
                print(f"[Dojour] Clicking '{sel}' on attempt {attempt}")
                try:
                    elem.click(timeout=2000)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    pass

        # 2. Scroll the last item into view to trigger lazy loaders
        rows = page.locator("tr, div.reservation-row, [role='row']").all()
        if rows:
            try:
                rows[-1].scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

        # 3. Scroll all internal overflow containers
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

        # 4. Extract schedule IDs from table rows
        for row in page.locator("tr, div.reservation-row, [role='row']").all():
            row_text = row.inner_text()
            for link in row.locator("a").all():
                href = link.get_attribute("href") or ""
                link_text = link.inner_text()
                is_cap = bool(re.search(r"\d+/\d+|spots left", link_text, re.IGNORECASE))
                inst_id = extract_instance_id_from_href(href)
                if inst_id and (is_cap or "reservations" in href or "instances" in href):
                    if inst_id not in schedules_by_id:
                        schedules_by_id[inst_id] = {
                            "instance_id": inst_id,
                            "raw_text": row_text,
                            "report_url": f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
                        }

        # 5. Fallback anchor scan across the whole page
        if not schedules_by_id:
            for link in page.locator("a").all():
                href = link.get_attribute("href") or ""
                link_text = link.inner_text()
                if re.search(r"\d+/\d+|spots left", link_text, re.IGNORECASE) or "reservations/" in href:
                    inst_id = extract_instance_id_from_href(href)
                    if inst_id and inst_id not in schedules_by_id:
                        schedules_by_id[inst_id] = {
                            "instance_id": inst_id,
                            "raw_text": link_text,
                            "report_url": f"https://dojour.us/api/event_instances/{inst_id}/reserve_report/"
                        }

        current_count = len(schedules_by_id)
        if current_count > prev_discovered:
            prev_discovered = current_count
            no_growth_count = 0
        else:
            no_growth_count += 1
            if no_growth_count >= 3:
                break

    print(f"[Dojour] Discovered {len(schedules_by_id)} upcoming schedules.")
    return list(schedules_by_id.values())

def fetch_dojour_tickets(context) -> list[list]:
    """
    Pulls reports from discovered schedules using in-page fetch to bypass 401 errors.
    """
    page = context.new_page()
    page.set_viewport_size({"width": 1920, "height": 1080})

    captured_auth_headers = {}
    def on_request(req):
        if "/api/" in req.url:
            for k, v in req.headers.items():
                if k.lower() in ("authorization", "x-csrftoken", "x-requested-with"):
                    captured_auth_headers[k] = v

    page.on("request", on_request)

    schedules = discover_all_schedules(page)
    dojour_rows = []

    for item in schedules:
        report_url = item["report_url"]
        instance_id = item["instance_id"]

        # In-browser session request
        report_res = page.evaluate("""async ({ url, extraHeaders }) => {
            try {
                let h = {
                    'Accept': 'application/json, text/plain, */*',
                    'X-Requested-With': 'XMLHttpRequest',
                    ...extraHeaders
                };
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    const v = localStorage.getItem(k);
                    if (/token|auth|jwt/i.test(k)) {
                        try {
                            const p = JSON.parse(v);
                            const t = p.token || p.key || p.authToken || p.access_token;
                            if (t) h['Authorization'] = (t.startsWith('Token ') || t.startsWith('Bearer ')) ? t : `Token ${t}`;
                        } catch(e) {
                            const clean = v.replace(/["']/g, '').trim();
                            if (clean && clean.length > 8) {
                                h['Authorization'] = (clean.startsWith('Token ') || clean.startsWith('Bearer ')) ? clean : `Token ${clean}`;
                            }
                        }
                    }
                }
                const m = document.cookie.match(/(?:^|;\s*)(?:csrftoken|csrf)=([^;]+)/);
                if (m) h['X-CSRFToken'] = m[1];

                const resp = await fetch(url, {
                    method: 'GET',
                    headers: h,
                    credentials: 'include'
                });
                if (resp.status === 200) {
                    return { status: 200, data: await resp.json() };
                }
                return { status: resp.status, data: null, error: `HTTP ${resp.status}` };
            } catch (err) {
                return { status: -1, data: null, error: err.toString() };
            }
        }""", {"url": report_url, "extraHeaders": captured_auth_headers})

        # Fallback tab navigation if evaluate encounters non-200
        if not report_res or report_res.get("status") != 200:
            tab = context.new_page()
            try:
                nav_resp = tab.goto(report_url, wait_until="domcontentloaded", timeout=12000)
                if nav_resp and nav_resp.status == 200:
                    raw_text = tab.locator("body").inner_text()
                    report_res = {"status": 200, "data": json.loads(raw_text)}
                else:
                    status_code = nav_resp.status if nav_resp else "timeout"
                    print(f"[Dojour] HTTP {status_code} fetching report for schedule {instance_id}")
            except Exception as e:
                print(f"[Dojour] Tab navigation error for schedule {instance_id}: {e}")
            finally:
                tab.close()

        if not report_res or report_res.get("status") != 200 or not report_res.get("data"):
            continue

        data = report_res["data"]
        show_title, show_date = extract_event_meta(data, item["raw_text"])

        reservations = []
        if isinstance(data, list):
            reservations = data
        elif isinstance(data, dict):
            for key in ("reservations", "reports", "items", "results", "orders"):
                if key in data and isinstance(data[key], list):
                    reservations = data[key]
                    break

        for i, res in enumerate(reservations):
            res_id = str(res.get("id") or res.get("reservation_id") or res.get("pk") or i)
            unique_id = f"dj_{instance_id}_{res_id}"

            name = (
                res.get("name") or
                f"{res.get('first_name', '')} {res.get('last_name', '')}".strip() or
                res.get("guest_name") or
                "Dojour Guest"
            ).strip()
            email = (res.get("email") or res.get("guest_email") or "").strip().lower()
            tickets = int(res.get("ticket_count") or res.get("quantity") or res.get("tickets") or res.get("count") or 1)

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
    print(f"[Dojour] Extracted {len(dojour_rows)} total reservations.")
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

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state)
            dojour_rows = fetch_dojour_tickets(context)
            browser.close()
    else:
        print("[Dojour] DOJOUR_STATE is missing. Skipping Dojour extraction.")

    all_rows = shopify_rows + dojour_rows
    sync_to_google_sheet(all_rows)

if __name__ == "__main__":
    main()
