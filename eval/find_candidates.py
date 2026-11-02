# --- Shazil: find candidate test agreements on EDGAR full-text search ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
# Run: py eval/find_candidates.py   -> prints recent credit agreements for each search phrase.

import sys
import requests

sys.path.insert(0, ".")
from edgar import HEADERS

# Each search targets one kind of test case we need.
SEARCHES = {
    "normal leverage covenant":  '"shall not permit the Consolidated Total Leverage Ratio"',
    "net leverage covenant":     '"shall not permit the Consolidated Net Leverage Ratio"',
    "fixed charge coverage":     '"shall not permit the Fixed Charge Coverage Ratio"',
    "step-downs (table by date)": '"Total Net Leverage Ratio" "Fiscal Quarter Ending"',
    "springing (revolver only)": '"Springing Financial Covenant"',
    "first lien leverage":       '"shall not permit the First Lien Net Leverage Ratio"',
}


def search(phrase, start="2023-01-01", end="2026-10-31", limit=8):
    params = {"q": phrase, "dateRange": "custom", "startdt": start, "enddt": end}
    data = requests.get("https://efts.sec.gov/LATEST/search-index",
                        params=params, headers=HEADERS, timeout=30).json()
    seen, rows = set(), []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        if not src.get("file_type", "").upper().startswith("EX-10"):
            continue
        company = (src.get("display_names") or ["?"])[0]
        if company in seen:
            continue
        seen.add(company)
        cik = src["ciks"][0].lstrip("0")
        accession, filename = hit["_id"].split(":", 1)
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"
        rows.append((src.get("file_date"), company, url))
        if len(rows) >= limit:
            break
    return rows


if __name__ == "__main__":
    for label, phrase in SEARCHES.items():
        print(f"\n=== {label}  ({phrase})")
        for date, company, url in search(phrase):
            print(f"{date} | {company[:60]} | {url}")
