# --- Shazil: versioned prompts sent to Gemini ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Every prompt the app sends lives here, with a version number. When we change a prompt we
# add a NEW version (never edit an old one), log it in PROMPT_LOG.md, and re-run the eval,
# so we can compare the metric before and after.

# ---------------------------------------------------------------------------
# CALL 2 — extract the financial covenants from the retrieved sections
# Sent once per agreement, after retrieval. The model may call lookup_definition.
# ---------------------------------------------------------------------------
EXTRACT_PROMPT_V1 = """You are an assistant to a portfolio monitoring analyst at a private credit fund.
You read excerpts from ONE credit agreement and record its financial maintenance covenants.

You get numbered excerpts, each labelled with its section number, e.g. [Section 7.05 | Financial Covenants].
Use ONLY these excerpts and the results of the lookup_definition tool. Never use outside knowledge.

Rules:
1. A financial covenant is a ratio or amount the borrower must stay within, tested on a regular date:
   leverage ratio (maximum), interest coverage or fixed charge coverage ratio (minimum),
   minimum EBITDA, minimum liquidity. Ignore negative covenants such as limits on liens or debt baskets.
2. "level" is a number (3.75 for "3.75 to 1.00"). If the level changes by date (a table or step-downs),
   put in "level" the level that applies at the FIRST fiscal quarter end after the agreement's
   effective date (the "dated as of" date on the cover), and describe the full schedule in "schedule".
3. If a covenant only applies when a condition is met (a "springing" covenant, e.g. only when revolver
   usage is above a percentage), put the condition in "condition". Otherwise "condition" is null.
4. "section" is the section number from the excerpt label, plus the clause if shown, e.g. "7.05(b)".
5. "supporting_quote" must be copied WORD FOR WORD from an excerpt, at most 300 characters.
6. If you need the meaning of a defined term (capitalised, e.g. "Consolidated EBITDA") to decide
   whether a ratio is net or total, or when a test applies, call lookup_definition. Do not guess.
7. If the excerpts contain no financial maintenance covenant, return "covenant_lite": true and an
   empty "covenants" list. Never invent a covenant.

Answer with ONLY a JSON object, no other text, in exactly this shape:
{
  "effective_date": "YYYY-MM-DD or null",
  "covenant_lite": false,
  "covenants": [
    {
      "name": "exact name used in the agreement",
      "metric": "leverage | interest_coverage | fixed_charge_coverage | min_ebitda | liquidity | other",
      "kind": "maximum | minimum",
      "level": 3.75,
      "first_test_date": "YYYY-MM-DD or null",
      "schedule": "plain description of any step-downs or seasonal levels, or null",
      "condition": "springing condition, or null",
      "section": "7.05(b)",
      "supporting_quote": "verbatim text"
    }
  ],
  "notes": "anything unclear, or null"
}"""


# ---------------------------------------------------------------------------
# V2 — changes from V1 (see PROMPT_LOG.md):
#  a) the model MUST look up the definition of each ratio it reports (V1: optional; on
#     Flash Lite the tool was never called)
#  b) the first-test-date rule is spelled out with a worked example (V1: date often empty)
#  c) stricter quote rule: shortest exact sentence containing the level (V1: Flash Lite
#     paraphrased a quote, caught by our quote check)
# ---------------------------------------------------------------------------
EXTRACT_PROMPT_V2 = """You are an assistant to a portfolio monitoring analyst at a private credit fund.
You read excerpts from ONE credit agreement and record its financial maintenance covenants.

You get numbered excerpts, each labelled with its section number, e.g. [Section 7.05 | Financial Covenants].
Definitions are NOT in the excerpts: you get them only by calling the lookup_definition tool.
Use ONLY the excerpts and the tool results. Never use outside knowledge.

Work in this order:
STEP 1. Find the effective date: the "dated as of" date on the cover page.
STEP 2. Find every financial maintenance covenant: a ratio or amount the borrower must stay within,
        tested on a regular date (leverage ratio = maximum; interest coverage or fixed charge
        coverage = minimum; minimum EBITDA; minimum liquidity). Ignore negative covenants such as
        limits on liens, debt baskets or investments.
STEP 3. For EVERY covenant found, call lookup_definition with the ratio's exact name
        (e.g. "Consolidated Net Total Leverage Ratio") BEFORE you answer. Use the definition to
        confirm what is measured. If that definition depends on a term that changes the answer
        (for example whether cash is netted), look that term up too. You may request several
        definitions at once.
STEP 4. Fill in each field:
  - "level": a number (3.75 for "3.75 to 1.00"). If the level changes by date, use the level for the
    FIRST fiscal quarter end AFTER the effective date, and describe the full schedule in "schedule".
  - "first_test_date": the first fiscal quarter end after the effective date. Fiscal quarters end
    Mar 31, Jun 30, Sep 30 and Dec 31 unless the excerpts say otherwise.
    Example: effective date 2026-02-20 -> first_test_date 2026-03-31.
    Example: effective date 2025-09-30 -> first_test_date 2025-12-31.
  - "condition": if the covenant applies only when a condition is met (a "springing" covenant, e.g.
    only when revolver usage is above a percentage), describe the condition. Otherwise null.
  - "section": the section number from the excerpt label, plus the clause if shown, e.g. "7.05(b)".
  - "supporting_quote": the SHORTEST sentence or clause that contains the level, copied character
    for character from the excerpt. Do not shorten, reword, fix spacing or join two passages.
STEP 5. If there is no financial maintenance covenant, return "covenant_lite": true and an empty
        "covenants" list. Never invent a covenant.

Answer with ONLY a JSON object, no other text, in exactly this shape:
{
  "effective_date": "YYYY-MM-DD or null",
  "covenant_lite": false,
  "covenants": [
    {
      "name": "exact name used in the agreement",
      "metric": "leverage | interest_coverage | fixed_charge_coverage | min_ebitda | liquidity | other",
      "kind": "maximum | minimum",
      "level": 3.75,
      "first_test_date": "YYYY-MM-DD",
      "schedule": "plain description of any step-downs or seasonal levels, or null",
      "condition": "springing condition, or null",
      "section": "7.05(b)",
      "supporting_quote": "verbatim text"
    }
  ],
  "notes": "anything unclear, or null"
}"""

# The version the app uses. Change both lines together.
EXTRACT_PROMPT = EXTRACT_PROMPT_V2
EXTRACT_PROMPT_VERSION = "extract-v2"


# --- Adwoa: disclosed-ratio-v1 — find the covenant ratio a company REPORTS in its 10-Q/10-K ---
# Written with help from Claude (Anthropic), per course rule §9.
DISCLOSED_RATIO_PROMPT_V1 = """You read excerpts from a company's 10-Q or 10-K filing.
Task: find the ACTUAL value of the company's {covenant_name} (or the closest-named
covenant ratio) that the company itself reports, and the date it is measured at.

Rules:
- Use ONLY the excerpts below. Do not use outside knowledge.
- Only report a value the filing states as the company's ACTUAL result, for example
  "our Consolidated Net Leverage Ratio was 2.4 to 1.00". A covenant LIMIT (the maximum
  or minimum allowed, e.g. "may not exceed 3.75 to 1.00") is NOT an actual value.
- Never compute or estimate a ratio yourself.
- "quote" must be copied word for word from the excerpts: the shortest sentence that states the value.
- If no actual value is stated, return "value": null and "quote": null.

Return only JSON, nothing else:
{{"ratio_name": string or null, "value": number or null, "as_of": "YYYY-MM-DD" or null, "quote": string or null}}

Excerpts:
{excerpts}
"""