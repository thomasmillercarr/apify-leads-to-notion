#!/usr/bin/env python3
"""
Dedupe a scraped-leads CSV against your Notion leads
database and import whatever is genuinely new.

Usage:
    python import_leads.py path/to/leads.csv --segment "Fintech"
    python import_leads.py path/to/leads.csv --segment "Fintech" --dry-run

Env vars required (see ../.env.example):
    NOTION_TOKEN
    NOTION_DATABASE_ID

CSV columns expected (header row required):
    first_name,last_name,email,linkedin_url
"""

import argparse
import csv
import os
import sys
import time
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"


def normalize_url(url: str) -> str:
    return (url or "").strip().lower().rstrip("/")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def fetch_existing_keys(token: str, database_id: str) -> tuple[set, set]:
    """Page through the database once and collect every LinkedIn URL and
    email already stored, normalized the same way as new rows."""
    urls, emails = set(), set()
    url = f"{NOTION_API}/databases/{database_id}/query"
    payload = {"page_size": 100}
    headers = notion_headers(token)

    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            li_prop = props.get("LinkedIn URL", {}).get("url")
            if li_prop:
                urls.add(normalize_url(li_prop))

            email_prop = props.get("Email", {}).get("email")
            if email_prop:
                emails.add(normalize_email(email_prop))

        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return urls, emails


def load_csv_rows(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [
            {
                "first_name": (r.get("first_name") or "").strip(),
                "last_name": (r.get("last_name") or "").strip(),
                "email": (r.get("email") or "").strip(),
                "linkedin_url": (r.get("linkedin_url") or "").strip(),
            }
            for r in reader
        ]


def dedupe(rows: list[dict], existing_urls: set, existing_emails: set):
    seen_urls, seen_emails = set(), set()
    new_rows, skipped_existing, skipped_batch_dupe = [], 0, 0

    for r in rows:
        li = normalize_url(r["linkedin_url"])
        em = normalize_email(r["email"])

        if (li and li in existing_urls) or (em and em in existing_emails):
            skipped_existing += 1
            continue
        if (li and li in seen_urls) or (em and em in seen_emails):
            skipped_batch_dupe += 1
            continue

        if li:
            seen_urls.add(li)
        if em:
            seen_emails.add(em)
        new_rows.append(r)

    return new_rows, skipped_existing, skipped_batch_dupe


def build_page_payload(row: dict, database_id: str, segment: str) -> dict:
    name = f"{row['first_name']} {row['last_name']}".strip() or "Unknown"
    properties = {
        "Name": {"title": [{"text": {"content": name}}]},
        "First Name": {"rich_text": [{"text": {"content": row["first_name"]}}]},
        "Last Name": {"rich_text": [{"text": {"content": row["last_name"]}}]},
        "Segment": {"select": {"name": segment}},
        "Status": {"select": {"name": "New"}},
        "Date Added": {"date": {"start": date.today().isoformat()}},
    }
    if row["linkedin_url"]:
        properties["LinkedIn URL"] = {"url": row["linkedin_url"]}
    if row["email"]:
        properties["Email"] = {"email": row["email"]}

    return {"parent": {"database_id": database_id}, "properties": properties}


def create_pages(token: str, database_id: str, rows: list[dict], segment: str):
    headers = notion_headers(token)
    url = f"{NOTION_API}/pages"
    created, failed = 0, []

    for i, row in enumerate(rows, 1):
        payload = build_page_payload(row, database_id, segment)
        for attempt in range(3):
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 1))
                time.sleep(wait)
                continue
            break

        if resp.status_code >= 300:
            failed.append((row, resp.status_code, resp.text[:300]))
        else:
            created += 1

        time.sleep(0.35)  # stay comfortably under Notion's rate limit
        if i % 25 == 0:
            print(f"  ...{i}/{len(rows)} written")

    return created, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to the new leads CSV")
    parser.add_argument(
        "--segment",
        required=True,
        help='Segment tag for this batch, e.g. "Fintech"',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show counts only, write nothing to Notion",
    )
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    database_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not database_id:
        sys.exit("Set NOTION_TOKEN and NOTION_DATABASE_ID (see .env.example).")

    print("Reading existing leads from Notion...")
    existing_urls, existing_emails = fetch_existing_keys(token, database_id)
    print(f"  {len(existing_urls)} LinkedIn URLs, {len(existing_emails)} emails on file")

    rows = load_csv_rows(args.csv_path)
    print(f"New file: {len(rows)} rows")

    new_rows, skipped_existing, skipped_batch = dedupe(rows, existing_urls, existing_emails)
    print(f"Already in Notion (skip): {skipped_existing}")
    print(f"Duplicate within this file (skip): {skipped_batch}")
    print(f"Genuinely new: {len(new_rows)}")

    if args.dry_run:
        print("\n--dry-run set, nothing written. New leads would be:")
        for r in new_rows:
            print(f"  {r['first_name']} {r['last_name']} | {r['email']} | {r['linkedin_url']}")
        return

    if not new_rows:
        print("Nothing to add.")
        return

    print(f"\nWriting {len(new_rows)} new pages to Notion (segment: {args.segment})...")
    created, failed = create_pages(token, database_id, new_rows, args.segment)

    print(f"\nDone. {created} pages created.")
    if failed:
        print(f"{len(failed)} rows failed:")
        for row, status, body in failed:
            print(f"  {row['first_name']} {row['last_name']} -> HTTP {status}: {body}")


if __name__ == "__main__":
    main()
