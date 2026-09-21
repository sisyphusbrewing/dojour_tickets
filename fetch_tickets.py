import os
import re
import json
import requests
from datetime import datetime
import dateutil.parser
import zoneinfo

CENTRAL_TZ = zoneinfo.ZoneInfo("America/Chicago")


# ==========================================
# 1. Authentication & Token Extraction
# ==========================================

def get_dojour_token() -> str:
    """
    Extracts the Django REST usertoken from the DOJOUR_STATE secret or environment.
    """
    # Check direct env var first
    direct_token = os.environ.get("DOJOUR_TOKEN")
    if direct_token:
        return direct_token.strip()

    # Parse DOJOUR_STATE (Playwright storage state JSON or file path)
    state_str = os.environ.get("DOJOUR_STATE", "")
    state_data = {}

    if state_str:
        if os.path.exists(state_str):
            with open(state_str, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        else:
            try:
                state_data = json.loads(state_str)
            except Exception:
                pass

    if not state_data and os.path.exists("dojour_state.json"):
        with open("dojour_state.json", "r", encoding="utf-8") as f:
            state_data = json.load(f)

    # Search cookies for 'usertoken'
    for cookie in state_data.get("cookies", []):
        if cookie.get("name") == "usertoken":
            return cookie.get("value")

    raise ValueError("Could not find 'usertoken' in DOJOUR_STATE or environment.")


# ==========================================
# 2. Date & Title Formatting Helpers
# ==========================================

def clean_show_title(raw_title: str) -> str:
    """
    Normalizes multi-line and multi-day Dojour titles to the comic/event name:
    'Alex Dragicevich /// Comedy - September 18 & 19' -> 'Alex Dragicevich'
    'Geoffrey Asmus // Sisyphus Brewing' -> 'Geoffrey Asmus'
    """
    if not raw_title:
        return ""

    title = raw_title.strip()

    # Split delimiters used by Sisyphus on Dojour
    for delimiter in ["///", "//", " - Comedy", " – Comedy"]:
        if delimiter in title:
            title = title.split(delimiter)[0].strip()

    # Strip any trailing date ranges (e.g. ' - September 18 & 19' or ' - 9/18')
    title = re.sub(
        r'\s*[-–]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d+.*$',
        '',
        title,
        flags=re.IGNORECASE
    )
    title = re.sub(r'\s*[-–]\s*\d{1,2}/\d{1,2}.*$', '', title)

    return title.strip()


def format_show_date(date_val: str) -> str:
    """
    Converts either ISO timestamps or Dojour DOM date strings into the exact
    Shopify target format: 'Sat, Sep 19 • 7:00 PM' (America/Chicago time).
    """
    if not date_val:
        return ""

    raw_str = str(date_val).strip()

    # 1. Parse DOM-style string: "Saturday, September 19th | 7:00pm - 9:00pm"
    dom_match = re.search(
        r'([A-Za-z]+),\s+([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*\|\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)',
        raw_str,
        re.IGNORECASE
    )
    if dom_match:
        weekday_raw, month_raw, day_raw, hour_raw, min_raw, ampm_raw = dom_match.groups()
        weekday = weekday_raw[:3].capitalize()
        month = datetime.strptime(month_raw[:3], "%b").strftime("%b")
        day = str(int(day_raw))
        hour = str(int(hour_raw))
        minute = min_raw if min_raw else "00"
        ampm = ampm_raw.upper()
        return f"{weekday}, {month} {day} • {hour}:{minute} {ampm}"

    # 2. Parse ISO-8601 or standard API timestamps
    try:
        dt = dateutil.parser.parse(raw_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(CENTRAL_TZ)
        else:
            # Assume UTC if naive, then localize
            dt = dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(CENTRAL_TZ)

        weekday = dt.strftime("%a")
        month = dt.strftime("%b")
        day = str(dt.day)
        hour = str(int(dt.strftime("%I")))
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p")
        return f"{weekday}, {month} {day} • {hour}:{minute} {ampm}"
    except Exception:
        return raw_str


# ==========================================
# 3. Schedule Metadata Fetcher (Native API)
# ==========================================

def fetch_dojour_schedules(token: str) -> dict:
    """
    Queries Dojour's native reserve_reports API to fetch upcoming event instances.
    Returns a dictionary mapping instance_id -> { 'title': ..., 'date': ... }
    """
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    url = "https://dojour.us/api/event_instances/reserve_reports/?page_size=100&upcoming=true"
    schedule_map = {}

    while url:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", []) if isinstance(data, dict) else data

        for item in results:
            inst_id = str(item.get("id") or item.get("event_instance_id") or "")
            if not inst_id:
                continue

            # Extract title
            raw_title = ""
            if isinstance(item.get("event"), dict):
                raw_title = item["event"].get("title") or item["event"].get("name") or ""
            if not raw_title:
                raw_title = item.get("title") or item.get("event_title") or ""

            # Extract performance start datetime
            raw_date = (
                item.get("start")
                or item.get("start_datetime")
                or item.get("starts_at")
                or item.get("start_time")
                or item.get("date_string")
            )

            schedule_map[inst_id] = {
                "show_title": clean_show_title(raw_title),
                "show_date": format_show_date(raw_date)
            }

        # Follow pagination if more than 100 upcoming shows exist
        url = data.get("next") if isinstance(data, dict) else None

    return schedule_map


# ==========================================
# 4. Master Dojour Ticket Sync Function
# ==========================================

def fetch_dojour_tickets() -> list[list]:
    """
    Pulls upcoming Dojour schedules, queries each instance's reservation list,
    and returns rows adhering to the 9-column Google Sheet schema.
    """
    token = get_dojour_token()
    schedules = fetch_dojour_schedules(token)
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    dojour_rows = []

    for instance_id, meta in schedules.items():
        show_date = meta["show_date"]
        show_title = meta["show_title"]

        report_url = f"https://dojour.us/api/event_instances/{instance_id}/reserve_report/"
        try:
            resp = requests.get(report_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"Skipping instance {instance_id}: Received status {resp.status_code}")
                continue
            report_data = resp.json()
        except Exception as e:
            print(f"Error fetching report for instance {instance_id}: {e}")
            continue

        # Extract reservation records
        reservations = []
        if isinstance(report_data, list):
            reservations = report_data
        elif isinstance(report_data, dict):
            for key in ["reservations", "results", "reserve_list", "data", "guests"]:
                if key in report_data and isinstance(report_data[key], list):
                    reservations = report_data[key]
                    break

        for idx, res in enumerate(reservations):
            # Column A: Unique ID
            res_id = str(res.get("id") or res.get("reservation_id") or idx)
            unique_id = f"dj_{instance_id}_{res_id}"

            # Column D: Guest Name
            guest_name = res.get("name") or res.get("guest_name") or res.get("full_name") or ""
            if not guest_name:
                first = res.get("first_name", "").strip()
                last = res.get("last_name", "").strip()
                guest_name = f"{first} {last}".strip()
            if not guest_name:
                guest_name = "Guest"

            # Column E: Email
            email = res.get("email") or res.get("guest_email") or ""

            # Column F: Tickets
            tickets = (
                res.get("party_size")
                or res.get("tickets")
                or res.get("quantity")
                or res.get("num_tickets")
                or res.get("seats")
                or 1
            )
            try:
                tickets_count = int(tickets)
            except (ValueError, TypeError):
                tickets_count = 1

            # 9-Column Row Schema
            row = [
                unique_id,       # Col A: Unique ID
                show_date,       # Col B: Show Date ('Sat, Sep 19 • 7:00 PM')
                show_title,      # Col C: Show Title ('Alex Dragicevich')
                guest_name,      # Col D: Guest Name
                email,           # Col E: Email
                tickets_count,   # Col F: Tickets (int)
                "Dojour",        # Col G: Source
                False,           # Col H: Checked In (preserved during sheet sync)
                ""               # Col I: Check-In Time (preserved during sheet sync)
            ]
            dojour_rows.append(row)

    print(f"Successfully processed {len(dojour_rows)} Dojour tickets across {len(schedules)} shows.")
    return dojour_rows
