# --- Shazil: definitions dictionary — the model's lookup source for defined terms ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Why: a covenant says "Consolidated Net Total Leverage Ratio" but the real rule sits in
# the definition, which points to other definitions ("Consolidated EBITDA", ...).
# We build a dictionary {term: definition} once per agreement. The model calls
# lookup_definition() as a tool when it needs a term, instead of guessing.

import re


def build_definitions(chunks):
    """From the chunks, collect every definition into a dictionary {term: text}."""
    definitions = {}
    for c in chunks:
        if c["title"].startswith('Definition: "'):
            term = c["title"][len('Definition: "'):-1].strip()
            definitions[term] = c["text"]
    return definitions


def terms_used_in(text, definitions):
    """List the defined terms that appear inside a piece of text (its cross-references).
    Longest terms first, so "Consolidated EBITDA" is found before "EBITDA"."""
    found = []
    for term in sorted(definitions, key=len, reverse=True):
        if term in text and not any(term in longer for longer in found):
            found.append(term)
    return found


def lookup_definition(term, definitions):
    """The tool the model calls. Returns the definition plus the other defined terms it
    uses, so the model can decide whether to look those up too."""
    match = definitions.get(term)
    if match is None:  # forgive small differences in capitals or spacing
        key = re.sub(r"\s+", " ", term).strip().lower()
        for t, text in definitions.items():
            if t.lower() == key:
                term, match = t, text
                break
    if match is None:
        return {"term": term, "found": False, "definition": None, "uses_terms": []}
    uses = [t for t in terms_used_in(match, definitions) if t != term]
    return {"term": term, "found": True, "definition": match, "uses_terms": uses}


# Quick test: "py definitions.py"
if __name__ == "__main__":
    from edgar import html_to_text
    from chunking import chunk_agreement
    text = html_to_text(open("samples/hasbro_2026_revolver.htm", encoding="utf-8").read())
    definitions = build_definitions(chunk_agreement(text))
    print("Defined terms found:", len(definitions))
    result = lookup_definition("Consolidated Net Total Leverage Ratio", definitions)
    print("\nLookup:", result["term"], "| found:", result["found"])
    print(result["definition"][:300])
    print("\nThis definition uses:", result["uses_terms"])
