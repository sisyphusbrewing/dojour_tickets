"""
Sisyphus - add a staff login from a GitHub Action (Nov 5 2026).

The manager page (staff-admin) does this for a signed-in manager. This lets a
Claude session add one without Sam's password: same username format
(<login>@sisyphusbrewing.com), a role, and optionally voice-recorder access
with the email their notes go to.

    LOGIN=lziegahn ROLE=door PASSWORD=sisyphus \
    VOICE_NAME=Lindsey VOICE_EMAIL=lziegahn@gmail.com python staff_login.py

An existing login is left as it is (its password is not changed); the role
and voice settings are still applied.
"""
import os
import sys

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
DOMAIN = "sisyphusbrewing.com"

login = (os.environ.get("LOGIN") or "").strip().lower()
role = (os.environ.get("ROLE") or "door").strip().lower()
password = os.environ.get("PASSWORD") or "sisyphus"
voice_name = (os.environ.get("VOICE_NAME") or "").strip()
voice_email = (os.environ.get("VOICE_EMAIL") or "").strip()
voice_context = (os.environ.get("VOICE_CONTEXT") or "").strip()

if not login or role not in ("door", "staff", "manager"):
    sys.exit("Need LOGIN, and ROLE door/staff/manager (owners are made by Sam only).")
email = login if "@" in login else f"{login}@{DOMAIN}"

users = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers=H, params={"per_page": 1000}, timeout=30)
users.raise_for_status()
user = next((u for u in users.json().get("users", []) if (u.get("email") or "").lower() == email), None)
if user:
    print(f"{email} already exists; leaving its password alone")
else:
    r = requests.post(f"{SUPABASE_URL}/auth/v1/admin/users", headers=H, timeout=30,
                      json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status()
    user = r.json()
    print(f"Made {email}")

requests.post(f"{SUPABASE_URL}/rest/v1/staff_roles", params={"on_conflict": "user_id"}, timeout=30,
              headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
              json={"user_id": user["id"], "role": role}).raise_for_status()
print(f"Role: {role}")

if voice_email:
    requests.post(f"{SUPABASE_URL}/rest/v1/voice_users", params={"on_conflict": "user_id"}, timeout=30,
                  headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
                  json={"user_id": user["id"], "name": voice_name or login, "email": voice_email,
                        "context": voice_context}).raise_for_status()
    print(f"Voice notes on; notes go to {voice_email}")
