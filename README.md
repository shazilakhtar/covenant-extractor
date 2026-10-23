# covenant-extractor

An app that reads a public credit agreement and pulls out its financial covenants, with the section each one comes from.

## Workshop checkpoint
Team name: 1
Members: Adwoa Atuahene, Norbesida Bagabila, Shazil Akhtar

### 0. Logistics
- Attending the Oct 23 workshop: Yes
- Project board: https://github.com/users/shazilakhtar/projects/1
- Streamlit app: https://covenant-extractor-bnqohatptcbnnfrwywhiyo.streamlit.app/

### 1. The project, as it stands today
- **User:** A portfolio monitoring analyst at a direct lender or BDC.
- **Task:** When the fund closes, buys into or amends a loan, the analyst reads the credit agreement and enters its covenant terms into the fund's monitoring system. Our app does the first pass and cites the section behind every number.
- **Input:** A company ticker (or an EDGAR link). Optionally, EBITDA and debt figures from the borrower's compliance certificate.
- **Output:** A table with one row per financial covenant (type, level, step-downs, test frequency, section number and the supporting text), headroom if numbers were entered, "no financial covenant found" for cov-lite deals, and a disclaimer that the output is model-generated and may be wrong.
- **Sources:** SEC EDGAR filings (credit agreements filed as exhibits), through the SEC's free public APIs. Public records; we send a declared User-Agent and stay under the SEC rate limit. Test documents are saved in `samples/`.

### 2. What changed since the proposal
- **What we changed:** We now cut each agreement into chunks by section number (e.g. 7.05) instead of fixed sizes, and each definition gets its own chunk. This way every chunk carries the section number we need for the citation. We also save each test agreement in `samples/`, so we develop offline and don't spend SEC requests or Gemini quota on repeat runs.
- We added a **definitions dictionary** (`definitions.py`), which the model will call as a tool (see feedback below).
- **Proposal feedback, and what we did:**
  1. *Define "the maximum leverage covenant level" precisely.* Done: see the scoring rules in slot 4.
  2. *Give the model a dictionary of cross-referenced definitions it can call.* Done: `definitions.py` builds a dictionary of every defined term in the agreement (247 terms for Hasbro). `lookup_definition()` returns a definition plus the other defined terms it uses, so the model can follow the chain (e.g. Leverage Ratio → Consolidated EBITDA → Measurement Period). This is now a tool the model calls.
  3. *Test on 2–4 agreements first to save free-tier tokens.* We will develop on Hasbro plus 2–3 more agreements, and run the full test set only once the output parses.
  4. *Fix repo access.* Instructor (`elhamod`) and TA (samuelbc@bu.edu) added as collaborators, and the link re-shared on Piazza.
  5. *Have a second member code 5–8 agreements independently.* Adwoa and Norbesida will each code part of a 6-agreement subset without seeing Shazil's answers. We report how often we agree, and use the disagreements to improve the prompt.

### 3. Where the build stands
- **What a user can do on the deployed app today:** Nothing yet. It is a placeholder that loads. The working pieces run from the command line:
  - `py edgar.py HAS`: finds Hasbro on EDGAR, lists its 10 most recent credit agreement filings, and downloads the newest one as text.
  - `py chunking.py`: cuts Hasbro's 2026 revolving credit agreement (448,000 characters) into 407 chunks and finds Section 7.05 Financial Covenants and the leverage ratio definition.
- **Capabilities:**

| Capability | Where it fires | Status |
|---|---|---|
| Tool calling | The model calls (1) an EDGAR search tool to pick the current agreement (not an old version or a small amendment), (2) `lookup_definition` when a covenant uses a defined term, and (3) a headroom calculator when numbers are given | In progress: EDGAR search and the definitions lookup work as plain functions; not yet connected to the model. Headroom not started |
| Retrieval | Chunks are embedded; for each question we pull the covenant section and the definitions it uses into the prompt | In progress: chunking works; embeddings and search not started |
| Structured output | The model returns the covenant table as JSON; our code checks it and shows an error message if it does not parse | Not started |
| Structured prompting | A versioned system prompt: extract only what is in the text, cite the section, say "not found" instead of guessing | Not started |

- **Architecture sketch:**

