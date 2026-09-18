import os
import json
import re
import sys
import time
import requests
import gspread
from playwright.sync_api import sync_playwright

# Configuration & Constants
SHEET_TITLE = "Dojour Ticket Counts"
DOJOUR_ADMIN_URL = "https://dojour.us/admin-tools/reservations/"
DOJOUR_SCHEDULE_URL = "https://dojour.us/admin-tools/reservations/s/{id}"

DOJOUR_STATE = os.environ.get("DOJOUR_STATE")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_SERVICE_ACCOUNT") or os.environ.get("GOOGLE_CREDENTIALS")
SHOPIFY_CLIENT_ID = (os.environ.get("SHOPIFY_CLIENT_ID") or "").strip().strip("'\"")
SHOPIFY_CLIENT_SECRET = (os.environ.get("SHOPIFY_CLIENT_SECRET") or "").strip().strip("'\"")
SHOPIFY_TOKEN = (os.environ.get("SHOPIFY_TOKEN") or "").strip().strip("'\"")

raw_store = (os.environ.get("SHOPIFY_STORE") or "sisyphus-brewing").replace("https://", "").replace("http://", "").strip("/").strip("'\"")
subdomain = raw_store.replace(".myshopify.com", "")
SHOPIFY_STORE = f"{subdomain}.myshopify.com"


def get_gspread_client():
    if not GOOGLE_CREDENTIALS:
        print("Error: Neither GOOGLE_SERVICE_ACCOUNT nor GOOGLE_CREDENTIALS is set.")
        sys.exit(1)
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    return gspread.service_account_from_dict(creds_dict)


def fetch_shopify_tickets():
    token = SHOPIFY_TOKEN

    if not token:
        if not (SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET):
            print("[Shopify] Missing client ID or secret. Skipping Shopify pull.")
            return []

        print(f"[Shopify] Requesting access token via Client Credentials from {SHOPIFY_STORE}...")
        auth_url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
        auth_payload = {
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
            "grant_type": "client_credentials"
        }
        
        try:
            auth_resp = requests.post(auth_url, data=auth_payload, timeout=15)
            if auth_resp.status_code == 200:
                token = auth_resp.json().get("access_token")
            else:
                print(f"[Shopify] Client credentials rejected ({auth_resp.status_code}): {auth_resp.text[:150]}")
                return []
        except Exception as e:
            print(f"[Shopify] Connection error: {e}")
            return []

    headers = {"X-Shopify-Access-Token": token}
    print(f"[Shopify] Fetching newest paid orders from {SHOPIFY_STORE}...")
    orders_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/orders.json?status=any&limit=250&order=created_at+desc"
    
    try:
        resp = requests.get(orders_url, headers=headers, timeout=20)
    except Exception as e:
        print(f"[Shopify] Request failed: {e}")
        return []

    if resp.status_code != 200:
        print(f"[Shopify] Error fetching orders ({resp.status_code}): {resp.text[:150]}")
        return []

    orders = resp.json().get("orders", [])
    shopify_rows = []

    for order in orders:
        if order.get("financial_status") not in ["paid", "authorized"]:
            continue

        customer = order.get("customer") or {}
        billing = order.get("billing_address") or {}
        first = customer.get("first_name") or billing.get("first_name", "")
        last = customer.get("last_name") or billing.get("last_name", "")
        guest_name = f"{first} {last}".strip() or billing.get("name", "Website Guest")
        email = order.get("email") or customer.get("email", "")
        order_num = order.get("name", "")

        for item in order.get("line_items", []):
            item_name = item.get("name", "")
            lower_name = item_name.lower()
            if any(term in lower_name for term in ["tip", "deposit", "gift card"]) and not any(t in lower_name for t in ["ticket", "show", "comedy"]):
                continue

            raw_title = item.get("title") or item_name
            variant = item.get("variant_title") or ""

            if " - " in raw_title:
                parts = raw_title.split(" - ")
                show_title = parts[0].strip()
                date_part = parts[1].split(" / ")[0].strip()
                show_date = variant if variant else date_part
            else:
                show_title = raw_title
                show_date = variant

            shopify_rows.append([
                f"shopify_{order_num}",
                show_date,
                show_title,
                guest_name,
                email,
                str(item.get("quantity", 1)),
                "Website",
                "FALSE",
                ""
            ])

    print(f"[Shopify] Processed {len(shopify_rows)} ticket items from {len(orders)} orders.")
    return shopify_rows


