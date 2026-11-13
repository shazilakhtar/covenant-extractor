# --- Shazil: evaluation script — runs the app on the test set and scores it ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Usage (from the repo folder):
#   py eval/run_eval.py --prompt v2              score prompt v2 on every coded row, 2 runs each
#   py eval/run_eval.py --prompt v1              same with prompt v1 (the before/after)
#   py eval/run_eval.py --prompt v3              prompt v3 (few-shot example; amendments)
#   py eval/run_eval.py --prompt v2 --only 4,5   just rows 4 and 5 (to test the script cheaply)
#   py eval/run_eval.py --prepare                download + embed the agreements only (no Gemini
#                                                extraction), so later runs cost only Gemini calls
#
# The metric (fixed in the workshop checkpoint): an agreement counts as correct when the app
# finds the expected covenant with the right level (to 2 decimals) AND the right section number.
# "No covenant" rows are correct only if the app reports none. Out-of-scope rows (no agreement,
# bad ticker) are correct only if the app says it found no company / no agreement.
# Everything here is decided by code, not by eye.

import argparse
import csv
import datetime
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgar import find_company, search_credit_agreements      # noqa: E402
from pipeline import load_document                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_SET = os.path.join(HERE, "test_set.csv")
CACHE = os.path.join(HERE, "cache")            # downloaded agreements + embeddings, reused


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def base_section(s):
    """'7.05(b)' -> '7.05'; 'Section 6.12(a)' -> '6.12'."""
    m = re.search(r"\d{1,2}\.\d{1,2}", s or "")
    return m.group(0) if m else norm(s)


def words(s):
    return set(re.findall(r"[a-z]+", norm(s))) - {"consolidated", "ratio", "the", "of", "to"}


def pick_covenant(covenants, expected_name):
    """The predicted covenant that best matches the expected one, by shared words in the name
    (e.g. 'Net Total Leverage' vs 'Total Net Leverage'). None if nothing shares a word."""
    target = words(expected_name)
    best, best_overlap = None, 0
    for c in covenants:
        overlap = len(target & words(c.get("name")))
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    return best


def score_row(row, result):
    """Compare one app result with the expected answer. Returns a dict of yes/no checks."""
    expected = row["expected_found"].strip().upper()
    out = {"status": result["status"], "pred_level": "", "pred_section": "", "pred_name": "",
           "level_ok": "", "section_ok": "", "quote_found": "", "correct": False, "note": "",
           "all_predicted": ""}

    if expected == "N/A":                              # out of scope: no company / no agreement
        out["correct"] = result["status"] in ("no_company", "no_agreement")
        return out
    if result["status"] != "ok":
        out["note"] = result.get("error", "")[:120]
        return out

    covenants = result["data"].get("covenants") or []
    # every covenant the app returned, so a miss can be explained later
    out["all_predicted"] = "; ".join(f'{c.get("name")} = {c.get("level")} [{c.get("section")}]'
                                     for c in covenants) or f'none (notes: {result["data"].get("notes")})'
    if expected == "N":                                # no financial covenant expected
        out["correct"] = len(covenants) == 0
        out["note"] = "" if out["correct"] else f"app reported {len(covenants)} covenant(s)"
        return out

    c = pick_covenant(covenants, row["expected_covenant_name"])
    if c is None:
        out["note"] = "expected covenant not found"
        return out
    out["pred_name"] = c.get("name")
    out["pred_level"] = c.get("level")
    out["pred_section"] = c.get("section")
    try:
        out["level_ok"] = abs(float(c.get("level")) - float(row["expected_level"])) < 0.005
    except (TypeError, ValueError):
        out["level_ok"] = False
    out["section_ok"] = base_section(c.get("section")) == base_section(row["expected_section"])
    out["quote_found"] = bool(c.get("quote_found"))
    out["correct"] = bool(out["level_ok"] and out["section_ok"])
    return out


