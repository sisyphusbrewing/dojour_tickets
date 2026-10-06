import os
import re
import sys
import requests
from datetime import datetime

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").replace("https://", "").rstrip("/")
if SHOPIFY_STORE and not SHOPIFY_STORE.endswith(".myshopify.com"):
    SHOPIFY_STORE = f"{SHOPIFY_STORE}.myshopify.com"

CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
TARGET_HANDLE = "comedy-and-events"
API_VERSION = "2024-01"

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'march': 3, 'april': 4, 'june': 6, 'july': 7, 'sept': 9
}

def get_shopify_access_token():
    url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
    resp = requests.post(url, json={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    })
    if resp.status_code != 200:
        print(f"❌ Auth failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    return resp.json().get("access_token")

def get_headers(token):
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }

def find_events_collection(token):
    headers = get_headers(token)
    all_collections = []

    # 1. Fetch Automated Collections (Smart Collections)
    smart_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/smart_collections.json"
    smart_resp = requests.get(smart_url, headers=headers)
    if smart_resp.status_code == 200:
        for c in smart_resp.json().get("smart_collections", []):
            all_collections.append({
                "id": c["id"],
                "title": c["title"],
                "handle": c["handle"],
                "is_smart": True,
                "sort_order": c.get("sort_order")
            })

    # 2. Fetch Manual Collections (Custom Collections)
    custom_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections.json"
    custom_resp = requests.get(custom_url, headers=headers)
    if custom_resp.status_code == 200:
        for c in custom_resp.json().get("custom_collections", []):
            all_collections.append({
                "id": c["id"],
                "title": c["title"],
                "handle": c["handle"],
                "is_smart": False,
                "sort_order": c.get("sort_order")
            })

    print(f"Discovered {len(all_collections)} collection(s) on store:")
    for c in all_collections:
        type_str = "Automated" if c["is_smart"] else "Manual"
        print(f"  • [{type_str}] \"{c['title']}\" (handle: {c['handle']}, ID: {c['id']})")

    # Match exact handle
    for c in all_collections:
        if c["handle"].lower() == TARGET_HANDLE.lower():
            return c

    # Match handle or title containing 'comedy' and 'event'
    for c in all_collections:
        text = f"{c['title']} {c['handle']}".lower()
        if "comedy" in text and ("event" in text or "show" in text or "ticket" in text):
            return c

    # Match any collection containing 'comedy'
    for c in all_collections:
        if "comedy" in f"{c['title']} {c['handle']}".lower():
            return c

    return None

def extract_event_date(title, variants, current_date=None):
    if current_date is None:
        current_date = datetime.now()

    if "ticket fee" in title.lower() or "facility fee" in title.lower():
        return datetime(9999, 12, 31)

    if "every thursday" in title.lower() or "open mic" in title.lower():
        return datetime(current_date.year, current_date.month, current_date.day)

    all_texts = [v.get("title", "") for v in variants] + [title]
    month_regex = r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b'
    dates_found = []

    for text in all_texts:
        if not text:
            continue
        matches = re.finditer(rf'{month_regex}\.?\s*(\d{{1,2}})', text, re.I)
        for m in matches:
            m_str = m.group(1).lower()[:3]
            m_num = MONTH_MAP.get(m_str)
            d_num = int(m.group(2))

            y_match = re.search(r'\b(202\d)\b', text)
            if y_match:
                y_num = int(y_match.group(1))
            else:
                if m_num < current_date.month - 2:
                    y_num = current_date.year + 1
                else:
                    y_num = current_date.year

            try:
                dates_found.append(datetime(y_num, m_num, d_num))
            except ValueError:
                pass

    if dates_found:
        return min(dates_found)
    return datetime(9998, 12, 31)

def main():
    print("=" * 60)
    print("SISYPHUS BREWING • CHRONOLOGICAL COLLECTION SORTER")
    print("=" * 60)
    token = get_shopify_access_token()
    headers = get_headers(token)

    col = find_events_collection(token)
    if not col:
        print("❌ Could not match an events collection on this store.")
        sys.exit(1)

    col_id = col["id"]
    print(f"\n✓ Matched collection: \"{col['title']}\" (ID: {col_id}, Handle: {col['handle']})")

    # 1. Fetch all products in this collection
    prods_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/collections/{col_id}/products.json?limit=250"
    p_resp = requests.get(prods_url, headers=headers)
    if p_resp.status_code != 200:
        print(f"❌ Failed to load products ({p_resp.status_code}): {p_resp.text}")
        sys.exit(1)
