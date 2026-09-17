import os
import re
import time
import gspread
from playwright.sync_api import sync_playwright

SHEET_NAME = "Dojour Ticket Counts"

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

def get_ticket_data():
    all_results = []
    seen_ids = set()
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

                    results = data.get("results", [])
                    for item in results:
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

        page.on("request", handle_request)
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

        # Sanitize intercepted headers for browser fetch (keeping auth tokens)
        clean_headers = {
            k: v for k, v in intercepted_headers.items()
            if not k.startswith(":") and k.lower() not in FORBIDDEN_FETCH_HEADERS
        }

        # 1. Paginate via API using authenticated context and headers
        next_url = initial_data.get("next")
        page_num = 2

        while next_url:
            print(f"Fetching page {page_num} via API...")
            try:
                data = page.evaluate("""async ({url, headers}) => {
                    try {
                        const res = await fetch(url, {
                            method: 'GET',
                            headers: headers,
                            credentials: 'include'
                        });
                        if (!res.ok) return { error: res.status };
                        return await res.json();
                    } catch (err) {
                        return { error: err.message };
                    }
                }""", {"url": next_url, "headers": clean_headers})

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

        # 2. Fallback: UI clicking if items remain
        load_more_attempts = 0
        while load_more_attempts < 30:
            btn = page.locator("button, a, [role='button']").filter(has_text=re.compile(r"load more", re.I)).first
            if not btn.is_visible():
                btn = page.get_by_text(re.compile(r"load more", re.I)).first

            if btn.is_visible():
                prev_count = len(all_results)
                print(f"Clicking 'Load More' button (currently at {prev_count} events)...")
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    page.wait_for_timeout(2500)
                except Exception:
                    break

                if len(all_results) == prev_count:
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
        sheet.update(rows)
    except Exception:
        sheet.update(values=rows)
    print(f"Success! Synced {len(rows)-1} shows to your Google Sheet.")

if __name__ == "__main__":
    sync_to_sheets()
