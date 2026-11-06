# disclosed_ratio.py
# Author: Adwoa | Task: find the covenant ratio a company reports in its latest 10-Q / 10-K
# Written with help from Claude (Anthropic), per course rule §9.

import os                                  # to check for / create the saved-filings folder
import re                                  # to tidy text before comparing quotes
import sys                                 # to read the company from the command line
import json                                # to read Gemini's JSON answer
import time                                # to wait before retrying a busy Gemini
import requests                            # to call EDGAR's free submissions API
import numpy as np                         # vectors for the embedding step
import streamlit as st                     # to read the key and model from secrets.toml
from google import genai                   # Google's Gemini library
from google.genai import types, errors     # request settings and error types
from edgar import HEADERS, fetch_document_html, html_to_text   # team EDGAR helpers
from retrieval import embed_texts, retrieve                     # my retrieval code
from prompts import DISCLOSED_RATIO_PROMPT_V1                   # my versioned prompt

FILINGS_DIR = "samples/filings"   # saved copies of filings, so repeat runs skip the SEC
TOP_K = 5                         # how many paragraphs we send to Gemini

# Words that signal a paragraph is about covenant compliance.
# DESIGN CHOICE: this free keyword filter runs BEFORE embeddings. A 10-Q has thousands
# of paragraphs; embedding all of them would use most of the free-tier quota for one
# company. Keeping only paragraphs with these words leaves a few dozen, costs nothing,
# and the paragraph we want almost always contains at least one of them.
KEYWORDS = ["covenant", "leverage ratio", "coverage ratio", "in compliance"]
MAX_PARAGRAPHS = 40               # safety cap on how many paragraphs we embed

# Gemini settings: the same key and model as the rest of the app, from secrets.toml.
GEN_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
gen_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
GEMINI_TRIES = 4                  # retry a busy Gemini up to 4 times
GEMINI_WAIT = 20                  # seconds to wait between tries


def empty_result():
    """The dict shape Norbesida's screen expects, with every field blank.
    We start from this every time so the shape never changes."""
    return {
        "status": "error",        # "found" | "not_disclosed" | "error"
        "ratio_name": None,       # the ratio's name as the filing writes it
        "value": None,            # e.g. 2.4 for "2.4 to 1.00"
        "as_of": None,            # "YYYY-MM-DD", the date the ratio is measured at
        "quote": None,            # copied word for word from the filing
        "quote_found": False,     # our own check: is the quote really in the text?
        "filing_form": None,      # "10-Q" or "10-K"
        "filing_date": None,      # "YYYY-MM-DD"
        "filing_url": None,       # link to the filing on EDGAR
        "tokens_in": 0,           # Gemini tokens sent
        "tokens_out": 0,          # Gemini tokens received
        "error": None,            # the reason, if status is "error"
    }


