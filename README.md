# apify-leads-to-notion

Scrape B2B leads for **any industry** with an Apify leads-finder actor, dedupe them against your existing Notion database (by LinkedIn URL and email), and push only the new ones.

```
scrape.py  ->  leads.csv  ->  import_leads.py  ->  Notion
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in NOTION_TOKEN, NOTION_DATABASE_ID, APIFY_TOKEN
```

Your Notion database needs these properties: `Name` (title), `First Name` (text), `Last Name` (text), `Email` (email), `LinkedIn URL` (url), `Segment` (select), `Status` (select), `Date Added` (date). Share it with your Notion integration (… menu → Connections).

## Usage

```bash
# 1. Scrape. Always set --max-usd: the actor charges per lead (check its Apify pricing page).
python scripts/scrape.py --industry "Financial Services" "Fintech" \
    --titles "Head of Marketing" "CMO" --location "United Kingdom" \
    --max-results 200 --max-usd 1 --out leads.csv

# 2. Preview the dedupe, then import
python scripts/import_leads.py leads.csv --segment "Fintech" --dry-run
python scripts/import_leads.py leads.csv --segment "Fintech"
```

Industry names must match the actor's own taxonomy (an unknown value returns zero matches, not an error). For anything the flags don't cover, pass a raw actor input with `--input my_input.json`. Try the importer on fake data with `examples/sample_leads.csv`.

## Notes

- Scraped CSVs contain personal data. `*.csv` is gitignored; only the fake sample is tracked. Make sure your use complies with GDPR / CAN-SPAM and the actor's terms.
- Dedupe happens after the scrape, so you still pay for leads you already have.
- Not affiliated with Apify or Notion.

## License

MIT