def fetch_dojour_data():
    if not DOJOUR_STATE:
        print("[Dojour] Missing DOJOUR_STATE. Skipping Dojour pull.")
        return [], []

    with open("state.json", "w") as f:
        f.write(DOJOUR_STATE)

    overview_rows = []
    attendee_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="state.json")
        page = context.new_page()

        intercepted_reports = {}
        captured_auth = {"header": None}

        def on_request(req):
            if "reserve_report" in req.url:
                auth = req.headers.get("authorization")
                if auth and not captured_auth["header"]:
                    captured_auth["header"] = auth
                    print("[Dojour] Successfully captured live session token.")

        def on_response(res):
            if "reserve_report" in res.url and res.status == 200:
                try:
                    data = res.json()
                    m = re.search(r"/event_instances/(\d+)/reserve_report", res.url)
                    if m:
                        intercepted_reports[m.group(1)] = data
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print("[Dojour] Navigating to admin reservations table...")
        page.goto(DOJOUR_ADMIN_URL, wait_until="networkidle")
        time.sleep(2)

        # -------------------------------------------------------------
        # Infinite Scroll & "Load More" Pagination Handler
        # -------------------------------------------------------------
        print("[Dojour] Expanding all paginated schedules (scrolling & clicking Load More)...")
        prev_count = 0
        stagnant_cycles = 0

        while stagnant_cycles < 3:
            # 1. Scroll main window and internal scroll containers to bottom
            page.evaluate("""() => {
                window.scrollTo(0, document.body.scrollHeight);
                const containers = document.querySelectorAll('div, table, tbody, main');
                for (const el of containers) {
                    if (el.scrollHeight > el.clientHeight && el.clientHeight > 0) {
                        el.scrollTop = el.scrollHeight;
                    }
                }
            }""")
            time.sleep(1.5)

            # 2. Check for and click any "Load More" / "Show More" buttons
            clicked_button = False
            load_selectors = [
                "button:has-text('Load More')",
                "button:has-text('Load more')",
                "button:has-text('Show More')",
                "button:has-text('Show more')",
                "button:has-text('More')",
                "a:has-text('Load More')",
                "a:has-text('Show More')",
                ".load-more",
                "#load-more"
            ]

            for sel in load_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        btn.scroll_into_view_if_needed()
                        btn.click(timeout=3000)
                        clicked_button = True
                        print("[Dojour] Clicked 'Load More' button.")
                        time.sleep(2)
                        break
                except Exception:
                    pass

            # 3. Check if new schedule links were loaded
            curr_count = page.locator("a[href*='/admin-tools/reservations/s/']").count()
            if curr_count > prev_count or clicked_button:
                print(f"[Dojour] Loaded {curr_count} schedules so far...")
                prev_count = curr_count
                stagnant_cycles = 0
            else:
                stagnant_cycles += 1
                time.sleep(1)

        schedule_links = page.locator("a[href*='/admin-tools/reservations/s/']").all()
        schedules = []

        for link in schedule_links:
            href = link.get_attribute("href") or ""
            sched_match = re.search(r"/admin-tools/reservations/s/(\d+)", href)
            if not sched_match:
                continue

            schedule_id = sched_match.group(1)
            row_el = link.locator("xpath=./ancestor::tr")
            row_text = row_el.inner_text().split("\t")

            show_title = link.inner_text().strip()
            show_date = row_text[1].strip() if len(row_text) > 1 else ""
            tickets_sold = row_text[2].strip() if len(row_text) > 2 else "0"

            schedules.append({
                "id": schedule_id,
                "title": show_title,
                "date": show_date,
                "sold": tickets_sold
            })

            overview_rows.append([show_title, show_date, tickets_sold])

        print(f"[Dojour] Total active schedules found: {len(schedules)}. Querying reserve reports...")

        # Collect attendee reports for every discovered schedule
        for sched in schedules:
            sched_id = sched["id"]

            if captured_auth["header"]:
                report_url = f"/api/event_instances/{sched_id}/reserve_report/"
                auth_val = captured_auth["header"]
                report_data = page.evaluate("""async ({url, auth}) => {
                    try {
                        const res = await fetch(url, {
                            headers: {
                                'Accept': 'application/json',
                                'Authorization': auth
                            }
                        });
                        if (!res.ok) return null;
                        return await res.json();
                    } catch(e) {
                        return null;
                    }
                }""", {"url": report_url, "auth": auth_val})
                if report_data:
                    intercepted_reports[sched_id] = report_data

            if sched_id not in intercepted_reports:
                page.goto(DOJOUR_SCHEDULE_URL.format(id=sched_id), wait_until="networkidle")
                time.sleep(1)

            data = intercepted_reports.get(sched_id, {})
            reservations = []
            if isinstance(data, dict):
                reservations = data.get("reservation_set") or data.get("results") or []
            elif isinstance(data, list):
                reservations = data

            for idx, res_item in enumerate(reservations):
                res_id = (
                    res_item.get("id") or 
                    res_item.get("reservation_id") or 
                    res_item.get("order_id") or 
                    res_item.get("code") or 
                    res_item.get("pk")
                )
                uid = f"dj_{res_id}" if res_id else f"dj_{sched_id}_{idx}"

                name = f"{res_item.get('first_name', '')} {res_item.get('last_name', '')}".strip()
                if not name:
                    name = res_item.get("name") or "Dojour Guest"

                email = res_item.get("email", "")
                tix = res_item.get("num_tickets") or res_item.get("tickets") or res_item.get("quantity") or 1
                event_date = res_item.get("schedule_name") or sched["date"]
                event_title = sched["title"]

                attendee_rows.append([
                    uid,
                    event_date,
                    event_title,
                    name,
                    email,
                    str(tix),
                    "Dojour",
                    "FALSE",
                    ""
                ])

        browser.close()

    print(f"[Dojour] Collected {len(attendee_rows)} individual Dojour reservations.")
    return overview_rows, attendee_rows


