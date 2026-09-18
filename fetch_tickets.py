import re
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

CENTRAL_TZ = ZoneInfo("America/Chicago")

def clean_dojour_title(raw_title: str) -> str:
    """
    Cleans Dojour title strings.
    Example: 'Chris Higgins /// September 25 & 26' -> 'Chris Higgins'
    Strips ticket/capacity counts like '35/90\n55 spots left'.
    """
    # Remove capacity counts
    cleaned = re.sub(r"\d+/\d+.*?(spots left|remaining)?", "", raw_title, flags=re.IGNORECASE)
    # Remove trailing date strings separated by triple slashes
    cleaned = cleaned.split("///")[0]
    # Remove excessive whitespace and line breaks
    return re.sub(r"\s+", " ", cleaned).strip()

def format_dojour_date(raw_date_str: str) -> str:
    """
    Converts ISO or standard Dojour date strings into 'Fri, Sep 18 • 7:00 PM' in America/Chicago.
    """
    if not raw_date_str:
        return "TBD"
    
    try:
        # Standard ISO 8601 parsing
        dt = datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))
        dt_central = dt.astimezone(CENTRAL_TZ)
        # Matches Shopify date format
        return dt_central.strftime("%a, %b %-d • %-I:%M %p")
    except Exception:
        # Fallback if raw text (e.g. 'Sep 25, 2026 7:00 PM')
        try:
            dt = datetime.strptime(raw_date_str.strip(), "%b %d, %Y %I:%M %p")
            dt_central = dt.replace(tzinfo=CENTRAL_TZ)
            return dt_central.strftime("%a, %b %-d • %-I:%M %p")
        except Exception:
            return raw_date_str.strip()

def discover_all_schedules(page) -> list[dict]:
    """
    Scrolls through the reservation table until no new schedule IDs appear.
    Extracts instance IDs and schedule metadata directly from the DOM and reserve report links.
    """
    page.goto("https://dojour.us/admin-tools/reservations/", wait_until="networkidle")

    # Scroll the window and any internal table wrappers
    last_count = 0
    stable_cycles = 0

    while stable_cycles < 3:
        # Extract schedule links currently rendered
        links = page.locator("a[href*='/api/event_instances/'], a[href*='/reserve_report/']").all()
        current_count = len(links)

        if current_count > last_count:
            last_count = current_count
            stable_cycles = 0
        else:
            stable_cycles += 1

        # Scroll document and inner containers
        page.evaluate("""() => {
            window.scrollTo(0, document.body.scrollHeight);
            document.querySelectorAll('div, main, section, table').forEach(el => {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }""")
        page.wait_for_timeout(1000)

    # Scrape table rows to extract metadata paired with instance IDs
    schedules = []
    rows = page.locator("tr, div.reservation-row, .event-instance-row").all()

    for row in rows:
        text = row.inner_text()
        report_link = row.locator("a[href*='reserve_report']").first
        if not report_link.count():
            continue

        href = report_link.get_attribute("href")
        instance_match = re.search(r"/event_instances/(\d+)/", href)
        if not instance_match:
            continue
        
        instance_id = instance_match.group(1)
        schedules.append({
            "instance_id": instance_id,
            "raw_text": text,
            "report_url": f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/"
        })

    # Deduplicate by instance_id
    unique_schedules = {s["instance_id"]: s for s in schedules}.values()
    return list(unique_schedules)

def fetch_dojour_tickets(context) -> list[list]:
    """
    Iterates over all discovered event instances, pulls reserve reports,
    and returns rows strictly mapped to the 9-column schema.
    """
    page = context.new_page()
    schedules = discover_all_schedules(page)
    dojour_rows = []

    for item in schedules:
        report_url = item["report_url"]
        
        # Use Playwright's authenticated request context directly
        response = context.request.get(report_url)
        if response.status != 200:
            continue

        data = response.json()
        
        # Extract show title and start time from payload or parent metadata
        raw_title = data.get("event_title") or data.get("title") or item["raw_text"].split("\n")[0]
        show_title = clean_dojour_title(raw_title)

        raw_time = data.get("starts_at") or data.get("start_time") or ""
        show_date = format_dojour_date(raw_time)

        # Dojour reservations array
        reservations = data.get("reservations", data.get("reports", []))

        for res in reservations:
            # Generate deterministic unique ID
            res_id = str(res.get("id") or res.get("reservation_id") or "")
            unique_id = f"dj_{item['instance_id']}_{res_id}"

            name = (res.get("name") or f"{res.get('first_name', '')} {res.get('last_name', '')}").strip()
            email = (res.get("email") or "").strip().lower()
            tickets = int(res.get("ticket_count") or res.get("quantity") or 1)

            # Strict 9-Column Order:
            # [Unique ID, Show Date, Show Title, Guest Name, Email, Tickets, Source, Checked In, Check-In Time]
            dojour_rows.append([
                unique_id,
                show_date,
                show_title,
                name,
                email,
                tickets,
                "Dojour",
                False,  # Checked In (default; merged later)
                ""      # Check-In Time (default; merged later)
            ])

    page.close()
    return dojour_rows
