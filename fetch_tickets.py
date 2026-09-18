import requests

def fetch_shopify_tickets(shop_url, access_token):
    headers = {"X-Shopify-Access-Token": access_token}
    url = f"https://{shop_url}/admin/api/2024-01/orders.json?status=any&limit=250"
    
    resp = requests.get(url, headers=headers).json()
    shopify_rows = []
    
    for order in resp.get("orders", []):
        if order.get("financial_status") != "paid":
            continue
            
        guest = f"{order.get('customer', {}).get('first_name', '')} {order.get('customer', {}).get('last_name', '')}".strip()
        email = order.get("email", "")
        order_num = order.get("name")
        
        for item in order.get("line_items", []):
            title = item.get("name", "")
            # Filter out room deposits, gift cards, tips, and fees
            if any(x in title.lower() for x in ["deposit", "tip", "fee", "gift card"]):
                continue
                
            shopify_rows.append([
                f"shopify_{order_num}",
                item.get("variant_title", ""),
                title,
                guest,
                email,
                item.get("quantity", 1),
                "Website",
                "FALSE",
                ""
            ])
    return shopify_rows
