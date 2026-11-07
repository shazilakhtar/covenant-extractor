# --- Shazil: pipeline — one agreement in, everything the model needs out ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Design decision: definitions are NOT embedded for retrieval. They reach the model only
# through the lookup_definition tool. Reasons: (1) about 60% of chunks are definitions, so
# skipping them cuts embedding time and free-tier quota by more than half; (2) the model
# must actively choose which definitions it needs, which is the tool's job.

import os
import re

import numpy as np

from chunking import chunk_agreement
from definitions import build_definitions
from edgar import fetch_document_html, html_to_text
from retrieval import embed_chunks

CACHE_DIR = "samples/cache"

# Agreements we keep a saved copy of, so the demo needs no SEC download and no embedding.
SAMPLES = {
    "https://www.sec.gov/Archives/edgar/data/46080/000095015726000171/ex10-1.htm":
        ("samples/hasbro_2026_revolver.htm", "samples/hasbro_2026_revolver.embeddings.npy"),
}

# Keyword filter before embedding. The free tier embeds about 1,000 chunks a day, and an
# agreement has about 150 operative sections; this keeps only sections that can matter for
# financial covenants. Across our 18 test agreements this means ~920 sections to embed, which fits one
# day of the free tier, and every covenant section is kept.
KEYWORDS = re.compile(r"ratio|covenant|EBITDA|leverage|coverage|in compliance", re.I)

# Filing descriptions that mean "a change to an agreement", not the full agreement itself.
NOT_FULL = re.compile(r"\b(AMENDMENT (TO|NO)|INCREASE|JOINDER|WAIVER|SUPPLEMENT|CONSENT)\b", re.I)


def pick_agreement(filings):
    """Default choice: the newest filing that is a full credit agreement, not an amendment.
    (A simple rule for now; the user can pick another one on screen.)"""
    for i, f in enumerate(filings):
        d = f["description"].upper()
        if "CREDIT AGREEMENT" in d and not NOT_FULL.search(d):
            return i
    return 0


def is_definition(chunk):
    return chunk["title"].startswith('Definition: "')


def doc_id(url):
    """A file-safe name for one filing, e.g. '46080_000095015726000171_ex10-1'."""
    parts = url.rstrip("/").split("/")
    return "_".join(parts[-3:]).replace(".htm", "").replace(".", "-")


# Covenant wording. A piece labelled as a definition is still kept if it contains this: in short
# amendments the covenant often sits between quoted terms and gets labelled as a definition.
COVENANT_WORDS = re.compile(r"shall not permit|shall maintain|shall not be less than|to exceed", re.I)


def keep_for_retrieval(chunk):
    """Operative sections that mention covenant words (plus the cover page, for the date)."""
    if is_definition(chunk):
        return bool(COVENANT_WORDS.search(chunk["text"]))
    return chunk["section"] == "front" or bool(KEYWORDS.search(chunk["title"] + " " + chunk["text"]))


def load_document(url, cache_dir=CACHE_DIR):
    """Download (or load the saved copy), chunk, build the definitions dictionary,
    and embed the operative sections (cached on disk after the first time)."""
    sample = SAMPLES.get(url)
    os.makedirs(cache_dir, exist_ok=True)
    html_path = os.path.join(cache_dir, doc_id(url) + ".htm")
    if sample:
        html = open(sample[0], encoding="utf-8").read()
    elif os.path.exists(html_path):            # downloaded before: no new SEC request
        html = open(html_path, encoding="utf-8").read()
    else:
        html = fetch_document_html(url)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
    chunks = chunk_agreement(html_to_text(html))
    definitions = build_definitions(chunks)
    ops_idx = [i for i, c in enumerate(chunks) if keep_for_retrieval(c)]
    ops_chunks = [chunks[i] for i in ops_idx]

    if sample and os.path.exists(sample[1]):
        full = np.load(sample[1])
        if len(full) == len(chunks):            # saved vectors for every chunk: keep ours
            return chunks, ops_chunks, full[ops_idx], definitions

    vectors = embed_chunks(ops_chunks, os.path.join(cache_dir, doc_id(url) + ".kw.npy"))
    return chunks, ops_chunks, vectors, definitions