# ---------- Step 1: find the latest 10-Q or 10-K ----------
def latest_filing(cik):
    """Ask EDGAR for the company's filing list and return the newest 10-Q or 10-K
    as {"form", "date", "url"}, or None if there isn't one."""
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    response = requests.get(url, headers=HEADERS, timeout=30)   # HEADERS carry our contact email
    response.raise_for_status()                                 # stop if EDGAR returned an error
    recent = response.json()["filings"]["recent"]               # parallel lists, newest first

    for i, form in enumerate(recent["form"]):
        if form in ("10-Q", "10-K"):
            accession = recent["accessionNumber"][i].replace("-", "")   # EDGAR URLs drop the dashes
            document = recent["primaryDocument"][i]
            return {
                "form": form,
                "date": recent["filingDate"][i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{document}",
            }
    return None


# ---------- Step 2: download once, then reuse the saved copy ----------
def load_filing_text(cik, filing):
    """Return the filing as plain text. Downloads it the first time and saves it
    in samples/filings/, then reads the saved copy on every later run."""
    os.makedirs(FILINGS_DIR, exist_ok=True)
    path = f"{FILINGS_DIR}/{int(cik)}_{filing['form']}_{filing['date']}.htm"

    if not os.path.exists(path):
        html = fetch_document_html(filing["url"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    with open(path, encoding="utf-8") as f:
        return html_to_text(f.read())


# ---------- Step 3: cheap keyword filter ----------
def keyword_paragraphs(text):
    """Keep only paragraphs that mention a covenant keyword (see KEYWORDS above)."""
    kept = []
    for line in text.splitlines():
        paragraph = line.strip()
        lower = paragraph.lower()
        hits = sum(1 for word in KEYWORDS if word in lower)    # how many keywords it mentions
        # Real sentences only: at least 8 words. This skips tiny fragments AND the hidden
        # XBRL code lines (long strings with almost no spaces). Also skip duplicates.
        if hits > 0 and len(paragraph.split()) >= 8 and paragraph not in kept:
            kept.append(paragraph)

    # If there are too many, keep the ones mentioning the most keywords.
    kept.sort(key=lambda p: sum(1 for word in KEYWORDS if word in p.lower()), reverse=True)
    return kept[:MAX_PARAGRAPHS]


# ---------- Step 4: rank the kept paragraphs with embeddings ----------
def top_paragraphs(paragraphs, covenant_name, k=TOP_K):
    """Embed the paragraphs and the question, and reuse retrieve() to pick the top k."""
    # Shape each paragraph like a chunk, so my retrieve() function can rank it.
    chunks = [{"section": "", "title": "", "text": p} for p in paragraphs]
    # Same document format as in retrieval.py (these paragraphs have no title).
    vectors = np.array(embed_texts([f"title: none | text: {p}" for p in paragraphs]), dtype=np.float32)
    question = f"What was the company's {covenant_name} as of the end of the quarter?"
    return retrieve(question, chunks, vectors, k=k)


# ---------- Step 5: ask Gemini ----------
def ask_gemini(prompt):
    """Send the prompt to Gemini (temperature 0 = most consistent answer, JSON only).
    Retries if Gemini is busy or rate-limited. Returns (answer_text, tokens_in, tokens_out)."""
    for attempt in range(GEMINI_TRIES):
        try:
            response = gen_client.models.generate_content(
                model=GEN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",   # ask for JSON only
                ),
            )
            usage = response.usage_metadata
            return response.text, usage.prompt_token_count or 0, usage.candidates_token_count or 0
        except errors.APIError as e:
            busy = e.code in (429, 500, 503)                  # rate limit or server busy
            if busy and attempt < GEMINI_TRIES - 1:
                print(f"  Gemini busy ({e.code}), waiting {GEMINI_WAIT} seconds...")
                time.sleep(GEMINI_WAIT)
            else:
                raise


# ---------- Step 6: check the answer in code ----------
def tidy(text):
    """Lower-case, unify curly quotes, and squash spaces, so a quote copied by Gemini
    still matches the filing even if spacing or quote marks differ slightly."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def find_disclosed_ratio(cik, covenant_name):
    """Find the covenant ratio the company itself reports in its latest 10-Q / 10-K.
    Returns the dict described in empty_result()."""
    result = empty_result()
    try:
        # Step 1: newest 10-Q / 10-K
        filing = latest_filing(cik)
        if filing is None:
            result["error"] = "No 10-Q or 10-K found on EDGAR for this company."
            return result
        result["filing_form"] = filing["form"]
        result["filing_date"] = filing["date"]
        result["filing_url"] = filing["url"]

        # Steps 2-3: text, then keyword filter
        text = load_filing_text(cik, filing)
        paragraphs = keyword_paragraphs(text)
        if not paragraphs:
            result["status"] = "not_disclosed"   # no covenant language at all
            return result

        # Step 4: top paragraphs by embeddings
        best = top_paragraphs(paragraphs, covenant_name)
        excerpts = "\n\n".join(p["text"] for p in best)

        # Step 5: ask Gemini
        prompt = DISCLOSED_RATIO_PROMPT_V1.format(covenant_name=covenant_name, excerpts=excerpts)
        answer_text, result["tokens_in"], result["tokens_out"] = ask_gemini(prompt)

        # Step 6: check the answer
        try:
            answer = json.loads(answer_text)
        except json.JSONDecodeError:
            result["error"] = f"Gemini's answer was not valid JSON: {answer_text[:200]}"
            return result

        value = answer.get("value")
        if value is None:
            result["status"] = "not_disclosed"   # the filing states no actual ratio
            return result
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            result["error"] = f"Gemini's value is not a number: {value!r}"
            return result

        quote = answer.get("quote") or ""
        result["status"] = "found"
        result["ratio_name"] = answer.get("ratio_name")
        result["value"] = float(value)
        result["as_of"] = answer.get("as_of")
        result["quote"] = quote
        # Our own check: does the quote really appear in the paragraphs we sent?
        result["quote_found"] = bool(quote) and tidy(quote) in tidy(excerpts)
        return result

    except Exception as e:                       # Step 7: never crash, report the reason
        result["error"] = f"{type(e).__name__}: {e}"
        return result


if __name__ == "__main__":
    # Test ONE company at a time. Default: Hasbro.
    # Another company:  python3 disclosed_ratio.py 63276 "Covenant Name Here"
    cik = int(sys.argv[1]) if len(sys.argv) > 1 else 46080
    covenant = sys.argv[2] if len(sys.argv) > 2 else "Consolidated Net Total Leverage Ratio"

    result = find_disclosed_ratio(cik, covenant)
    for key, value in result.items():
        print(f"{key}: {value}")