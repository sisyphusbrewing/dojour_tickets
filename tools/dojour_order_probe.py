"""Read-only: find one buyer's Dojour reservation(s) for a show and show what was paid
and what refund options the Dojour API offers. GET and OPTIONS only, nothing is changed.
The repo is public, so emails, phones and card details are redacted from the log.

Env: DOJOUR_STATE, SHOW_QUERY (e.g. "Sam Jay"), BUYER (e.g. "Kisling"), SINCE (YYYY-MM-DD).
"""
import json, os, sys
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch_tickets import get_dojour_token, parse_show_datetime

SHOW = (os.environ.get("SHOW_QUERY") or "").lower()
BUYER = (os.environ.get("BUYER") or "").lower()
SINCE = os.environ.get("SINCE") or ""
BASE = "https://dojour.us/api/"
token = get_dojour_token()
s = requests.Session()
s.cookies.set("usertoken", token, domain="dojour.us")
s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
SECRET = ("email", "phone", "address", "card", "last4", "zip", "postal", "stripe_customer")


def redact(x):
    if isinstance(x, dict):
        return {k: ("<redacted>" if any(w in k.lower() for w in SECRET) else redact(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [redact(v) for v in x]
    return x


instances = {}
for extra in ("", "&upcoming=false", "&past=true"):
    url = BASE + f"event_instances/reserve_reports/?page_size=100{extra}"
    while url:
        r = s.get(url, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        for item in (data.get("results", []) if isinstance(data, dict) else data):
            opt = (item.get("option_set") or [{}])[0].get("title") or ""
            ev = item.get("event") if isinstance(item.get("event"), dict) else {}
            hay = " ".join(str(x) for x in (opt, item.get("title"), item.get("event_title"), ev.get("title"))).lower()
            dt = parse_show_datetime(item.get("start_dt"))
            if SINCE and dt and dt.strftime("%Y-%m-%d") < SINCE:
                continue
            iid = str(item.get("id") or item.get("event_instance_id") or "")
            if iid and SHOW in hay:
                instances[iid] = item.get("start_dt")
        url = data.get("next") if isinstance(data, dict) else None
print("instances:", instances)

hits = []
for iid, start in instances.items():
    r = s.get(BASE + f"event_instances/{iid}/reserve_report/", timeout=30)
    if r.status_code != 200:
        continue
    rep = r.json()
    for res in rep.get("reservation_set", []):
        user = res.get("user") if isinstance(res.get("user"), dict) else {}
        name = f"{res.get('first_name') or user.get('first_name') or ''} {res.get('last_name') or user.get('last_name') or ''}".lower()
        if BUYER in name or BUYER in str(res.get("name") or "").lower() or BUYER in str(res.get("email") or "").lower():
            hits.append((iid, start, res))
    if hits and not any(h[0] == iid for h in hits[:-1]):
        print(f"\nreport keys for {iid}:", list(rep.keys()))
        print("option/ticket types:", json.dumps(redact({k: rep[k] for k in rep if k != "reservation_set"}), indent=1)[:4000])

for iid, start, res in hits:
    print(f"\n### MATCH instance {iid} {start}")
    print(json.dumps(redact(res), indent=1)[:6000])
    rid = res.get("id")
    for path in (f"reservations/{rid}/", f"reservations/{rid}/refund/", f"reservations/{rid}/partial_refund/",
                 f"reservations/{rid}/cancel/", f"orders/{res.get('order') or res.get('order_id') or rid}/",
                 f"orders/{res.get('order') or res.get('order_id') or rid}/refund/"):
        for method in ("OPTIONS", "GET"):
            try:
                r = s.request(method, BASE + path, timeout=20)
            except Exception as e:  # noqa
                print(method, path, "error", e)
                continue
            body = r.text
            try:
                body = json.dumps(redact(r.json()))
            except Exception:  # noqa
                pass
            print(f"{method} {path} -> {r.status_code} allow={r.headers.get('Allow')} {body[:2500]}")
if not hits:
    print("no reservation matched", BUYER)
