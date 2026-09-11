import os
import time
import gspread
from playwright.sync_api import sync_playwright

SHEET_NAME = "Dojour Ticket Counts"

# If running inside GitHub Actions, reconstruct the credentials files from the secrets
if "DOJOUR_STATE_JSON" in os.environ:
    with open("state.json", "w") as f:
        f.write(os.environ["DOJOUR_STATE_JSON"])

if "GOOGLE_SERVICE_ACCOUNT_JSON" in os.environ:
    with open("service_account.json", "w") as f:
        f.write(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

def get_ticket_data():
    collected_results = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state="state.json")
        page = context.new_page()

        def handle_response(response):
            if "reserve_reports" in response.url and response.status == 200:
                try:
                    data = response.json()
                    for item in data.get("results", []):
                        item_id = item.get("id")
                        if item_id and item_id not in seen_ids:
                            seen_ids.add(item_id)
                            collected_results.append(item)
                except Exception:
                    pass

        page.on("response", handle_response)
        page.goto("https://dojour.us/", wait_until="networkidle")
        time.sleep(2)

        last_count = 0
        for _ in range(20):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            if len(collected_results) == last_count:
                break
            last_count = len(collected_results)

        browser.close()

    rows = [["Event Title", "Date", "Sold", "Remaining", "Limit", "Last Updated"]]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    for item in collected_results:
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
