"""Read-only look at the Dojour API. GET and OPTIONS only, buyer fields redacted.
Prints the reservation POST schema and the venue's own no-email reservations
(Sam's "Shopify Sales" / "Hold" blocks) so automated blocks can copy them exactly."""
import json, os, sys
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_tickets import get_dojour_token

INSTANCES = (os.environ.get("INSTANCE_ID") or "86823,86825").split(",")
token = get_dojour_token()
H = {"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
BASE = "https://dojour.us/api/"


def schema(fields, depth=0):
    for k, v in fields.items():
        if not isinstance(v, dict):
            print("  " * depth + f"{k}: {v}")
            continue
        flags = [v.get("type")] + (["required"] if v.get("required") else []) + (["read_only"] if v.get("read_only") else [])
        extra = {x: v[x] for x in ("choices", "help_text", "default") if x in v}
        print("  " * depth + f"{k}: {' '.join(str(f) for f in flags)} {json.dumps(extra)[:300] if extra else ''}")
        for sub in ("children",):
            if isinstance(v.get(sub), dict):
                schema(v[sub].get("children", v[sub]), depth + 1)


r = requests.options(BASE + "reservations/", headers=H, timeout=20)
print("### reservations/ POST schema", r.status_code)
schema(r.json().get("actions", {}).get("POST", {}))

for inst in INSTANCES:
    r = requests.get(BASE + f"event_instances/{inst}/reserve_report/", headers=H, timeout=30)
    print(f"\n### reserve_report {inst} -> {r.status_code}")
    data = r.json() if r.status_code == 200 else {}
    print("report keys:", list(data.keys()))
    rows = data.get("reservation_set", [])
    print("reservations:", len(rows), "row keys:", list(rows[0].keys()) if rows else None)
    for res in rows:
        email = (res.get("email") or "") or ((res.get("user") or {}).get("email") if isinstance(res.get("user"), dict) else "")
        if not email:
            print("VENUE ROW:", json.dumps(res, indent=1)[:4000])
    sample = next((x for x in rows if x.get("email")), None)
    if sample:
        print("BUYER ROW SHAPE:", json.dumps({k: (type(v).__name__ if k in ("first_name", "last_name", "email", "phone", "user", "name") else v) for k, v in sample.items()}, indent=1)[:3000])
