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
COLLECTION_HANDLE = "comedy-and-events"
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
        print(f"❌ Auth failed: {resp.text}")
        sys.exit(1)
    return resp.json().get("access_token")

def run_graphql(token, query, variables=None):
    url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json"
    }
    resp = requests.post(url, headers=headers, json={"query": query, "variables": variables or {}})
    data = resp.json()
    if "errors" in data:
        raise Exception(f"GraphQL error: {data['errors']}")
    return data.get("data", {})

def extract_event_date(title, variant_titles, current_date=None):
    if current_date is None:
        current_date = datetime.now()

    if "ticket fee" in title.lower() or "facility fee" in title.lower():
        return datetime(9999, 12, 31)

    if "every thursday" in title.lower() or "open mic" in title.lower():
        return datetime(current_date.year, current_date.month, current_date.day)

    all_texts = list(variant_titles) + [title]
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
    token = get_shopify_access_token()
    query = """
    query getCollection($handle: String!) {
      collectionByHandle(handle: $handle) {
        id
        title
        sortOrder
        products(first: 100) {
          edges {
            node {
              id
              title
              handle
              variants(first: 20) {
                nodes { id title }
              }
            }
          }
        }
      }
    }
    """
    res = run_graphql(token, query, {"handle": COLLECTION_HANDLE})
    col = res.get("collectionByHandle")
    if not col:
        print(f"Collection '{COLLECTION_HANDLE}' not found.")
        return

    collection_id = col["id"]
    products = [edge["node"] for edge in col.get("products", {}).get("edges", [])]

    # Ensure MANUAL sort
    if col.get("sortOrder") != "MANUAL":
        update_mutation = """
        mutation setManual($input: CollectionInput!) {
          collectionUpdate(input: $input) { collection { id sortOrder } }
        }
        """
        run_graphql(token, update_mutation, {"input": {"id": collection_id, "sortOrder": "MANUAL"}})

    sorted_products = sorted(
        products,
        key=lambda p: (
            extract_event_date(p["title"], [v["title"] for v in p.get("variants", {}).get("nodes", [])]),
            p["title"]
        )
    )

    current_ids = [p["id"] for p in products]
    target_ids = [p["id"] for p in sorted_products]

    moves = []
    working = list(current_ids)
    for i, target_id in enumerate(target_ids):
        current_idx = working.index(target_id)
        if current_idx != i:
            moves.append({"id": target_id, "newPosition": str(i)})
            working.remove(target_id)
            working.insert(i, target_id)

    if not moves:
        print("✓ All events are already in perfect chronological order!")
        return

    print(f"Reordering {len(moves)} products in '{COLLECTION_HANDLE}'...")
    reorder_mutation = """
    mutation reorder($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        job { id }
        userErrors { field message }
      }
    }
    """
    run_graphql(token, reorder_mutation, {"id": collection_id, "moves": moves})
    print("✓ Successfully sorted all events!")

if __name__ == "__main__":
    main()
