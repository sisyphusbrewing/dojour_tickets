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

# Exact collection ID from your Shopify Admin URL
COLLECTION_ID = "472787812387"
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

def extract_event_date(title, variants, current_date=None):
    if current_date is None:
        current_date = datetime.now()

    # Utility items go to the very end
    if "ticket fee" in title.lower() or "facility fee" in title.lower():
        return datetime(9999, 12, 31)

    # Weekly open mic stays near the top
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
                # Wrap upcoming shows into next year if they are earlier in the calendar
                diff = (m_num - current_date.month) % 12
                if diff <= 9 and m_num < current_date.month:
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

def ensure_manual_sort(token, headers):
    # Try updating smart collection first, then custom collection
    smart_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/smart_collections/{COLLECTION_ID}.json"
    s_res = requests.get(smart_url, headers=headers)
    if s_res.status_code == 200:
        c = s_res.json().get("smart_collection", {})
        if c.get("sort_order") != "manual":
            print("Updating collection sort_order to 'manual'...")
            requests.put(smart_url, headers=headers, json={"smart_collection": {"id": int(COLLECTION_ID), "sort_order": "manual"}})
        return c.get("title", "Smart Collection")

    custom_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections/{COLLECTION_ID}.json"
    c_res = requests.get(custom_url, headers=headers)
    if c_res.status_code == 200:
        c = c_res.json().get("custom_collection", {})
        if c.get("sort_order") != "manual":
            print("Updating collection sort_order to 'manual'...")
            requests.put(custom_url, headers=headers, json={"custom_collection": {"id": int(COLLECTION_ID), "sort_order": "manual"}})
        return c.get("title", "Custom Collection")

    # Fallback GraphQL update
    gql_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    mutation = """
    mutation setManual($input: CollectionInput!) {
      collectionUpdate(input: $input) {
        collection { id title sortOrder }
      }
    }
    """
    res = requests.post(gql_url, headers=headers, json={"query": mutation, "variables": {"input": {"id": f"gid://shopify/Collection/{COLLECTION_ID}", "sortOrder": "MANUAL"}}})
    data = res.json().get("data", {}).get("collectionUpdate", {}).get("collection", {})
    return data.get("title", "Collection")

def main():
    print("=" * 60)
    print("SISYPHUS BREWING • CHRONOLOGICAL COLLECTION SORTER (DIRECT ID)")
    print("=" * 60)
    token = get_shopify_access_token()
    headers = get_headers(token)

    col_title = ensure_manual_sort(token, headers)
    print(
