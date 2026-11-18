"""
Sisyphus Comedy - keep the comics' ad results page up to date (Nov 18 2026).

Comics we run ads for sign in at staff.sisyphusbrewing.com/results/ and see
what their ads spent, how many people saw them and how many clicked (Sam,
Nov 17 2026: "We should create a simple platform on the staff page for Colin
(and other comics) to access these metrics"). This job fetches those numbers
and writes them into comic_ad_campaigns.

  Reddit: always. Reddit is reached through our reddit-ads Edge Function
    (it holds the Reddit sign-in). That function wants a key; this job makes
    a one-time key for itself with the service key, uses it, and deletes it.
  Facebook/Instagram: only when the secret META_ADS_TOKEN exists (a Meta
    system-user token that can read the Sisyphus Comedy ad account). Until
    then a daily Claude task fills these in from Adspirer.

Only campaigns that are running, or ended in the last 3 days, are fetched,
so finished shows keep their final numbers and cost nothing to keep.

The repo and its logs are public: this prints counts only, never names.

    SUPABASE_SERVICE_ROLE_KEY=... python comic_ads_refresh.py [--dry-run]
"""
import datetime as dt
import hashlib
import os
import secrets
import sys

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
META_TOKEN = os.environ.get("META_ADS_TOKEN") or ""
GRAPH = "https://graph.facebook.com/v21.0"
KEEP_FETCHING_DAYS = 3