def run_app(row, prompt, prompt_version, prepare_only=False):
    """Run the app's pipeline on one row, the same way the app does."""
    url = row["agreement_url"].strip()
    if not url:                                        # ticker-only row: test the search path
        company = find_company(row["ticker"]) if row["ticker"].strip() else None
        if company is None:
            return {"status": "no_company", "tokens_in": 0, "tokens_out": 0, "requests": 0}
        if not search_credit_agreements(company["cik"]):
            return {"status": "no_agreement", "tokens_in": 0, "tokens_out": 0, "requests": 0}
        return {"status": "skipped", "error": "ticker has agreements but no URL in the test set",
                "tokens_in": 0, "tokens_out": 0, "requests": 0}
    chunks, ops_chunks, vectors, definitions = load_document(url, cache_dir=CACHE)
    if prepare_only:
        return {"status": "prepared", "tokens_in": 0, "tokens_out": 0, "requests": 0}
    from extractor import extract_covenants
    return extract_covenants(ops_chunks, vectors, definitions, prompt, prompt_version)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", choices=["v1", "v2", "v3"], default="v2")
    ap.add_argument("--runs", type=int, default=2, help="runs per agreement (consistency check)")
    ap.add_argument("--only", default="", help="comma-separated row ids, e.g. 4,5")
    ap.add_argument("--prepare", action="store_true", help="download + embed only")
    args = ap.parse_args()

    import prompts
    prompt = {"v1": prompts.EXTRACT_PROMPT_V1, "v2": prompts.EXTRACT_PROMPT_V2,
              "v3": prompts.EXTRACT_PROMPT_V3}[args.prompt]
    version = "extract-" + args.prompt

    rows = list(csv.DictReader(open(TEST_SET, encoding="utf-8")))
    rows = [r for r in rows if r["expected_found"].strip()]          # coded rows only
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        rows = [r for r in rows if r["id"] in wanted]
    print(f"{len(rows)} coded rows, prompt {version}, {args.runs} run(s) each\n")

    os.makedirs(CACHE, exist_ok=True)
    records = []
    for row in rows:
        runs = []
        for k in range(1 if args.prepare else args.runs):
            try:
                t0 = time.time()
                result = run_app(row, prompt, version, prepare_only=args.prepare)
                result["seconds"] = round(time.time() - t0, 1)
            except Exception as e:                       # one bad row must not stop the eval
                result = {"status": "error", "error": str(e), "tokens_in": 0, "tokens_out": 0,
                          "requests": 0}
            if args.prepare:
                print(f'row {row["id"]:>3} {row["ticker"]:<6} {result["status"]} {result.get("error", "")[:80]}')
                break
            err = str(result.get("error", "")).lower().replace(" ", "")
            if "resource_exhausted" in err and "perday" in err:
                print("\nSTOPPED: the free tier's DAILY limit is used up (it resets at midnight Pacific).")
                print("Nothing was scored for this row. Re-run later or with a teammate's key.")
                return
            s = score_row(row, result)
            runs.append(s)
            records.append({"id": row["id"], "ticker": row["ticker"], "case_type": row["case_type"],
                            "run": k + 1, "expected_level": row["expected_level"],
                            "expected_section": row["expected_section"],
                            "tokens_in": result.get("tokens_in", 0),
                            "tokens_out": result.get("tokens_out", 0),
                            "requests": result.get("requests", 0),
                            "tool_calls": len(result.get("tool_calls", []) or []),
                            "seconds": result.get("seconds", ""), **s})
            print(f'row {row["id"]:>3} {row["ticker"]:<6} run {k + 1}: '
                  f'{"CORRECT" if s["correct"] else "wrong  "} '
                  f'level {s["pred_level"]!s:<6} section {s["pred_section"]!s:<8} '
                  f'quote {s["quote_found"]!s:<5} {s["note"]}')
        if len(runs) > 1:
            same = len({(r["pred_level"], base_section(str(r["pred_section"])), r["correct"])
                        for r in runs}) == 1
            for rec in records[-len(runs):]:
                rec["consistent"] = same

    if args.prepare or not records:
        return

    # ---- summary ----
    first = [r for r in records if r["run"] == 1]
    n = len(first)
    acc = sum(r["correct"] for r in first) / n
    with_quote = [r for r in first if r["quote_found"] != ""]
    quote_rate = (sum(bool(r["quote_found"]) for r in with_quote) / len(with_quote)) if with_quote else 0
    multi = [r for r in first if "consistent" in r]
    cons = (sum(r["consistent"] for r in multi) / len(multi)) if multi else None
    calls = [r for r in records if r["requests"]]
    avg_in = sum(r["tokens_in"] for r in calls) / len(calls) if calls else 0
    avg_out = sum(r["tokens_out"] for r in calls) / len(calls) if calls else 0
    avg_req = sum(r["requests"] for r in calls) / len(calls) if calls else 0

    print("\n========== RESULT ==========")
    print(f"Prompt {version} | model from secrets | {n} agreements")
    print(f"METRIC (run 1): {sum(r['correct'] for r in first)}/{n} correct = {acc:.0%}")
    if cons is not None:
        print(f"Same answer on both runs: {cons:.0%}")
    print(f"Quotes verified word for word: {quote_rate:.0%}")
    print(f"Per agreement: {avg_req:.1f} Gemini requests, {avg_in:,.0f} tokens in, {avg_out:,.0f} out")
    secs = sorted(r["seconds"] for r in calls if r.get("seconds") != "")
    if secs:
        print(f"Seconds per agreement (model call, agreement already cached): median {secs[len(secs)//2]:.1f}, max {secs[-1]:.1f}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(HERE, f"results_{version}_{stamp}.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()) + (["consistent"] if "consistent" not in records[0] else []))
        w.writeheader()
        w.writerows(records)
    print(f"Saved every run to {path}")


if __name__ == "__main__":
    main()
