"""
Sisyphus - put a settlement on a comic's get-paid page (getpaid/?t=<token>).

Run by the "Payee statement" action: give the payee's name and a JSON object.
It is merged into payees.statement (shows, door, total, ticket-fee pool, the
suggested fee split), which the get-paid page shows above the form. Kept out
of the repo on purpose: settlement numbers aren't for the public Pages site.

    PAYEE="Ali Sultan" STATEMENT='{"pool": 822}' python payee_statement.py
"""
import json
import os
import sys

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
AUTH = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def main():
    name = (os.environ.get("PAYEE") or "").strip()
    patch = json.loads(os.environ.get("STATEMENT") or "{}")
    if not name or not isinstance(patch, dict) or not patch:
        sys.exit("Need PAYEE and a JSON object in STATEMENT.")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/payees", headers=AUTH, timeout=30,
                     params={"select": "id,name,statement", "name": f"ilike.{name}"})
    r.raise_for_status()
    rows = r.json()
    if len(rows) != 1:
        sys.exit(f"Expected one payee named {name!r}, found {len(rows)}.")
    merged = {**(rows[0].get("statement") or {}), **patch}
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/payees", params={"id": f"eq.{rows[0]['id']}"},
                       json={"statement": merged}, headers={**AUTH, "Prefer": "return=minimal"}, timeout=30)
    r.raise_for_status()
    print(f"Updated {rows[0]['name']}: {', '.join(sorted(patch))}")


if __name__ == "__main__":
    main()
