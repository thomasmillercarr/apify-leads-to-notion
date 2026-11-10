#!/usr/bin/env python3
"""
Scrape leads for any industry with an Apify "leads finder" actor and save a CSV
ready for import_leads.py.

Examples:
    python scripts/scrape.py --industry "Events Services" "Hospitality" \
        --titles "Executive Assistant" "Events Manager" \
        --location "United Kingdom" --max-results 200 --max-usd 1 --out leads.csv

    python scripts/scrape.py --input my_actor_input.json --out leads.csv   # raw actor input

Env (see .env.example): APIFY_TOKEN, APIFY_ACTOR_ID (default microworlds~leads-finder).
"""
import argparse
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()
API = "https://api.apify.com/v2"
DEFAULT_ACTOR = "microworlds~leads-finder"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--industry", nargs="+", help='Company industries, e.g. "Financial Services" "Fintech"')
    p.add_argument("--titles", nargs="+", help='Job titles, e.g. "Head of Marketing" "CMO"')
    p.add_argument("--location", nargs="+", default=["United States"], help="Contact countries/regions")
    p.add_argument("--max-results", type=int, default=100, help="Hard cap on leads returned")
    p.add_argument("--max-usd", type=float, help="Hard spend cap for the run (strongly recommended)")
    p.add_argument("--any-email", action="store_true", help="Include unverified emails (default: verified only)")
    p.add_argument("--input", help="Path to a raw actor-input JSON (overrides the flags above)")
    p.add_argument("--out", default="leads.csv")
    a = p.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    actor = os.environ.get("APIFY_ACTOR_ID") or DEFAULT_ACTOR
    if not token:
        sys.exit("Set APIFY_TOKEN (see .env.example).")

    if a.input:
        with open(a.input, encoding="utf-8") as f:
            body = json.load(f)
    else:
        if not a.industry and not a.titles:
            sys.exit("Give at least --industry or --titles (or --input).")
        body = {
            "contact_location": a.location,
            "max_result": a.max_results,
            "include_mobile": False,
        }
        if a.industry:
            body["company_industry"] = a.industry
        if a.titles:
            body["contact_job_titles"] = a.titles
        if not a.any_email:
            body["email_status"] = ["verified"]

    params = {"token": token}
    if a.max_usd:
        params["maxTotalChargeUsd"] = a.max_usd
    r = requests.post(f"{API}/acts/{actor}/runs", params=params, json=body, timeout=30)
    r.raise_for_status()
    run_id = r.json()["data"]["id"]
    print(f"Started run {run_id}")

    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        run = requests.get(f"{API}/actor-runs/{run_id}", params={"token": token}, timeout=30).json()["data"]
        print(f"  {run['status']}")
        if run["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break
        time.sleep(10)
    else:
        sys.exit("Timed out waiting for the run.")
    if run["status"] != "SUCCEEDED":
        sys.exit(f"Run ended: {run['status']}")

    resp = requests.get(
        f"{API}/datasets/{run['defaultDatasetId']}/items",
        params={"token": token, "format": "csv"},
        timeout=120,
    )
    resp.raise_for_status()
    with open(a.out, "wb") as f:
        f.write(resp.content)
    print(f"Saved {a.out}. Cost: ${run.get('usageTotalUsd')}")


if __name__ == "__main__":
    main()
