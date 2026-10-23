# --- Shazil: chunking — cut a credit agreement into labelled pieces for retrieval ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Why sections, not fixed sizes: every chunk keeps its section number (e.g. "7.11"),
# so when the model uses a chunk, the app can cite exactly where the rule came from.

import re

MAX_CHARS = 4000   # longer sections get split into pieces about this size
MIN_CHARS = 200    # shorter pieces are dropped (mostly table-of-contents lines)

# A section heading: optional "Section", a number like 7.11 followed by a dot, then the
# title and sometimes the start of the section text on the same line.
HEADING = re.compile(r'^(?:SECTION|Section)?\s*(\d{1,2}\.\d{1,2})\.\s*(.*)$')
# A definition starts a line with a quoted term, e.g.  "Consolidated EBITDA" means ...
DEFINITION = re.compile(r'^[“"]([^”"]{2,80})[”"]')


def clean_text(text):
    """Glue back stray punctuation the HTML left on its own line ('INC' / '.')."""
    lines = text.splitlines()
    out = []
    for line in lines:
        if re.fullmatch(r'\d{1,3}', line.strip()):   # page numbers like "93"
            continue
        if out and re.fullmatch(r'[.,;:)\]]+', line):
            out[-1] += line
        else:
            out.append(line)
    return "\n".join(out)


def is_heading(line):
    """True if the line looks like a section heading, not a number inside a sentence."""
    m = HEADING.match(line)
    if not m:
        return None
    rest = m.group(2).strip()
    title = rest.split(". ")[0][:80]   # title = text up to the first full stop
    # A real heading has no title yet (title on next line) or a capitalised title.
    if title == "" or title[0].isupper() or title[0] == "[":
        return m.group(1), title
    return None


def split_long(section, title, body):
    """Split one long section. Definitions get one chunk per defined term;
    anything else gets cut into pieces of about MAX_CHARS."""
    lines = body.splitlines()
    pieces, current, label = [], [], title

    if sum(1 for l in lines if DEFINITION.match(l)) >= 5:  # this is the definitions section
        for line in lines:
            m = DEFINITION.match(line)
            if m and current:
                pieces.append((label, "\n".join(current)))
                current = []
            if m:
                label = f'Definition: "{m.group(1)}"'
            current.append(line)
    else:
        size = 0
        for line in lines:
            if size + len(line) > MAX_CHARS and current:
                pieces.append((label, "\n".join(current)))
                current, size = [], 0
            current.append(line)
            size += len(line)
    if current:
        pieces.append((label, "\n".join(current)))

    return [{"section": section, "title": t, "text": txt} for t, txt in pieces]


def chunk_agreement(text):
    """Main function: text in, list of chunks out. Each chunk is
    {"section": "7.11", "title": "Financial Covenants", "text": "..."}"""
    text = clean_text(text)
    chunks, section, title, body = [], "front", "Cover and parties", []

    def close():
        joined = "\n".join(body).strip()
        if len(joined) < MIN_CHARS:
            return
        if len(joined) > MAX_CHARS:
            chunks.extend(split_long(section, title, joined))
        else:
            chunks.append({"section": section, "title": title, "text": joined})

    lines = text.splitlines()
    for i, line in enumerate(lines):
        found = is_heading(line)
        if found:
            close()
            section, title = found
            if not title and i + 1 < len(lines):  # title sits on the next line
                title = lines[i + 1].strip()[:120]
            body = [line]
        else:
            body.append(line)
    close()
    return chunks


# Quick test: "py chunking.py". The first run downloads Hasbro's agreement (raw HTML) and saves it
# to samples/, so later runs work offline and don't use up SEC requests.
if __name__ == "__main__":
    import os
    from edgar import fetch_document_html, html_to_text
    path = "samples/hasbro_2026_revolver.htm"
    if not os.path.exists(path):
        url = "https://www.sec.gov/Archives/edgar/data/46080/000095015726000171/ex10-1.htm"
        os.makedirs("samples", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(fetch_document_html(url))
    text = html_to_text(open(path, encoding="utf-8").read())

    chunks = chunk_agreement(text)
    print("Characters:", len(text), "| Chunks:", len(chunks))
    print("Biggest chunk:", max(len(c["text"]) for c in chunks), "characters\n")
    for c in chunks:
        if "financial covenant" in c["title"].lower() or "Leverage Ratio" in c["title"]:
            print(f'--- {c["section"]} | {c["title"]}\n{c["text"][:400]}\n')
