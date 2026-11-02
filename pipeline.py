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


def load_document(url):
    """Download (or load the saved copy), chunk, build the definitions dictionary,
    and embed the operative sections (cached on disk after the first time)."""
    sample = SAMPLES.get(url)
    if sample:
        html = open(sample[0], encoding="utf-8").read()
    else:
        html = fetch_document_html(url)
    chunks = chunk_agreement(html_to_text(html))
    definitions = build_definitions(chunks)
    ops_idx = [i for i, c in enumerate(chunks) if not is_definition(c)]
    ops_chunks = [chunks[i] for i in ops_idx]

    if sample and os.path.exists(sample[1]):
        full = np.load(sample[1])
        if len(full) == len(chunks):            # saved vectors for every chunk: keep ours
            return chunks, ops_chunks, full[ops_idx], definitions

    os.makedirs(CACHE_DIR, exist_ok=True)
    vectors = embed_chunks(ops_chunks, os.path.join(CACHE_DIR, doc_id(url) + ".npy"))
    return chunks, ops_chunks, vectors, definitions
