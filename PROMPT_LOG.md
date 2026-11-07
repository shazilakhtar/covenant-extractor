# Prompt log

Every prompt the app sends to Gemini, when it is sent, and how it changed.
Prompts live in `prompts.py`. Old versions are never edited, only added to.

## Where prompts are sent

| Stage | When | Prompt | Input | Output |
|---|---|---|---|---|
| Call 2: extract covenants | After retrieval, once per agreement | `EXTRACT_PROMPT_V*` (system instruction) | Up to 10 retrieved sections + the cover page | JSON covenant table. The model may call `lookup_definition` in between (each call is one more request) |

Choosing the agreement is currently a simple rule in code (`pipeline.pick_agreement`), not a model call.

## Versions

### extract-v1 (Oct 30)
- First version. Lists the covenant types, the first-test-date rule, verbatim quotes, and says to call `lookup_definition` "if you need" a defined term.
- Results on Hasbro:
  - gemini-3.8-flash: leverage 3.75 and coverage 3.00 correct, sections correct, both quotes verified. With definitions sent through retrieval: 0 tool calls, 3,605 tokens in. With definitions only via the tool: 2 tool calls, first test date filled, 13,940 tokens in.
  - gemini-3.5-flash-lite: levels and sections correct, but first test date empty, leverage quote not verbatim (caught by the quote check), 0 tool calls, 4,069 tokens in.

### extract-v2 (Nov 1)
- Why: on Flash Lite, v1 never called the tool, left the first test date empty and paraphrased a quote.
- Changes: (a) must look up the definition of every ratio it reports; (b) first-test-date rule with two worked examples; (c) quote must be the shortest exact clause containing the level.
- Results on the 21-row test set (Nov 7, gemini-3.5-flash-lite, 2 runs each):

| | extract-v1 | extract-v2 |
|---|---|---|
| Metric (run 1) | 14/21 = 67% | 14/21 = 67% |
| Same answer on both runs | 90% | 100% |
| Quotes verified word for word | 81% | 100% |
| Gemini requests per agreement | 1.0 | 2.1 |
| Tokens in / out per agreement | 4,494 / 464 | 9,836 / 456 |

- v2 misses: MAT 3.75 (took the first table row; Sep 30 row is 4.00), SGC 4.50 (wrong table row), CVGI 6.50, AMN 4.00 (struck-out redline value), GAN section 1.01(c) (amendment paragraph instead of original section 9.2), MNTK and ONEW no covenant returned (short amendments; definitions not available).
- Files: `eval/results_extract-v1_20261107_1605.csv`, `eval/results_extract-v2_20261107_1600.csv`.

### extract-v3 (Nov 7)
- Why: the v2 misses above.
- Changes: (a) step-by-step table rule: pick the row that covers the first test date, never just the first row; (b) one few-shot worked example, using an invented amendment (not from the test set); (c) amendments: effective date = amendment date, section = the original agreement's section being changed; (d) if `lookup_definition` returns found=false, still report the covenant.
- Caveat: v3 was written after looking at test-set errors, so its score is not an unbiased estimate.
- Results: _to be filled after the test set run._

## disclosed-ratio-v1

**Author:** Adwoa (written with help from Claude, per course rule §9)
**Prompt:** `DISCLOSED_RATIO_PROMPT_V1` in `prompts.py`, used by `find_disclosed_ratio` in `disclosed_ratio.py`.

**What it does:** Given the top 5 covenant-related excerpts from a company's latest 10-Q/10-K, Gemini returns JSON with `ratio_name`, `value`, `as_of`, `quote`. It may only report a ratio the company states as its ACTUAL result, never a covenant limit; it must never compute a ratio; the quote must be word for word; if no actual value is stated it returns `value: null`. Our code then checks the JSON parses, the value is a number, and the quote really appears in the excerpts (`quote_found`).

**Pipeline before the prompt:** EDGAR submissions API → newest 10-Q/10-K (saved in `samples/filings/`) → free keyword filter ("covenant", "leverage ratio", "coverage ratio", "in compliance") keeping each keyword line plus the next 12 lines → embeddings + `retrieve()` top 5 → Gemini (temperature 0, JSON).

**Results (checked by hand against each filing):**

| Company | CIK | Result | Hand check | Tokens in/out |
|---|---|---|---|---|
| Hasbro | 46080 | not_disclosed | "in compliance with all covenants"; only limits (3.75 / 4.00) stated | 2316 / 24 |
| Mattel | 63276 | not_disclosed (tested as "Consolidated Leverage Ratio" and "Total Leverage Ratio") | "in compliance with all covenants"; only limits (3.75 / 4.00) stated | 4799 / 24 |
| Casella | 911177 | found: 2.70 as of 2026-06-30, quote_found True | covenant table: 2.70 actual vs 4.00 requirement | 1667 / 60 |

**What we learned:**
- The first version kept only lines with 8+ words, which dropped Casella's covenant TABLE (short rows), so it wrongly returned not_disclosed. Keeping the 12 lines after each keyword line fixed it.
- For Hasbro and Mattel the excerpts contained covenant LIMITS (3.75, 4.00); the "a limit is not an actual value" rule stopped Gemini from reporting them.
- Hidden XBRL code lines matched keywords; we skip lines with web addresses or 40+ character tokens.
- Note for Shazil: the app picked a 2011 agreement for MAT and found no covenants, but Mattel's current 10-Q describes a Credit Agreement with 2.75 interest coverage and 3.75 / 4.00 leverage covenants.
