import os
import json
import requests

def run_github_diagnostic():
    # 1. Grab token from DOJOUR_STATE secret just like the main script does
    state_str = os.environ.get("DOJOUR_STATE", "")
    token = ""
    
    if state_str:
        try:
            state_data = json.loads(state_str)
            for c in state_data.get("cookies", []):
                if c.get("name") == "usertoken":
                    token = c.get("value")
                    break
        except Exception:
            pass
            
    if not token:
        token = os.environ.get("DOJOUR_TOKEN", "")

    if not token:
        print("DIAGNOSTIC FAILED: Could not find usertoken in DOJOUR_STATE secret.")
        return

    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    # 2. Query a specific, known upcoming instance ID (Advice Column)
    INSTANCE_ID = "83455"
    print(f"=== TESTING INSTANCE {INSTANCE_ID} ===")

    # Test Detail Endpoint
    url_detail = f"https://dojour.us/api/event_instances/{INSTANCE_ID}/"
    resp_detail = requests.get(url_detail, headers=headers)
    print(f"\n1. GET {url_detail} -> Status {resp_detail.status_code}")
    if resp_detail.status_code == 200:
        data = resp_detail.json()
        print("   Top-level keys:", list(data.keys()))
        for k in ["start", "start_datetime", "readable_time", "created_at", "title", "name"]:
            if k in data:
                print(f"   {k}: {data[k]}")

    # Test Reserve Report Endpoint
    url_report = f"https://dojour.us/api/event_instances/{INSTANCE_ID}/reserve_report/"
    resp_report = requests.get(url_report, headers=headers)
    print(f"\n2. GET {url_report} -> Status {resp_report.status_code}")
    
    if resp_report.status_code == 200:
        report_data = resp_report.json()
        
        if isinstance(report_data, dict):
            print("   Report Dict Keys:", list(report_data.keys()))
            for k, v in report_data.items():
                if isinstance(v, list):
                    print(f"   Key '{k}' is a list with {len(v)} items.")
                    if v and isinstance(v[0], dict):
                        print(f"     -> First item keys in '{k}': {list(v[0].keys())}")
                        # Print the first 300 characters of a real reservation so we can see the exact schema
                        print(f"     -> First item sample: {json.dumps(v[0])[:300]}")
        elif isinstance(report_data, list):
            print(f"   Report is a direct LIST of {len(report_data)} items.")
            if report_data and isinstance(report_data[0], dict):
                print("   First item keys:", list(report_data[0].keys()))
                print("   First item sample:", json.dumps(report_data[0])[:300])
    else:
        print("   Response text:", resp_report.text[:300])

if __name__ == "__main__":
    run_github_diagnostic()
