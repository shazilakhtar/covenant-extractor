# --- Shazil: compare the old and new agreement search for a few tickers ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
# Usage: py eval/list_agreements.py MAT HAS CWST
# Makes only SEC requests (no Gemini). Nothing in the app changes.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgar import (find_company, search_credit_agreements, list_credit_agreements,  # noqa: E402
                   add_titles)
from pipeline import pick_agreement                                                # noqa: E402

for ticker in (sys.argv[1:] or ["MAT", "HAS", "CWST"]):
    company = find_company(ticker)
    if company is None:
        print(f"\n{ticker}: no company found")
        continue
    old = search_credit_agreements(company["cik"])
    new = add_titles(list_credit_agreements(company["cik"]))   # reads each cover page title
    print(f"\n===== {ticker}  {company['name']}")
    print(f"OLD search: {len(old)} results, app would open: "
          + (f"{old[pick_agreement(old)]['date']}  {old[pick_agreement(old)]['description'][:60]}" if old else "nothing"))
    print(f"NEW search: {len(new)} results, app would open: "
          + (f"{new[pick_agreement(new)]['date']}  {new[pick_agreement(new)]['description'][:60]}" if new else "nothing"))
    print("NEW list (newest first):")
    for f in new:
        tag = "amendment" if f["is_amendment"] else "FULL     "
        print(f"   {f['date']}  {tag}  {f['exhibit']:<8} {f['description'][:70]}")
