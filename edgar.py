# --- Shazil: EDGAR tool — find a company's credit agreements and download the text ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.

import re
import requests
from bs4 import BeautifulSoup

# The SEC requires every request to say who is asking (name + email).
# Put your own BU email here. Requests without it get blocked.
USER_AGENT = "IS883 Covenant Extractor shaxil@bu.edu"
HEADERS = {"User-Agent": USER_AGENT}


def find_company(ticker):
    """Turn a ticker like 'AAPL' into the SEC's company ID (CIK) and name."""
    url = "https://www.sec.gov/files/company_tickers.json"
    data = requests.get(url, headers=HEADERS, timeout=20).json()
    for row in data.values():
        if row["ticker"].upper() == ticker.upper():
            return {"cik": int(row["cik_str"]), "name": row["title"]}
    return None  # ticker not found


def search_credit_agreements(cik, max_results=10):
    """Search EDGAR full-text search for exhibits that mention 'credit agreement'
    filed by this company. Returns a list of candidate documents, newest first."""
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {"q": '"credit agreement"', "ciks": str(cik).zfill(10)}
    data = requests.get(url, params=params, headers=HEADERS, timeout=20).json()

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit["_source"]
        file_type = src.get("file_type", "")
        # Credit agreements are filed as "material contracts": exhibit 10.x
        if not file_type.upper().startswith("EX-10"):
            continue
        accession, filename = hit["_id"].split(":", 1)
        results.append({
            "date": src.get("file_date"),
            "form": src.get("form"),
            "exhibit": file_type,
            "description": src.get("file_description") or "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                   f"{accession.replace('-', '')}/{filename}",
        })
    results.sort(key=lambda r: r["date"] or "", reverse=True)
    return results[:max_results]


LINE_BREAK = "@@BR@@"   # a placeholder that never appears in filings
INLINE_TAGS = ["span", "font", "b", "i", "u", "a", "strong", "em"]
BLOCK_TAGS = ["p", "div", "br", "tr", "td", "li", "table",
              "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(html):
    """Turn filing HTML into plain text. Line breaks go only where the page has a real
    block (paragraph, table row...), so bold or styled words stay inside their sentence."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(INLINE_TAGS):
        tag.insert_after(" ")          # keep words in separate styled pieces apart
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_after(LINE_BREAK)   # mark the real line breaks
    text = soup.get_text()
    text = " ".join(text.split())      # the HTML file's own line breaks are meaningless
    lines = [line.strip() for line in text.split(LINE_BREAK)]
    lines = [re.sub(r"\s+([.,;:)”])", r"\1", line) for line in lines]  # "INC ." -> "INC."
    lines = [re.sub(r"([“(])\s+", r"\1", line) for line in lines]
    return "\n".join(line for line in lines if line)


def fetch_document_html(url):
    """Download one filing as raw HTML."""
    return requests.get(url, headers=HEADERS, timeout=60).text


def fetch_document_text(url):
    """Download one filing and return it as plain text."""
    return html_to_text(fetch_document_html(url))


# Quick test: run "py edgar.py TICKER" in the VS Code terminal, e.g. "py edgar.py HAS".
if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "HAS"
    company = find_company(ticker)
    print("Company:", company)
    if company:
        docs = search_credit_agreements(company["cik"])
        for d in docs:
            print(d["date"], d["exhibit"], d["description"][:60], d["url"])
        if docs:
            text = fetch_document_text(docs[0]["url"])
            print("\nFirst document length:", len(text), "characters")
            print(text[:500])
