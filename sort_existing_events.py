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

    # 1. Direct query by handle on Automated Collections
    print(f"Looking up '{TARGET_HANDLE}' in Smart Collections...")
    smart_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/smart_collections.json?handle={TARGET_HANDLE}"
    s_resp = requests.get(smart_url, headers=headers)
    if s_resp.status_code == 200:
        smart_cols = s_resp.json().get("smart_collections", [])
        if smart_cols:
            c = smart_cols[0]
            print(f"✓ Found Automated Collection: \"{c['title']}\" (ID: {c['id']})")
            return {"id": c["id"], "title": c["title"], "handle": c["handle"], "is_smart": True, "sort_order": c.get("sort_order")}
    else:
        print(f"Notice: Smart collections API returned HTTP {s_resp.status_code}")

    # 2. Direct query by handle on Manual Collections
    print(f"Looking up '{TARGET_HANDLE}' in Custom Collections...")
    custom_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections.json?handle={TARGET_HANDLE}"
    c_resp = requests.get(custom_url, headers=headers)
    if c_resp.status_code == 200:
        custom_cols = c_resp.json().get("custom_collections", [])
        if custom_cols:
            c = custom_cols[0]
            print(f"✓ Found Manual Collection: \"{c['title']}\" (ID: {c['id']})")
            return {"id": c["id"], "title": c["title"], "handle": c["handle"], "is_smart": False, "sort_order": c.get("sort_order")}
    else:
        print(f"Notice: Custom collections API returned HTTP {c_resp.status_code}")

    # 3. Discovery Fallback: Fetch all collections from both endpoints
    print("Direct handle lookup missed. Scanning all store collections...")
    all_cols = []
    
    s_all = requests.get(f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/smart_collections.json", headers=headers)
    if s_all.status_code == 200:
        for c in s_all.json().get("smart_collections", []):
            all_cols.append({"id": c["id"], "title": c["title"], "handle": c["handle"], "is_smart": True, "sort_order": c.get("sort_order")})

    c_all = requests.get(f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections.json", headers=headers)
    if c_all.status_code == 200:
        for c in c_all.json().get("custom_collections", []):
            all_cols.append({"id": c["id"], "title": c["title"], "handle": c["handle"], "is_smart": False, "sort_order": c.get("sort_order")})

    print(f"Found {len(all_cols)} total collection(s):")
    for c in all_cols:
        print(f"  • \"{c['title']}\" (handle: {c['handle']})")
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
    print("SISYPHUS BREWING • CHRONOLOGICAL COLLECTION SORTER v2")
    print("=" * 60)
    token = get_shopify_access_token()
    headers = get_headers(token)

    col = find_events_collection(token)
    if not col:
        print("❌ Could not locate the events collection.")
        sys.exit(1)

    col_id = col["id"]
    print(f"\n✓ Operating on collection: \"{col['title']}\" (ID: {col_id})")

    # 1. Fetch products
    prods_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/collections/{col_id}/products.json?limit=250"
    p_resp = requests.get(prods_url, headers=headers)
    if p_resp.status_code != 200:
        print(f"❌ Failed to load products ({p_resp.status_code}): {p_resp.text}")
        sys.exit(1)

    products = p_resp.json().get("products", [])
    print(f"Loaded {len(products)} products from collection.")

    if not products:
        print("No products found in collection.")
        return

    # 2. Ensure collection sort order is manual
    if col.get("sort_order") != "manual":
        print("Setting collection sort_order to 'manual'...")
        endpoint = "smart_collections" if col["is_smart"] else "custom_collections"
        key = "smart_collection" if col["is_smart"] else "custom_collection"
        requests.put(
            f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/{endpoint}/{col_id}.json",
            headers=headers,
            json={key: {"id": col_id, "sort_order": "manual"}}
        )

    # 3. Sort products chronologically
    sorted_products = sorted(
        products,
        key=lambda p: (
            extract_event_date(p["title"], p.get("variants", [])),
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
            moves.append({
                "id": f"gid://shopify/Product/{target_id}",
                "newPosition": str(i)
            })
            working.remove(target_id)
            working.insert(i, target_id)

    if not moves:
        print("✓ All events are already in perfect chronological order!")
        return

    print(f"Reordering {len(moves)} event(s) via GraphQL...")
    gql_url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
    reorder_mutation = """
    mutation reorder($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        job { id }
        userErrors { field message }
      }
    }
    """
    g_resp = requests.post(gql_url, headers=headers, json={
        "query": reorder_mutation,
        "variables": {
            "id": f"gid://shopify/Collection/{col_id}",
            "moves": moves
        }
    })
    errors = g_resp.json().get("data", {}).get("collectionReorderProducts", {}).get("userErrors", [])
    if errors:
        print(f"⚠️ Reorder notice: {errors}")
    else:
        print("✓ Order updated in Shopify!")

    print("\n" + "=" * 60)
    print("UPCOMING SHOW LINEUP (CHRONOLOGICAL):")
    print("=" * 60)
    for idx, p in enumerate(sorted_products, start=1):
        d = extract_event_date(p["title"], p.get("variants", []))
        d_str = d.strftime("%b %d, %Y") if d.year < 9000 else "General"
        print(f"  {idx:2d}. [{d_str}] {p['title']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
