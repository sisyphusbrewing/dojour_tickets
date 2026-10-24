"""
Sisyphus - every Dojour show ever, one row per showtime, into Supabase show_history.

Run from GitHub: Actions -> "Dojour sales history" -> Run workflow. Safe to re-run;
rows are upserted by Dojour instance id. The full table is also printed as CSV
in the log and attached to the run as dojour_history.csv.
"""
import csv
import os
import sys

import requests

from fetch_tickets import get_dojour_token, extract_tickets_count, dojour_ticket_type, \
    parse_show_datetime, clean_show_title


def dojour_session():
    token = get_dojour_token()
    s = requests.Session()
    s.cookies.set("usertoken", token, domain="dojour.us")
    s.headers.update({"Authorization": f"Token {token}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    return s


def list_instances(s):
    instances = {}
    for extra in ("", "&upcoming=false", "&past=true"):
        url = f"https://dojour.us/api/event_instances/reserve_reports/?page_size=100{extra}"
        while url:
            r = s.get(url, timeout=30)
            if r.status_code != 200:
                print(f"list {url} -> {r.status_code}")
                break
            data = r.json()
            for item in (data.get("results", []) if isinstance(data, dict) else data):
                iid = str(item.get("id") or item.get("event_instance_id") or "")
                if not iid:
                    continue
                ev = item.get("event") if isinstance(item.get("event"), dict) else {}
                opt = (item.get("option_set") or [{}])[0].get("title") or ""
                instances[iid] = {
                    "event_title": ev.get("title") or item.get("event_title") or item.get("title") or opt,
                    "opt": opt,
                    "start": item.get("start_dt"),
                }
            url = data.get("next") if isinstance(data, dict) else None
    return instances


def buyer_email(res):
    user = res.get("user") if isinstance(res.get("user"), dict) else {}
    return (res.get("email") or user.get("email") or "").strip().lower()


def is_hold(res):
    # Same rule as sync_inventory.is_hold: venue holds have no email and "hold" in the name.
    name = " ".join(str(res.get(k) or "") for k in ("first_name", "last_name", "name")).lower()
    return not buyer_email(res) and "hold" in name


def summarize(s, iid, meta):
    r = s.get(f"https://dojour.us/api/event_instances/{iid}/reserve_report/", timeout=30)
    if r.status_code != 200:
        return None
    rep = r.json()
    if not isinstance(rep, dict):
        return None
    row = {"instance_id": iid, "source": "Dojour", "event_title": meta["event_title"],
           "tickets": 0, "vip_tickets": 0, "orders": 0, "buyers": 0, "hold_tickets": 0,
           "revenue": round((rep.get("total_revenue") or 0) / 100, 2)}
    start, emails, title = meta["start"], set(), ""
    for res in rep.get("reservation_set", []):
        if not isinstance(res, dict):
            continue
        start = start or res.get("start_dt")
        title = title or res.get("event_title") or ""
        if res.get("is_cancelled") or res.get("waitlist") or res.get("is_on_waitlist") \
                or res.get("checkout_complete") is False:
            continue
        n = extract_tickets_count(res)
        if is_hold(res):
            row["hold_tickets"] += n
            continue
        row["tickets"] += n
        row["orders"] += 1
        if dojour_ticket_type(res):
            row["vip_tickets"] += n
        if buyer_email(res):
            emails.add(buyer_email(res))
    row["buyers"] = len(emails)
    row["show_title"] = clean_show_title(meta["opt"] or title or meta["event_title"] or "")
    dt = parse_show_datetime(start)
    row["starts_at"] = dt.isoformat() if dt else None
    return row


def upsert(rows):
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("No Supabase credentials; skipping upsert.")
        return
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    endpoint = f"{url.rstrip('/')}/rest/v1/show_history?on_conflict=instance_id"
    for i in range(0, len(rows), 200):
        r = requests.post(endpoint, headers=headers, json=rows[i:i + 200], timeout=30)
        if r.status_code >= 300:
            sys.exit(f"Supabase upsert failed: {r.status_code} {r.text[:300]}")
    print(f"Upserted {len(rows)} rows into show_history.")


def main():
    s = dojour_session()
    instances = list_instances(s)
    print(f"Dojour: {len(instances)} showtimes found.")
    rows = [row for iid, meta in instances.items() if (row := summarize(s, iid, meta))]
    rows.sort(key=lambda r: r["starts_at"] or "")
    upsert(rows)

    cols = ["instance_id", "starts_at", "show_title", "event_title", "tickets", "vip_tickets",
            "orders", "buyers", "hold_tickets", "revenue"]
    with open("dojour_history.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    w = csv.DictWriter(sys.stdout, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            total = sum(r["tickets"] for r in rows)
            f.write(f"## Dojour sales history\n\n{len(rows)} showtimes, {total:,} tickets. "
                    f"Saved to Supabase show_history and attached as dojour_history.csv.\n")


if __name__ == "__main__":
    main()
