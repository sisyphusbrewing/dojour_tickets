import os
import requests

def fetch_shopify_tickets():
    shop = os.environ.get("SHOPIFY_STORE", "sisyphus-brewing.myshopify.com")
    client_id = os.environ.get("SHOPIFY_CLIENT_ID")
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
    
    if not (client_id and client_secret):
        print("Shopify credentials not found. Skipping Shopify sync.")
        return []

    # 1. Exchange Dev Dashboard credentials for access token
    auth_url = f"https://{shop}/admin/oauth/access_token"
    auth_resp = requests.post(auth_url, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials"
    })
    
    if auth_resp.status_code != 200:
        print(f"Shopify auth error: {auth_resp.text}")
        return []
        
    access_token = auth_resp.json().get("access_token")
    headers = {"X-Shopify-Access-Token": access_token}

    # 2. Fetch paid orders
    orders_url = f"https://{shop}/admin/api/2026-07/orders.json?status=any&limit=250"
    res = requests.get(orders_url, headers=headers).json()

    shopify_rows = []
    for order in res.get("orders", []):
        if order.get("financial_status") != "paid":
            continue

        customer = order.get("customer") or {}
        billing = order.get("billing_address") or {}
        first = customer.get("first_name") or billing.get("first_name", "")
        last = customer.get("last_name") or billing.get("last_name", "")
        guest_name = f"{first} {last}".strip() or billing.get("name", "Website Guest")
        email = order.get("email") or customer.get("email", "")
        order_num = order.get("name", "")

        for item in order.get("line_items", []):
            item_name = item.get("name", "")
            
            # Exclude deposits, tips, gift cards, ticket fees
            if any(term in item_name.lower() for term in ["deposit", "tip", "fee", "gift card"]):
                continue

            # Parse Show Title and Date from line item name
            raw_title = item.get("title") or item_name
            variant = item.get("variant_title") or ""
            
            show_title = raw_title.split(" - ")[0].strip() if " - " in raw_title else raw_title
            show_date = variant if variant else (raw_title.split(" - ")[1].split(" / ")[0].strip() if " - " in raw_title else "")

            shopify_rows.append([
                f"shopify_{order_num}",
                show_date,
                show_title,
                guest_name,
                email,
                str(item.get("quantity", 1)),
                "Website",
                "FALSE",
                ""
            ])
            
    print(f"Fetched {len(shopify_rows)} valid ticket rows from Shopify.")
    return shopify_rows
