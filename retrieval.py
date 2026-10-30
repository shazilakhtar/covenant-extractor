# retrieval.py
# Author: Adwoa | Task: embeddings + retrieval for the Covenant Extractor (IS883)
# Written with help from Claude (Anthropic), per course rule §9.

import os                        # to check whether the cache file already exists
import time                      # lets us pause between API calls (free-tier limit)
import numpy as np               # fast math on lists of numbers
import streamlit as st           # used here only to read the API key from secrets.toml
from google import genai         # Google's Gemini library
from google.genai import types   # helper classes for building Gemini requests
from google.genai import errors  # so we can recognise a "rate limit" error (code 429)

EMBED_MODEL = "gemini-embedding-2"  # Google's current embedding model (checked Oct 2026)
EMBED_DIM = 768                     # numbers per vector: smaller cache, nearly the same quality
BATCH_SIZE = 20                     # how many texts we send per API call
# Free tier: 100 texts per minute, and EACH text counts, even inside a batch.
# 20 texts every 15 seconds = 80 per minute, safely under the limit.
PAUSE_SECONDS = 15
RETRY_WAIT = 60                     # if we still hit the limit, wait a full minute
MAX_TRIES = 5                       # give up after 5 attempts on the same batch

# Connect to Gemini. The key comes from .streamlit/secrets.toml, never from the code.
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def embed_texts(texts):
    """Turn a list of strings into a list of vectors, one vector per string."""
    vectors = []
    # Walk through the texts 20 at a time: 0-19, then 20-39, and so on.
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]

        # Wrap each text in its own Content object so Gemini returns one vector
        # per text. Plain strings would be blended into a single vector.
        contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in batch]

        # Try the call; if Gemini says "too fast" (429), wait and try again.
        for attempt in range(MAX_TRIES):
            try:
                result = client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=contents,
                    config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
                )
                break  # success, so leave the retry loop
            except errors.ClientError as e:
                if e.code == 429 and attempt < MAX_TRIES - 1:
                    print(f"  Rate limit hit, waiting {RETRY_WAIT} seconds...")
                    time.sleep(RETRY_WAIT)
                else:
                    raise  # a different error, or too many tries: stop and show it

        # Each result holds .values, the list of 768 numbers for one text.
        for embedding in result.embeddings:
            vectors.append(embedding.values)

        done = min(start + BATCH_SIZE, len(texts))
        if len(texts) > BATCH_SIZE:
            print(f"  Embedded {done}/{len(texts)}")  # progress, so we know it's moving

        # Pause before the next batch, but skip the pause after the last one.
        if done < len(texts):
            time.sleep(PAUSE_SECONDS)

    return vectors


def embed_chunks(chunks, cache_path):
    """Embed every chunk ONCE and save the vectors to cache_path.
    Next time, load them from the file instead of calling Gemini."""
    # 1. If a saved file exists AND has one vector per chunk, just load it.
    if os.path.exists(cache_path):
        vectors = np.load(cache_path)
        if len(vectors) == len(chunks):
            print(f"Loaded {len(vectors)} vectors from cache: {cache_path}")
            return vectors
        print("Cache doesn't match the chunks (chunking changed?). Re-embedding.")

    # 2. Otherwise, format each chunk the way Google recommends for documents:
    #    "title: <section> <title> | text: <the chunk's text>"
    texts = [f'title: {c["section"]} {c["title"]} | text: {c["text"]}' for c in chunks]

    print(f"Embedding {len(texts)} chunks with Gemini (about 5 minutes on the free tier)...")
    vectors = np.array(embed_texts(texts), dtype=np.float32)  # float32 = half the file size

    # 3. Save to the cache file so we never pay for these again.
    np.save(cache_path, vectors)
    print(f"Saved {len(vectors)} vectors to {cache_path}")
    return vectors


def retrieve(question, chunks, vectors, k=6):
    """Return the k chunks most similar to the question, best first.
    Each returned chunk is a copy of the original with a "score" added."""
    # 1. Embed the question, using Google's recommended format for questions.
    query = f"task: question answering | query: {question}"
    q = np.array(embed_texts([query])[0], dtype=np.float32)

    # 2. Cosine similarity between the question and EVERY chunk at once:
    #    (chunk . question) / (length of chunk * length of question)
    scores = (vectors @ q) / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))

    # 3. Sort chunk positions from highest score to lowest, keep the top k.
    best = np.argsort(scores)[::-1][:k]

    # 4. Return copies of those chunks with their score attached.
    return [{**chunks[i], "score": float(scores[i])} for i in best]


def rank_of(results, match):
    """Position (1 = best) of the first result where match(chunk) is True, or None."""
    for position, chunk in enumerate(results, start=1):
        if match(chunk):
            return position
    return None


if __name__ == "__main__":
    # Test: load Hasbro the same way chunking.py does, then embed (or load from cache).
    from edgar import html_to_text
    from chunking import chunk_agreement

    path = "samples/hasbro_2026_revolver.htm"
    text = html_to_text(open(path, encoding="utf-8").read())
    chunks = chunk_agreement(text)
    vectors = embed_chunks(chunks, "samples/hasbro_2026_revolver.embeddings.npy")

    # What counts as the "right answer" for each test question.
    is_705 = lambda c: c["section"] == "7.05"
    is_ebitda_def = lambda c: c["title"] == 'Definition: "Consolidated EBITDA"'

    tests = [
        ("What are the financial covenants?", is_705, "Section 7.05", 6),
        ("What is the maximum leverage ratio?", is_705, "Section 7.05", 6),
        ("How is Consolidated EBITDA defined?", is_ebitda_def, "EBITDA definition", 3),
    ]

    for question, target, target_name, needed in tests:
        # Rank ALL chunks so we know exactly where the right one landed.
        ranked = retrieve(question, chunks, vectors, k=len(chunks))
        rank = rank_of(ranked, target)

        print(f"\nQ: {question}")
        for position, c in enumerate(ranked[:6], start=1):
            print(f"  {position}. [{c['score']:.3f}] {c['section']} | {c['title'][:60]}")
        verdict = "PASS" if rank is not None and rank <= needed else "FAIL"
        print(f"  -> {target_name} is #{rank} (needs top {needed}): {verdict}")