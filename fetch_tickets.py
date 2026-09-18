import os
import re
import time
import gspread
from playwright.sync_api import sync_playwright

SHEET_NAME = "Dojour Ticket Counts"
DOOR_LIST_TAB = "Door List"

if "DOJOUR_STATE_JSON" in os.environ:
    with open("state.json", "w") as f:
        f.write(os.environ["DOJOUR_STATE_JSON"])

if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
    with open("service_account.json", "w") as f:
        f.write(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

FORBIDDEN_FETCH_HEADERS = {
    "accept-charset", "accept-encoding", "access-control-request-headers",
    "access-control-request-method", "connection", "content-length",
    "cookie", "cookie2", "date", "dnt", "expect", "host", "keep-alive",
    "origin", "referer", "set-cookie", "te", "trailer", "transfer-encoding",
    "upgrade", "via"
}

def clean_headers(raw_headers):
    return {
        k: v for k, v in raw_headers.items()
        if not k.startswith(":") and k.lower() not in FORBIDDEN_FETCH_HEADERS
    }

def run_sync():
    all_events = []
    seen_event_ids = set()
    intercepted_headers = {}
    initial_data = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state="state.json",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        def handle_request(request):
            nonlocal intercepted_headers
            if "reserve_reports" in request.url:
                intercepted_headers = request.headers

        def handle_response(response):
            nonlocal initial_data
            if "reserve_reports" in response.url and response.status == 200:
                try:
                    data = response.json()
                    if not initial_data and "results" in data:
                        initial_data = data
                    for item in data.get("results", []):
                        eid = item.get("id") or item.get("showing")
                        if eid and eid not in seen_event_ids:
                            seen_event_ids.add(eid)
                            all_events.append(item)
                except Exception:
                    pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        print("Opening DoJour dashboard...")
        page.goto("https://dojour.us/", wait_until="networkidle")
        page.wait_for_timeout(3000)

        headers_for_fetch = clean_headers(intercepted_headers)

        # 1. Paginate dashboard events to discover all schedule IDs
        next_url = initial_data.get("next")
        page_num = 2
        while next_url:
            print(f"Fetching overview page {page_num}...")
            try:
                data = page.evaluate("""async ({url, headers}) => {
                    const res = await fetch(url, { headers, credentials: 'include' });
                    return res.ok ? await res.json() : null;
                }""", {"url": next_url, "headers": headers_for_fetch})

                if not data:
                    break

                for item in data.get("results", []):
                    eid = item.get("id") or item.get("showing")
                    if eid and eid not in seen_event_ids:
                        seen_event_ids.add(eid)
                        all_events.append(item)

                next_url = data.get("next")
                page_num += 1
            except Exception:
                break

        print(f"Discovered {len(all_events)} active show schedules.")

        # 2. Fetch attendee details for each active schedule
        door_entries = []
        for event in all_events:
            # Try getting schedule ID
            schedule_id = event.get("showing") or event.get("id")
            if not schedule_id:
                continue

            report_url = f"https://dojour.us/api/event_instances/{schedule_id}/reserve_report/"
            print(f"Fetching attendee list for schedule #{schedule_id}...")

            try:
                report_data = page.evaluate("""async ({url, headers}) => {
                    const res = await fetch(url, { headers, credentials: 'include' });
                    return res.ok ? await res.json() : null;
                }""", {"url": report_url, "headers": headers_for_fetch})

                if not report_data:
                    continue

                for res in report_data.get("reservation_set", []):
                    if res.get("is_cancelled"):
                        continue

                    order_key = f"dj_{res.get('encrypted_pk')}"
                    first = res.get("first_name", "")
                    last = res.get("last_name", "")
                    name = f"{first} {last}".strip() or "Guest"
                    email = res.get("email", "")
                    show_title = res.get("event_title", "Comedy Show")
                    start_dt = res.get("start_dt", "")[:16].replace("T", " ")

                    # Sum ticket quantity across all selected options
                    ticket_count = sum(opt.get("count", 0) for opt in res.get("option_set", []))
                    if ticket_count == 0 and res.get("ticket_set"):
                        ticket_count = len(res.get("ticket_set"))

                    door_entries.append([
                        order_key,
                        start_dt,
                        show_title,
                        name,
                        email,
                        ticket_count,
                        "Dojour",
                        "FALSE",  # Default Checked In status
                        ""        # Check-in timestamp blank initially
                    ])
            except Exception as e:
                print(f"Error fetching schedule {schedule_id}: {e}")

        browser.close()

    # 3. Update Google Sheets
    print(f"Connecting to Google Sheets ('{SHEET_NAME}')...")
    gc = gspread.service_account(filename="service_account.json")
    workbook = gc.open(SHEET_NAME)

    # --- Sync Door List (Safe Upsert) ---
    try:
        door_sheet = workbook.worksheet(DOOR_LIST_TAB)
    except gspread.WorksheetNotFound:
        door_sheet = workbook.add_worksheet(title=DOOR_LIST_TAB, rows=1000, cols=10)
        door_sheet.append_row(["Unique ID", "Show Date", "Show Title", "Guest Name", "Email", "Tickets", "Source", "Checked In", "Check-In Time"])

    existing_ids = set(door_sheet.col_values(1))  # Column A contains Unique IDs
    new_rows = [row for row in door_entries if row[0] not in existing_ids]

    if new_rows:
        door_sheet.append_rows(new_rows)
        print(f"Added {len(new_rows)} new Dojour attendees to '{DOOR_LIST_TAB}'.")
    else:
        print("No new attendees to add. All existing check-in data preserved.")

    # --- Sync Ticket Overview (Sheet 1) ---
    overview_sheet = workbook.sheet1
    overview_rows = [["Event Title", "Date", "Sold", "Remaining", "Limit", "Last Updated"]]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    for item in all_events:
        title = item.get("event", {}).get("title", "Unknown")
        start_dt = item.get("start_dt", "")[:16].replace("T", " ")
        offer = item.get("offer")
        if offer:
            sold = offer.get("active_count", 0)
            remaining = offer.get("remaining_count", 0)
            limit = offer.get("limit", 0)
        else:
            sold = remaining = limit = "-"
        overview_rows.append([title, start_dt, sold, remaining, limit, now_str])

    overview_sheet.clear()
    overview_sheet.update(overview_rows)
    print(f"Updated show counts on Sheet 1.")

if __name__ == "__main__":
    run_sync()
