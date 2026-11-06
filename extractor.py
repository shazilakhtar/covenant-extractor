# --- Shazil: Call 2 — Gemini extracts the covenants (retrieval + tool calling + JSON) ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Flow: retrieve the relevant chunks -> send them to Gemini with the versioned prompt ->
#       Gemini may call lookup_definition (our tool) -> Gemini answers in JSON ->
#       our code parses and checks the JSON. If anything fails, we return a clear status.

import json
import re
import time

from google.genai import errors, types

from definitions import lookup_definition
from prompts import EXTRACT_PROMPT, EXTRACT_PROMPT_VERSION
import streamlit as st

from retrieval import client, retrieve

# The model can be switched in Streamlit Secrets (GEMINI_MODEL = "...") without a code change,
# e.g. to a model with a bigger free daily limit.
GEN_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-3.8-flash")
MAX_TOOL_ROUNDS = 5               # stop the model looping on the tool forever
MAX_CHUNKS = 10                   # how many retrieved chunks go into the prompt

# Several questions, because one question does not reliably pull back every covenant.
RETRIEVAL_QUESTIONS = [
    "What are the financial covenants?",
    "What is the maximum leverage ratio the borrower must maintain?",
    "What is the minimum interest coverage or fixed charge coverage ratio?",
    "When does the financial covenant apply, for example only when the revolver is drawn?",
]

# The tool, described to Gemini. The model reads this description to decide when to call it.
LOOKUP_TOOL = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="lookup_definition",
    description="Look up the exact definition of a capitalised defined term in this credit "
                "agreement, e.g. 'Consolidated EBITDA'. Returns the definition text and the "
                "other defined terms it uses.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"term": types.Schema(type=types.Type.STRING,
                                         description="The defined term, exactly as written")},
        required=["term"],
    ),
)])


RETRY_WAITS = [10, 20, 40]        # seconds to wait after a "busy" (503) or "too fast" (429) error


def is_daily_limit(error):
    """True when Google says the free tier's requests-per-DAY limit is used up."""
    return "PerDay" in str(error) or "per day" in str(error).lower()


def call_gemini(contents, config):
    """Call Gemini. If Google says it is busy (503) or we are too fast (429),
    wait and try again, up to 3 more times. Any other error is raised right away."""
    for wait in RETRY_WAITS + [None]:
        try:
            return client.models.generate_content(
                model=GEN_MODEL, contents=contents, config=config)
        except errors.APIError as e:
            if is_daily_limit(e):
                raise    # waiting seconds will not help: the daily quota resets at midnight PT
            if e.code in (429, 503) and wait is not None:
                print(f"  Gemini busy ({e.code}), retrying in {wait} seconds...")
                time.sleep(wait)
            else:
                raise


def gather_chunks(chunks, vectors):
    """Run each retrieval question, merge the results, keep the best MAX_CHUNKS.
    The cover page is always included, so the model can see the effective date."""
    best = {}
    for q in RETRIEVAL_QUESTIONS:
        for c in retrieve(q, chunks, vectors, k=6):
            key = (c["section"], c["title"])
            if key not in best or c["score"] > best[key]["score"]:
                best[key] = c
    picked = sorted(best.values(), key=lambda c: c["score"], reverse=True)[:MAX_CHUNKS]
    cover = next((c for c in chunks if c["section"] == "front"), None)
    if cover and all(c["section"] != "front" for c in picked):
        picked.insert(0, {**cover, "score": None})
    return picked


def build_message(picked):
    parts = []
    for i, c in enumerate(picked, start=1):
        parts.append(f'Excerpt {i} [Section {c["section"]} | {c["title"]}]\n{c["text"]}')
    return "\n\n---\n\n".join(parts)


def parse_json(text):
    """Pull the JSON object out of the model's reply. Returns (data, error)."""
    if not text:
        return None, "The model returned an empty answer."
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        return None, "The model's answer contained no JSON object."
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"The model's JSON could not be read ({e.msg})."
    if not isinstance(data.get("covenants"), list):
        return None, "The JSON has no 'covenants' list."
    return data, None


