import os
import json
import re
from playwright.sync_api import sync_playwright

def run_diagnostics():
    dojour_state = os.environ.get("DOJOUR_STATE")
    if not dojour_state:
        print("ERROR: DOJOUR_STATE environment variable is missing.")
        return

    try:
        storage_state = json.loads(dojour_state)
    except Exception:
        storage_state = dojour_state

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        # 1. Inspect cookies & session storage
        print("\n=== 1. AUTH & SESSION CHECK ===")
        cookies = context.cookies()
        print(f"Stored cookies: {[c['name'] + ' (' + c['domain'] + ')' for c in cookies]}")

        # 2. Intercept all background API requests
        api_requests = []
        def track_request(req):
            if any(term in req.url for term in ["api", "reserve", "report", "instances"]):
                api_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "headers": {k: v for k, v in req.headers.items() if k.lower() in ["authorization", "x-csrftoken", "cookie", "referer"]}
                })
        page.on("request", track_request)

        # 3. Navigate to upcoming reservations
        target_url = "https://dojour.us/admin-tools/reservations/all/?upcoming=true"
        print(f"\n=== 2. LOADING PAGE: {target_url} ===")
        response = page.goto(target_url, wait_until="networkidle")
        print(f"Final URL: {page.url}")
        print(f"Page Title: {page.title()}")

        # Check localStorage tokens inside the browser
        storage = page.evaluate("""() => {
            let items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                items[k] = localStorage.getItem(k);
            }
            return items;
        }""")
        print(f"localStorage keys: {list(storage.keys())}")
        for k, v in storage.items():
            if any(t in k.lower() for t in ["token", "auth", "user", "session"]):
                print(f"  -> {k}: {v[:80]}...")

        # 4. Inspect links and buttons in the first 3 rows
        print("\n=== 3. DOM ROW & LINK INSPECTION ===")
        rows = page.locator("tr, div.reservation-row, [role='row']").all()
        print(f"Total rows found: {len(rows)}")

        clicked = False
        for idx, row in enumerate(rows[:5]):
            text = row.inner_text().replace("\n", " | ").strip()
            links = row.locator("a, button").all()
            print(f"\nRow {idx + 1}: {text[:100]}...")
            
            for elem in links:
                tag = elem.evaluate("el => el.tagName")
                elem_text = elem.inner_text().strip()
                href = elem.get_attribute("href") or ""
                onclick = elem.get_attribute("onclick") or ""
                classes = elem.get_attribute("class") or ""
                print(f"   [{tag}] text='{elem_text}' href='{href}' class='{classes}' onclick='{onclick}'")

                # Try clicking the capacity link or view button on the first row
                if not clicked and (re.search(r"\d+/\d+|spots", elem_text, re.IGNORECASE) or "reserve" in href):
                    print(f"\n=== 4. CLICKING ELEMENT TO REVEAL REAL API ENDPOINT ===")
                    print(f"Clicking on: {elem_text} ({href})")
                    api_requests.clear()
                    try:
                        elem.click(timeout=3000)
                        page.wait_for_timeout(3000)
                        clicked = True
                    except Exception as e:
                        print(f"Click failed: {e}")

        # 5. Log all requests fired after the click
        print("\n=== 5. CAPTURED NETWORK REQUESTS ON INTERACTION ===")
        if not api_requests:
            print("No background API requests captured during click.")
        for req in api_requests:
            print(f"[{req['method']}] {req['url']}")
            print(f"   Headers: {req['headers']}")

        # 6. Check if click opened a modal or navigated
        print(f"\nCurrent URL after click: {page.url}")
        modal = page.locator(".modal, [role='dialog'], .reservations-list, table").first
        if modal.count() and modal.is_visible():
            print("\nModal/Guest List visible in DOM after click!")
            print(modal.inner_text()[:400])

        browser.close()

if __name__ == "__main__":
    run_diagnostics()
