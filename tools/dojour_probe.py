"""Read-only look at the Dojour API shape for one event instance (no buyer data printed).
Used to find where a showtime's seat cap lives. GET and OPTIONS only."""
import json, os, sys
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_tickets import get_dojour_token

INST = os.environ.get("INSTANCE_ID", "86822")
token = get_dojour_token()
H = {"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
PII = {"email", "phone", "first_name", "last_name", "name", "full_name", "purchaser", "attendees", "reservations", "orders"}

def scrub(o, depth=0):
    if isinstance(o, dict):
        return {k: ("<redacted>" if k in PII else scrub(v, depth + 1)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(x, depth + 1) for x in o[:5]] + (["...%d more" % (len(o) - 5)] if len(o) > 5 else [])
    if isinstance(o, str) and len(o) > 200:
        return o[:200] + "..."
    return o

def show(method, path):
    url = "https://dojour.us/api/" + path
    try:
        r = requests.request(method, url, headers=H, timeout=20)
    except Exception as e:
        print(f"\n### {method} {path} -> {e}"); return
    print(f"\n### {method} {path} -> {r.status_code} allow={r.headers.get('Allow')}")
    try:
        print(json.dumps(scrub(r.json()), indent=1)[:6000])
    except Exception:
        print(r.text[:300])

for m, p in [("GET", f"event_instances/{INST}/"), ("OPTIONS", f"event_instances/{INST}/"),
             ("OPTIONS", "reservations/"), ("OPTIONS", f"event_instances/{INST}/reservations/"),
             ("OPTIONS", "reserves/"), ("OPTIONS", "options/"), ("OPTIONS", "option_sets/"),
             ("GET", "")]:
    show(m, p)