def normalise(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()


def check_covenants(data, picked):
    """Deterministic checks our code runs on every covenant (no model involved):
    the level is a number, and the quote really appears in the text we sent."""
    sent_text = normalise(" ".join(c["text"] for c in picked))
    for cov in data["covenants"]:
        cov["level_is_number"] = isinstance(cov.get("level"), (int, float))
        quote = normalise(cov.get("supporting_quote"))
        cov["quote_found"] = bool(quote) and quote in sent_text
    return data


def extract_covenants(chunks, vectors, definitions, prompt=None, prompt_version=None):
    """Main function. Returns a dict with "status": "ok", "parse_error" or "api_error".
    prompt / prompt_version let the eval script compare prompt versions; the app uses the default."""
    prompt = prompt or EXTRACT_PROMPT
    prompt_version = prompt_version or EXTRACT_PROMPT_VERSION
    result = {"prompt_version": prompt_version, "model": GEN_MODEL, "requests": 0,
              "tool_calls": [], "tokens_in": 0, "tokens_out": 0}
    try:
        picked = gather_chunks(chunks, vectors)
        result["retrieved"] = [(c["section"], c["title"], c["score"]) for c in picked]

        contents = [types.Content(role="user",
                                  parts=[types.Part.from_text(text=build_message(picked))])]
        config = types.GenerateContentConfig(
            system_instruction=prompt,
            tools=[LOOKUP_TOOL],
            temperature=0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = call_gemini(contents, config)
            result["requests"] += 1
            usage = response.usage_metadata
            result["tokens_in"] += usage.prompt_token_count or 0
            result["tokens_out"] += usage.candidates_token_count or 0

            calls = response.function_calls or []
            if not calls:
                break   # the model gave its final answer
            # The model asked for definitions: run our tool, send the results back.
            contents.append(response.candidates[0].content)
            replies = []
            for call in calls:
                term = call.args.get("term", "")
                answer = lookup_definition(term, definitions)
                result["tool_calls"].append(term)
                replies.append(types.Part.from_function_response(
                    name="lookup_definition", response={"result": answer}))
            contents.append(types.Content(role="user", parts=replies))
        else:
            result.update(status="parse_error",
                          error="The model kept calling the tool and never answered.")
            return result

    except Exception as e:   # network down, bad key, rate limit, model renamed...
        result.update(status="api_error", error=f"Gemini call failed: {e}")
        return result

    result["raw"] = response.text
    data, error = parse_json(response.text)
    if error:
        result.update(status="parse_error", error=error)
        return result
    result.update(status="ok", data=check_covenants(data, picked))
    return result


# Quick test: "py extractor.py" — runs on Hasbro (saved copy, no embedding needed).
if __name__ == "__main__":
    from pipeline import load_document, SAMPLES

    url = next(iter(SAMPLES))
    chunks, ops_chunks, vectors, definitions = load_document(url)
    out = extract_covenants(ops_chunks, vectors, definitions)

    print("Status:", out["status"], "| prompt:", out["prompt_version"], "| model:", out["model"])
    print("Retrieved:", [s for s, _, _ in out.get("retrieved", [])])
    print("Tool calls:", out["tool_calls"])
    print("Tokens in/out:", out["tokens_in"], "/", out["tokens_out"])
    if out["status"] != "ok":
        print("ERROR:", out["error"])
        print("Raw answer:", (out.get("raw") or "")[:500])
    else:
        d = out["data"]
        print("Effective date:", d.get("effective_date"), "| cov-lite:", d.get("covenant_lite"))
        for c in d["covenants"]:
            print(f'- {c.get("section")} | {c.get("name")} | {c.get("kind")} {c.get("level")} '
                  f'| first test {c.get("first_test_date")} | quote found: {c["quote_found"]}')
            if c.get("schedule"):
                print("    schedule:", c["schedule"])
            if not c["quote_found"]:
                print("    QUOTE NOT FOUND IN TEXT:", repr(c.get("supporting_quote")))
        print("\nExpected (hand-coded): 7.05(b) leverage max 3.75 at 2026-03-31; "
              "7.05(a) interest coverage min 3.00")
