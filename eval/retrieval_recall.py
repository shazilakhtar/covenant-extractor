# --- Shazil: retrieval check (Session 9: 'the action, then the answer') ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
# For each covenant row: was the expected covenant text among the chunks sent to Gemini?
# Offline: uses cached vectors only, no API calls.  Usage: py eval/retrieval_recall.py .

import sys, types, csv, re, os
repo = sys.argv[1]; sys.path.insert(0, repo); os.chdir(repo)
# stub heavy modules: no API calls are made
st = types.ModuleType("streamlit"); st.secrets = {}
st.cache_data = st.cache_resource = lambda *a, **k: (lambda f: f)
sys.modules["streamlit"] = st
g = types.ModuleType("google"); gg = types.ModuleType("google.genai")
gg.errors = types.SimpleNamespace(APIError=Exception, ClientError=Exception, ServerError=Exception)
gg.types = types.SimpleNamespace(FunctionDeclaration=lambda **k: None, Tool=lambda **k: None,
    GenerateContentConfig=lambda **k: None, AutomaticFunctionCallingConfig=lambda **k: None,
    Schema=lambda **k: None, Type=types.SimpleNamespace(OBJECT=1, STRING=2), Content=None, Part=None,
    EmbedContentConfig=lambda **k: None)
gg.Client = lambda **k: None; g.genai = gg
sys.modules["google"] = g; sys.modules["google.genai"] = gg
sys.modules["google.genai.errors"] = gg.errors; sys.modules["google.genai.types"] = gg.types
os.environ["GEMINI_API_KEY"] = "offline"
import numpy as np
from chunking import chunk_agreement
from edgar import html_to_text
import pipeline, extractor
hits = n = 0
for r in csv.DictReader(open("eval/test_set.csv", encoding="utf-8")):
    if r["expected_found"].strip().upper() != "Y" or not r["agreement_url"].strip(): continue
    url = r["agreement_url"].strip(); did = pipeline.doc_id(url)
    sample = pipeline.SAMPLES.get(url)
    html = open(sample[0] if sample else f"eval/cache/{did}.htm", encoding="utf-8", errors="ignore").read()
    chunks = chunk_agreement(html_to_text(html))
    idx = [i for i, c in enumerate(chunks) if pipeline.keep_for_retrieval(c)]
    ops = [chunks[i] for i in idx]
    if sample and os.path.exists(sample[1]) and len(np.load(sample[1])) == len(chunks):
        vec = np.load(sample[1])[idx]
    else:
        vec = np.load(f"eval/cache/{did}.kw.npy")
    picked = extractor.gather_chunks(ops, vec)
    lvl = float(r["expected_level"]); 
    forms = [f"{lvl:,.0f}"] if lvl >= 1000 else [f"{lvl:.2f}", f"{lvl:.1f}x" if False else f"{lvl:.2f}"]
    sec = re.search(r"\d{1,2}(\.\d{1,2}(\.\d)?)?", r["expected_section"]).group(0)
    hit = any(any(f in c["text"] for f in forms) and (c["section"].startswith(sec.split('(')[0]) or sec in c["text"]) for c in picked)
    n += 1; hits += hit
    print(f'{r["ticker"]:<6} sec {r["expected_section"]:<9} level {r["expected_level"]:<9} retrieved: {"YES" if hit else "no"}  ({len(picked)} chunks sent of {len(ops)})')
print(f"\nRecall: right covenant text was in what the model saw for {hits}/{n} agreements")
