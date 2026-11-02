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
- Results: _to be filled after the test set run._
