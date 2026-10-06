import os
import re
import sys
import requests
from datetime import datetime

SHOPIFY_STORE = os.environ.get('SHOPIFY_STORE', '').replace('https://', '').rstrip('/')
if SHOPIFY_STORE and not SHOPIFY_STORE.endswith('.myshopify.com'):
    SHOPIFY_STORE = f'{SHOPIFY_STORE}.myshopify.com'

CLIENT_ID = os.environ.get('SHOPIFY_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('SHOPIFY_CLIENT_SECRET', '')
COLLECTION_ID = '472787812387'
API_VERSION = '2024-01'

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'march': 3, 'april': 4, 'june': 6, 'july': 7, 'sept': 9
}

def get_shopify_access_token():
    url = f'https://{SHOPIFY_STORE}/admin/oauth/access_token'
    resp = requests.post(url, json={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    })
    if resp.status_code != 200:
        print(f'Auth failed: {resp.status_code} - {resp.text}')
        sys.exit(1)
    return resp.json().get('access_token')

def get_headers(token):
    return {
        'X-Shopify-Access-Token': token,
        'Content-Type': 'application/json'
    }

def extract_event_date(title, variants, current_date=None):
    if current_date is None:
        current_date = datetime.now()

    t_lower = title.lower()
    if 'ticket fee' in t_lower or 'facility fee' in t_lower:
        return datetime(9999, 12, 31)

    if 'every thursday' in t_lower or 'open mic' in t_lower:
        return datetime(current_date.year, current_date.month, current_date.day)

    all_texts = [v.get('title', '') for v in variants] + [title]
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
    smart_url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/smart_collections/{COLLECTION_ID}.json'
    s_res = requests.get(smart_url, headers=headers)
    if s_res.status_code == 200:
        c = s_res.json().get('smart_collection', {})
        if c.get('sort_order') != 'manual':
            print('Setting smart collection sort_order to manual...')
            requests.put(smart_url, headers=headers, json={'smart_collection': {'id': int(COLLECTION_ID), 'sort_order': 'manual'}})
        return c.get('title', 'Smart Collection')

    custom_url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/custom_collections/{COLLECTION_ID}.json'
    c_res = requests.get(custom_url, headers=headers)
    if c_res.status_code == 200:
        c = c_res.json().get('custom_collection', {})
        if c.get('sort_order') != 'manual':
            print('Setting custom collection sort_order to manual...')
            requests.put(custom_url, headers=headers, json={'custom_collection': {'id': int(COLLECTION_ID), 'sort_order': 'manual'}})
        return c.get('title', 'Custom Collection')

    return 'Collection'

def main():
    print('============================================================')
    print('SISYPHUS BREWING • COLLECTION SORTER')
    print('============================================================')
    token = get_shopify_access_token()
    headers = get_headers(token)

    col_title = ensure_manual_sort(token, headers)
    print(f'Target Collection: {col_title} (ID: {COLLECTION_ID})')

    prods_url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/collections/{COLLECTION_ID}/products.json?limit=250'
    p_resp = requests.get(prods_url, headers=headers)
    if p_resp.status_code != 200:
        print(f'Failed to load products: {p_resp.status_code} - {p_resp.text}')
        sys.exit(1)

    products = p_resp.json().get('products', [])
    print(f'Loaded {len(products)} products from collection.')

    if not products:
        print('No products found in collection.')
        return

    sorted_products = sorted(
        products,
        key=lambda p: (
            extract_event_date(p['title'], p.get('variants', [])),
            p['title']
        )
    )

    current_ids = [p['id'] for p in products]
    target_ids = [p['id'] for p in sorted_products]

    moves = []
    working = list(current_ids)
    for i, target_id in enumerate(target_ids):
        current_idx = working.index(target_id)
        if current_idx != i:
            moves.append({
                'id': f'gid://shopify/Product/{target_id}',
                'newPosition': str(i)
            })
            working.remove(target_id)
            working.insert(i, target_id)

    if not moves:
        print('All events are already in perfect chronological order!')
        return

    print(f'Reordering {len(moves)} event(s) to match calendar dates...')
    gql_url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json'
    reorder_mutation = '''
    mutation reorder($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        job { id }
        userErrors { field message }
      }
    }
    '''
    g_resp = requests.post(gql_url, headers=headers, json={
        'query': reorder_mutation,
        'variables': {
            'id': f'gid://shopify/Collection/{COLLECTION_ID}',
            'moves': moves
        }
    })
    errors = g_resp.json().get('data', {}).get('collectionReorderProducts', {}).get('userErrors', [])
    if errors:
        print(f'Reorder error: {errors}')
    else:
        print('Order successfully updated on Shopify!')

    print('============================================================')
    print('UPCOMING SHOW LINEUP (CHRONOLOGICAL):')
    print('============================================================')
    for idx, p in enumerate(sorted_products, start=1):
        d = extract_event_date(p['title'], p.get('variants', []))
        d_str = d.strftime('%b %d, %Y') if d.year < 9000 else 'Utility'
        print(f'  {idx:2d}. [{d_str}] {p["title"]}')
    print('============================================================')

if __name__ == '__main__':
    main()
