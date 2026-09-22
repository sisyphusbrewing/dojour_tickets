import os
import requests

def sync_to_database(tickets: list):
    """
    Upserts tickets to Supabase.
    CRITICAL: Does NOT include 'checked_in', 'checked_in_count', or 'check_in_time'.
    Postgres will insert them on new records, and completely preserve them on existing records.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"  # UPSERT mode
    }

    # Format payload (stripping out check-in state so it can never be overwritten)
    payload = []
    for t in tickets:
        payload.append({
            "unique_id": t[0],
            "show_date": t[1],
            "show_title": t[2],
            "guest_name": t[3],
            "email": t[4],
            "tickets": int(t[5]),
            "source": t[6]
        })

    # Batch upsert in chunks of 500
    chunk_size = 500
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/tickets?on_conflict=unique_id"

    for i in range(0, len(payload), chunk_size):
        chunk = payload[i:i + chunk_size]
        resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
        if resp.status_code not in [200, 201]:
            print(f"Database error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()

    print(f"Successfully synced {len(payload)} tickets to Supabase without touching check-in states.")
