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
    all_results = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Desktop viewport ensures the "Load More" button isn't hidden by mobile styling
        context = browser.new_context(
            storage_state="state.json",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        initial_data = {}

        def handle_response(response):
            nonlocal initial_data
            if "reserve_reports" in response.url and response.status == 200:
                try:
                    data = response.json()
                    if not initial_data and "results" in data:
                        initial_data = data

                    results = data.get("results", [])
                    for item in results:
                        # De-duplicate by show identity
                        item_id = item.get("id") or (
                            item.get("event", {}).get("title"),
                            item.get("start_dt"),
                            item.get("offer", {}).get("id") if item.get("offer") else None
                        )
                        if item_id not in seen_ids:
                            seen_ids.add(item_id)
                            all_results.append(item)
                except Exception:
                    pass

        page.on("response", handle_response)

        print("Opening DoJour dashboard...")
        page.goto("https://dojour.us/", wait_until="networkidle")
        page.wait_for_timeout(3000)

        if not all_results:
            page.wait_for_timeout(3000)

        if not all_results:
            browser.close()
            raise Exception("Failed to load initial event data. Check if your state.json session secret has expired.")

        print(f"Captured initial batch ({len(all_results)} events).")

        # 1. First, attempt fast pagination via the browser's own fetch context
        next_url = initial_data.get("next")
        page_num = 2

        while next_url:
            print(f"Fetching page {page_num} via browser context...")
            try:
                data = page.evaluate("""async (url) => {
                    const res = await fetch(url, { credentials: 'include' });
                    if (!res.ok) return { error: res.status };
                    return await res.json();
                }""", next_url)

                if not data or "error" in data:
                    print(f"API fetch returned status {data.get('error') if data else 'unknown'}. Falling back to UI click.")
                    break

                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    item_id = item.get("id") or (
                        item.get("event", {}).get("title"),
                        item.get("start_dt"),
                        item.get("offer", {}).get("id") if item.get("offer") else None
                    )
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        all_results.append(item)

                next_url = data.get("next")
                page_num += 1
            except Exception as e:
                print(f"Browser API pagination ended: {e}")
                break

        # 2. If events remain behind a UI 'Load More' button, click through the rest
        load_more_attempts = 0
        while load_more_attempts < 30:
            load_more_btn = page.locator("button:has-text('Load More'), a:has-text('Load More'), text=/Load More/i").first
            if load_more_btn.is_visible():
                prev_count = len(all_results)
                print(f"Clicking 'Load More' button (currently at {prev_count} events)...")
                try:
                    load_more_btn.scroll_into_view_if_needed()
                    load_more_btn.click()
                    page.wait_for_timeout(2500)
                except Exception:
                    break

                if len(all_results) == prev_count:
                    # Give slow AJAX calls an extra moment before giving up
                    page.wait_for_timeout(2500)
                    if len(all_results) == prev_count:
                        print("No additional events returned after clicking 'Load More'.")
                        break
                load_more_attempts += 1
            else:
                break

        browser.close()

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
    try:
        sheet.update(values=rows)
    except TypeError:
        sheet.update(rows)
    print(f"Success! Synced {len(rows)-1} shows to your Google Sheet.")

if __name__ == "__main__":
    sync_to_sheets()
