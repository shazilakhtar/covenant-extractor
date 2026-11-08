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



def list_credit_agreements(cik, years=6, pages=3, max_results=25):
    """Newer version of search_credit_agreements (not used by the app yet; test first with
    eval/list_agreements.py). Two fixes:
      1. asks EDGAR only for the last `years` years, so old filings do not crowd out new ones
      2. reads up to `pages` pages of results (100 hits each), not just the first page
    Returns the same shape as search_credit_agreements, newest first, plus "is_amendment"."""
    import datetime
    url = "https://efts.sec.gov/LATEST/search-index"
    today = datetime.date.today()
    start = today.replace(year=today.year - years)
    seen, results = set(), []
    for page in range(pages):
        params = {"q": '"credit agreement"', "ciks": str(cik).zfill(10),
                  "dateRange": "custom", "startdt": start.isoformat(), "enddt": today.isoformat(),
                  "from": page * 100}
        data = requests.get(url, params=params, headers=HEADERS, timeout=20).json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit["_source"]
            file_type = src.get("file_type", "")
            if not file_type.upper().startswith("EX-10"):
                continue
            accession, filename = hit["_id"].split(":", 1)
            doc_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                       f"{accession.replace('-', '')}/{filename}")
            if doc_url in seen:
                continue
            seen.add(doc_url)
            description = src.get("file_description") or ""
            results.append({
                "date": src.get("file_date"),
                "form": src.get("form"),
                "exhibit": file_type,
                "description": description,
                "url": doc_url,
                "is_amendment": bool(AMENDMENT_WORDS.search(description)),
            })
        if len(hits) < 100:          # last page reached
            break
    results.sort(key=lambda r: r["date"] or "", reverse=True)
    return results[:max_results]



TITLE_WORDS = re.compile(r"AGREEMENT|AMENDMENT", re.I)
SKIP_LINES = re.compile(r"^(EX-\d|EXHIBIT|EXECUTION (VERSION|COPY)|CONFORMED COPY|\[?[A-Z ]*CUSIP)", re.I)


def title_from_text(text, max_lines=40):
    """The document's own title: the first short line near the top that names an
    agreement or amendment (e.g. "AMENDMENT NO. 1 TO LOAN AND SECURITY AGREEMENT")."""
    for line in text.split("\n")[:max_lines]:
        line = line.strip()
        letters = [ch for ch in line if ch.isalpha()]
        mostly_caps = letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.8
        if (10 <= len(line) <= 160 and mostly_caps and TITLE_WORDS.search(line)
                and not SKIP_LINES.match(line)):
            return line
    return ""


def fetch_title(url, max_bytes=100_000):
    """Read only the start of a filing (the cover page) and return its title."""
    try:
        with requests.get(url, headers=HEADERS, timeout=20, stream=True) as r:
            head = b""
            for part in r.iter_content(16_384):
                head += part
                if len(head) >= max_bytes:
                    break
        return title_from_text(html_to_text(head.decode("utf-8", errors="ignore")))
    except requests.RequestException:
        return ""


def add_titles(filings):
    """For filings whose EDGAR label is only the exhibit number ("EX-10.1"), read the real
    title from the document's cover page. One small SEC request per such filing, no Gemini."""
    for f in filings:
        label = f["description"].strip()
        if not label or label.upper().startswith("EX-"):
            title = fetch_title(f["url"])
            if title:
                f["description"] = title
                f["is_amendment"] = bool(AMENDMENT_WORDS.search(title))
    return filings

# same words as pipeline.NOT_FULL: "AMENDMENT" (but not "AMENDED AND RESTATED") means an amendment
AMENDMENT_WORDS = re.compile(r"\b(AMENDMENT|INCREASE|JOINDER|WAIVER|SUPPLEMENT|CONSENT)\b", re.I)

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