def db_headers():
    return {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def needs_refresh(row, today):
    """A campaign is fetched while it runs and for a few days after it ends
    (platforms keep correcting the last day's numbers for a while)."""
    if row.get("ends_on"):
        ends = dt.date.fromisoformat(row["ends_on"])
        if ends < today - dt.timedelta(days=KEEP_FETCHING_DAYS):
            return False
    if row.get("starts_on"):
        if dt.date.fromisoformat(row["starts_on"]) > today:
            return False
    return True


def hour_utc(t):
    return t.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")


def reddit_report_body(start, now):
    """Lifetime totals per campaign. Without a DATE breakdown, REACH is the
    number of different people, not a sum of days."""
    return {"data": {
        "starts_at": hour_utc(start),
        "ends_at": hour_utc(now + dt.timedelta(hours=1)),
        "breakdowns": ["CAMPAIGN_ID"],
        "fields": ["SPEND", "IMPRESSIONS", "REACH", "CLICKS"],
    }}


def parse_reddit(body):
    """Reddit money is in millionths of a dollar."""
    out = {}
    for m in ((body or {}).get("data") or {}).get("metrics") or []:
        cid = str(m.get("campaign_id") or "")
        if not cid:
            continue
        out[cid] = {
            "spend": round((m.get("spend") or 0) / 1_000_000, 2),
            "impressions": int(m.get("impressions") or 0),
            "reach": int(m.get("reach") or 0),
            "clicks": int(m.get("clicks") or 0),
        }
    return out


def parse_meta(row):
    """One row of Meta's campaign insights. Clicks are LINK clicks (people who
    went to the ticket page), not every tap on the ad (Nov 2026: Meta's
    "clicks" counted 769 where 104 people actually reached the page)."""
    if not row:
        return {"spend": 0, "impressions": 0, "reach": 0, "clicks": 0, "data_through": None}
    return {
        "spend": round(float(row.get("spend") or 0), 2),
        "impressions": int(row.get("impressions") or 0),
        "reach": int(row.get("reach") or 0),
        "clicks": int(row.get("inline_link_clicks") or 0),
        "data_through": row.get("date_stop"),
    }


class RedditBridge:
    """Calls the reddit-ads Edge Function with a key made just for this run."""

    def __init__(self, session=requests):
        self.s = session
        self.key = None

    def __enter__(self):
        self.key = secrets.token_hex(24)
        r = self.s.post(f"{SUPABASE_URL}/rest/v1/reddit_tool_keys", timeout=30,
                        headers={**db_headers(), "Prefer": "return=minimal"},
                        json={"key_hash": hashlib.sha256(self.key.encode()).hexdigest(),
                              "label": "comic_ads_refresh (one run)"})
        r.raise_for_status()
        return self

    def __exit__(self, *exc):
        h = hashlib.sha256(self.key.encode()).hexdigest()
        self.s.delete(f"{SUPABASE_URL}/rest/v1/reddit_tool_keys", params={"key_hash": f"eq.{h}"},
                      headers=db_headers(), timeout=30)
        return False

    def call(self, method, path, body=None):
        r = self.s.post(f"{SUPABASE_URL}/functions/v1/reddit-ads", timeout=60,
                        headers={"x-tool-key": self.key, "Content-Type": "application/json"},
                        json={"method": method, "path": path, "body": body})
        r.raise_for_status()
        out = r.json()
        if out.get("status", 500) >= 300:
            raise RuntimeError(f"Reddit said {out.get('status')}")
        return out.get("body")


def fetch_reddit(rows, now, session=requests):
    found = {}
    by_account = {}
    for row in rows:
        by_account.setdefault(row["account_id"], []).append(row)
    with RedditBridge(session) as bridge:
        for account, items in by_account.items():
            starts = [dt.date.fromisoformat(r["starts_on"]) for r in items if r.get("starts_on")]
            first = min(starts) if starts else (now.date() - dt.timedelta(days=60))
            start = dt.datetime.combine(first - dt.timedelta(days=1), dt.time(), dt.timezone.utc)
            body = bridge.call("POST", f"ad_accounts/{account}/reports", reddit_report_body(start, now))
            got = parse_reddit(body)
            for r in items:
                if r["campaign_id"] in got:
                    found[r["campaign_id"]] = {**got[r["campaign_id"]], "data_through": now.date().isoformat()}
                else:
                    # No line for a campaign = it hasn't spent anything yet.
                    found[r["campaign_id"]] = {"spend": 0, "impressions": 0, "reach": 0, "clicks": 0,
                                               "data_through": now.date().isoformat()}
    return found


def fetch_meta(rows, session=requests):
    found = {}
    for row in rows:
        r = session.get(f"{GRAPH}/{row['campaign_id']}/insights", timeout=30, params={
            "fields": "spend,impressions,reach,inline_link_clicks",
            "date_preset": "maximum",
            "access_token": META_TOKEN,
        })
        r.raise_for_status()
        data = r.json().get("data") or []
        found[row["campaign_id"]] = parse_meta(data[0] if data else None)
    return found


def main(argv):
    dry = "--dry-run" in argv or (os.environ.get("DRY_RUN") or "").lower() == "true"
    if not KEY:
        sys.exit("Need SUPABASE_SERVICE_ROLE_KEY")
    now = dt.datetime.now(dt.timezone.utc)
    r = requests.get(f"{SUPABASE_URL}/rest/v1/comic_ad_campaigns", headers=db_headers(), timeout=30,
                     params={"select": "id,platform,account_id,campaign_id,starts_on,ends_on"})
    r.raise_for_status()
    rows = [x for x in r.json() if needs_refresh(x, now.date())]
    reddit = [x for x in rows if x["platform"] == "reddit"]
    meta = [x for x in rows if x["platform"] == "meta"]
    print(f"{len(rows)} campaigns to refresh: {len(reddit)} Reddit, {len(meta)} Facebook/Instagram")

    found = {}
    failed = 0
    if reddit:
        try:
            found.update({("reddit", k): v for k, v in fetch_reddit(reddit, now).items()})
        except Exception as e:  # keep going so Meta still refreshes
            failed += 1
            print(f"Reddit refresh failed: {type(e).__name__}")
    if meta and META_TOKEN:
        try:
            found.update({("meta", k): v for k, v in fetch_meta(meta).items()})
        except Exception as e:
            failed += 1
            print(f"Facebook/Instagram refresh failed: {type(e).__name__}")
    elif meta:
        print("No META_ADS_TOKEN yet: Facebook/Instagram numbers come from the daily Claude task")

    written = 0
    for row in rows:
        v = found.get((row["platform"], row["campaign_id"]))
        if v is None:
            continue
        if not dry:
            p = requests.patch(f"{SUPABASE_URL}/rest/v1/comic_ad_campaigns", timeout=30,
                               params={"id": f"eq.{row['id']}"},
                               headers={**db_headers(), "Prefer": "return=minimal"},
                               json={**v, "refreshed_at": now.isoformat()})
            p.raise_for_status()
        written += 1
    print(f"{'Would update' if dry else 'Updated'} {written} campaigns")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
