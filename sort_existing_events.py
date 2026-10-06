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

def run_graphql(token, query, variables=None):
    url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json'
    headers = {
        'X-Shopify-Access-Token': token,
        'Content-Type': 'application/json'
    }
    resp = requests.post(url, headers=headers, json={'query': query, 'variables': variables or {}})
    data = resp.json()
    if 'errors' in data:
        raise Exception(f'GraphQL error: {data["errors"]}')
    return data.get('data', {})

def extract_event_date(title, variants, current_date=None):
    if current_date is None:
        current_date = datetime.now()

    t_lower = title.lower()
    if 'ticket fee' in t_lower or 'facility fee' in t_lower:
        return datetime(9999, 12, 31)

    if 'every thursday' in t_lower or 'open mic' in t_lower:
        return datetime(current_date.year, current_date.month, current_date.day)

    all_texts = list(variants) + [title]
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

def main():
    print('=' * 60)
    print('SISYPHUS BREWING • CHRONOLOGICAL COLLECTION SORTER')
    print('=' * 60)
    token = get_shopify_access_token()
    gid = f'gid://shopify/Collection/{COLLECTION_ID}'

    # 1. Fetch collection details and products via GraphQL
    print(f'Fetching collection {COLLECTION_ID} via GraphQL...')
    query = '''
    query getCollection($id: ID!) {
      collection(id: $id) {
        id
        title
        handle
        sortOrder
        products(first: 250) {
          edges {
            node {
              id
              title
              handle
              variants(first: 20) {
                nodes {
                  id
                  title
                }
              }
            }
          }
        }
      }
    }
    '''
    data = run_graphql(token, query, {'id': gid})
    col = data.get('collection')

    products = []
    if col:
        print(f'✓ Found collection: "{col.get("title")}" (Handle: {col.get("handle")})')
        edges = col.get('products', {}).get('edges', [])
        for e in edges:
            node = e['node']
            v_titles = [v['title'] for v in node.get('variants', {}).get('nodes', [])]
            products.append({
                'id': node['id'],
                'title': node['title'],
                'variants': v_titles
            })
    else:
        print('GraphQL collection lookup returned null, falling back to Admin REST query...')
        rest_url = f'https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/products.json?collection_id={COLLECTION_ID}&limit=250'
        headers = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}
        r = requests.get(rest_url, headers=headers)
        if r.status_code == 200:
            for p in r.json().get('products', []):
                v_titles = [v['title'] for v in p.get('variants', [])]
                products.append({
                    'id': f'gid://shopify/Product/{p["id"]}',
                    'title': p['title'],
                    'variants': v_titles
                })
        else:
            print(f'REST fallback failed ({r.status_code}): {r.text}')

    print(f'Loaded {len(products)} products from collection.')
    if not products:
        print('No products found to sort.')
        return

    # 2. Ensure collection sort order is MANUAL so moves can be applied
    if col and col.get('sortOrder') != 'MANUAL':
        print('Setting collection sort order to MANUAL...')
        update_mut = '''
        mutation setManual($input: CollectionInput!) {
          collectionUpdate(input: $input) {
            collection { id sortOrder }
            userErrors { field message }
          }
        }
        '''
        run_graphql(token, update_mut, {'input': {'id': gid, 'sortOrder': 'MANUAL'}})
        print('Sort order set to MANUAL.')

    # 3. Sort chronologically
    sorted_products = sorted(
        products,
        key=lambda p: (
            extract_event_date(p['title'], p['variants']),
            p['title']
        )
    )

    current_ids = [p['id'] for p in products]
    target_ids = [p['id'] for p in sorted_products]

    # Calculate minimal moves
    moves = []
    working = list(current_ids)
    for i, target_id in enumerate(target_ids):
        current_idx = working.index(target_id)
        if current_idx != i:
            moves.append({
                'id': target_id,
                'newPosition': str(i)
            })
            working.remove(target_id)
            working.insert(i, target_id)

    if not moves:
        print('All events are already in perfect chronological order!')
        return

    print(f'Reordering {len(moves)} event(s) to match calendar order...')
    reorder_mutation = '''
    mutation reorder($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        job { id }
        userErrors { field message }
      }
    }
    '''
    res = run_graphql(token, reorder_mutation, {'id': gid, 'moves': moves})
    errors = res.get('collectionReorderProducts', {}).get('userErrors', [])
    if errors:
        print(f'Reorder error: {errors}')
    else:
        print('Order successfully updated on Shopify!')

    print('=' * 60)
    print('UPCOMING SHOW LINEUP (CHRONOLOGICAL):')
    print('=' * 60)
    for idx, p in enumerate(sorted_products, start=1):
        d = extract_event_date(p['title'], p['variants'])
        d_str = d.strftime('%b %d, %Y') if d.year < 9000 else 'Utility'
        print(f'  {idx:2d}. [{d_str}] {p["title"]}')
    print('=' * 60)

if __name__ == '__main__':
    main()