def sync_to_google_sheets(overview_rows, attendee_rows, shopify_rows):
    gc = get_gspread_client()
    spreadsheet = gc.open(SHEET_TITLE)

    # 1. Update Overview Sheet (Sheet 1)
    if overview_rows:
        overview_sheet = spreadsheet.sheet1
        overview_sheet.clear()
        overview_header = [["Show Title", "Show Date", "Dojour Sold"]]
        overview_sheet.update(overview_header + overview_rows)
        print(f"[Google Sheets] Updated Sheet 1 with {len(overview_rows)} overview rows.")

    # 2. Get or Create "Door List" Tab
    try:
        door_sheet = spreadsheet.worksheet("Door List")
    except gspread.exceptions.WorksheetNotFound:
        door_sheet = spreadsheet.add_worksheet(title="Door List", rows=1000, cols=10)

    # 3. Preserve Existing Check-In Statuses (Columns H & I)
    existing_data = door_sheet.get_all_values()
    existing_checkins = {}

    if len(existing_data) > 1:
        for row in existing_data[1:]:
            if not row or not row[0]:
                continue
            uid = row[0].strip()
            checked_in = row[7] if len(row) > 7 else "FALSE"
            check_time = row[8] if len(row) > 8 else ""
            existing_checkins[uid] = (checked_in, check_time)

    # 4. Merge Incoming Rows
    all_incoming = attendee_rows + shopify_rows
    final_rows = [[
        "Unique ID", "Show Date", "Show Title", "Guest Name", 
        "Email", "Tickets", "Source", "Checked In", "Check-In Time"
    ]]

    seen_uids = set()
    for row in all_incoming:
        uid = str(row[0]).strip()
        if uid in seen_uids:
            continue
        seen_uids.add(uid)

        if uid in existing_checkins:
            row[7] = existing_checkins[uid][0]
            row[8] = existing_checkins[uid][1]

        final_rows.append(row)

    # 5. Overwrite the Door List Tab
    door_sheet.clear()
    door_sheet.update(final_rows)
    print(f"[Google Sheets] Successfully synced {len(final_rows) - 1} total attendees to 'Door List'.")


def main():
    print("Starting ticket sync...")
    overview_rows, dojour_attendees = fetch_dojour_data()
    shopify_attendees = fetch_shopify_tickets()

    if not dojour_attendees and not shopify_attendees:
        print("No attendees found from either Dojour or Shopify. Aborting sheet update.")
        return

    sync_to_google_sheets(overview_rows, dojour_attendees, shopify_attendees)
    print("Sync complete.")


if __name__ == "__main__":
    main()
