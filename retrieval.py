# retrieval.py
# Author: Adwoa | Task: embeddings + retrieval for the Covenant Extractor (IS883)
# Written with help from Claude (Anthropic), per course rule §9.

import time                      # lets us pause between API calls (free-tier limit)
import numpy as np               # fast math on lists of numbers
import streamlit as st           # used here only to read the API key from secrets.toml
from google import genai         # Google's Gemini library
from google.genai import types   # helper classes for building Gemini requests

EMBED_MODEL = "gemini-embedding-2"  # Google's current embedding model (checked Oct 2026)
EMBED_DIM = 768                     # numbers per vector: smaller cache, nearly the same quality
BATCH_SIZE = 20                     # how many texts we send per API call
PAUSE_SECONDS = 2                   # rest between calls so we stay under the rate limit

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

        result = client.models.embed_content(
            model=EMBED_MODEL,
            contents=contents,
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
        )

        # Each result holds .values, the list of 768 numbers for one text.
        for embedding in result.embeddings:
            vectors.append(embedding.values)

        # Pause before the next batch, but skip the pause after the last one.
        if start + BATCH_SIZE < len(texts):
            time.sleep(PAUSE_SECONDS)

    return vectors


if __name__ == "__main__":
    # Quick test: our three toy sentences from Step 1 (costs just 1 API call).
    sentences = [
        "Debt may not exceed 3.75x EBITDA.",
        "The leverage ratio shall not be greater than 3.75 to 1.",
        "Notices shall be sent by certified mail.",
    ]
    vecs = np.array(embed_texts(sentences))
    print("Number of vectors:", len(vecs))       # expect 3
    print("Numbers per vector:", len(vecs[0]))   # expect 768
    # The vectors have length 1, so a plain dot product IS the cosine similarity.
    print("A vs B:", round(float(np.dot(vecs[0], vecs[1])), 3))  # should be high
    print("A vs C:", round(float(np.dot(vecs[0], vecs[2])), 3))  # should be lower