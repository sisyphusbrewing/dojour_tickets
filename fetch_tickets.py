import os
import time
import requests
import gspread
from playwright.sync_api import sync_playwright

SHEET_NAME = "Dojour Ticket Counts"

if "DOJOUR_STATE_JSON" in os.environ:
    with open("state.json", "w") as f:
        f.write(os.environ["DOJOUR_STATE_JSON"])

if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
    with open("service_account.json", "w") as f:
        f.write(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

def get_ticket_data():
    intercepted_headers = {}
    initial_data = {}
    cookies = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="state.json")
        page = context.new_page()

        def handle_request(request):
            nonlocal intercepted_headers
            if "reserve_reports" in request.url:
                intercepted_headers = request.headers

        def handle_response(response):
            nonlocal initial_data
            if "reserve_reports" in response.url and response.status == 200:
                try:
                    initial_data = response.json()
                except Exception:
                    pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        print("Opening DoJour to initialize session...")
        page.goto("https://dojour.us/", wait_until="networkidle")
        time.sleep(2)

        # Grab cookies from the authenticated context
        cookies = context.cookies()
        browser.close()

    if not initial_data:
        raise Exception("Failed to load initial event data from DoJour.")

    # Build a requests session with both intercepted headers and browser cookies
    session = requests.Session()
    session.headers.update(intercepted_headers)
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", "dojour.us"))

    all_results = initial_data.get("results", [])
    next_url = initial_data.get("next")
    page_num = 2

    while next_url:
        print(f"Fetching page {page_num}...")
        resp = session.get(next_url)
        if resp.status_code != 200:
            print(f"Warning: Page {page_num} returned HTTP {resp.status_code}. Stopping pagination.")
            break

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        all_results.extend(results)
        next_url = data.get("next")
        page_num += 1

    print(f"Total events found across all pages: {len(all_results)}")

    rows = [["Event Title", "Date", "Sold", "Remaining", "Limit", "Last Updated"]]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    for item in all_results:
        title = item.get("event", {}).get("title", "Unknown")
        start_dt = item.get("start_dt", "")[:16].replace("T", " ")
        offer = item.get("offer")
        if offer:
            sold = offer.get("active_count", 0)
            remaining = offer.get("remaining_count", 0)
            limit = offer.get("limit", 0)
        else:
            sold = remaining = limit = "-"
        rows.append([title, start_dt, sold, remaining, limit, now_str])

    return rows

def sync_to_sheets():
    print("Fetching DoJour ticket data...")
    rows = get_ticket_data()

    print(f"Connecting to Google Sheets ('{SHEET_NAME}')...")
    gc = gspread.service_account(filename="service_account.json")
    sheet = gc.open(SHEET_NAME).sheet1

    sheet.clear()
    sheet.update(rows)
    print(f"Success! Synced {len(rows)-1} shows to your Google Sheet.")

if __name__ == "__main__":
    sync_to_sheets()