```
Ticker ──► [Model] ──calls──► EDGAR search tool ──► list of filings
                │                                        │
                │◄──── picks the current agreement ◄─────┘
                ▼
        Download + HTML to text ──► Chunk by section ──► Embed chunks
                                                            │
Question: "financial covenants?" ──► Retrieve top chunks ◄──┘
                                            │
                                            ▼
                      [Model + versioned prompt] ◄──► lookup_definition tool
                                            │            (definitions dictionary)
                                            ▼
                                   JSON covenant table
                                            │
                          parses? ── no ──► error message to user
                                  └─ yes ─► table + citations on screen
                                            │
                    numbers entered? ──► headroom tool (plain Python)
```

### 4. Success metric
- **The number:** % of test agreements where the app gets the maximum leverage covenant level right AND cites the right section number.
- **What "the maximum leverage covenant level" means, exactly:**
  - **Which covenant:** the leverage ratio test in the agreement's financial covenants section. If there is more than one (e.g. total and first lien), we score the total or net total leverage test. If the only one is first lien or senior secured, we score that one.
  - **Which level:** the highest ratio allowed at the first quarter-end test date after the agreement's effective date. For Hasbro (effective Feb 20, 2026) that is Mar 31, 2026, so 3.75x. Later step-downs and temporary step-ups (e.g. after an acquisition) are recorded but not scored.
  - **Springing covenant** (revolver only, tested only above a usage level): scored as the leverage level, plus the usage trigger.
  - **No leverage covenant** (cov-lite): correct only if the app says none was found.
  - **Match rule:** the number matches to two decimals (3.75 = 3.75:1.00) and the section number matches exactly (e.g. 7.05). Checked by a script, not by eye.
- **Second coder:** Adwoa and Norbesida independently code 6 of the agreements. We report the % where their answer matches Shazil's.
- **Test inputs:** 20–25 credit agreements found through EDGAR full-text search, mostly direct-lender deals, including awkward ones: a cov-lite deal, an amended-and-restated agreement, a deal with step-downs, and an unusual format. Shazil writes the expected answers before the app runs on them. We develop on 2–4 of them first and run the full set only once the output parses.

### 5. Proof of concept — two test inputs
- **Input A (ordinary):** Hasbro, Fourth Amended and Restated Revolving Credit Agreement, Feb 20, 2026 ([link](https://www.sec.gov/Archives/edgar/data/46080/000095015726000171/ex10-1.htm)).
  - Expected: Section 7.05. Consolidated Net Total Leverage Ratio no more than 3.75x for quarters ending Mar 31, Jun 30 and Dec 31, and 4.00x for the quarter ending Sep 30. Consolidated Interest Coverage Ratio at least 3.00x.
  - Result: The app cannot extract yet. Our chunking does find Section 7.05 and the leverage ratio definition as separate chunks.
- **Input B (expected to fail):** Same Hasbro agreement, but this time the trap is the seasonal table. Section 7.05(b) allows 3.75x in most quarters and 4.00x for the quarter ending Sep 30.
  - Expected (by our metric): 3.75x, Section 7.05, because the first test date after Feb 20, 2026 is Mar 31, 2026.
  - Why we expect it to fail: the model will likely report 4.00x, the biggest number in the table, as "the maximum level". A springing-covenant deal (revolver-only test) is another hard case; we will add one to the test set.
  - Result: Not run yet.

### 6. The plan to our presentation
- **Adwoa:** embeddings and retrieval (`retrieval.py`), with cached embeddings; check that Section 7.05 comes back in the top results.
- **Norbesida:** Streamlit screen (`app.py`) with the disclaimer, request cap and error messages; headroom calculator tool (`headroom.py`).
- **Shazil:** versioned system prompt; JSON output and parse-failure handling; connecting EDGAR search, `lookup_definition` and headroom as tools the model calls; test set of 20+ agreements with expected answers; evaluation script.
- **Adwoa and Norbesida together:** independently code 6 test agreements (3 each); we report how often they agree with Shazil.
- **Cut first if behind:** the EBITDA definition summary, then step-down schedules. We keep the EDGAR tool and the headroom calculator, since those are the tools the model decides to call.

### 7. What we need from you
Should a springing covenant (revolver only, tested only above a usage threshold) count as a financial covenant in our metric, or be scored separately?
