# --- Shazil: embed the 4 fixed retrieval questions once and save them in the repo ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
# Run once:  py eval/make_question_vectors.py   (uses 4 embedding requests), then commit
# samples/question_vectors.json. After that, neither the app nor the eval embeds these again.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from extractor import RETRIEVAL_QUESTIONS, QUESTION_FILE, question_vector   # noqa: E402

for q in RETRIEVAL_QUESTIONS:
    question_vector(q)
print("Saved", len(RETRIEVAL_QUESTIONS), "question vectors to", QUESTION_FILE)
