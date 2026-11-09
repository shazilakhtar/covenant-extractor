# --- Shazil: covenant test from the financial statements (SEC XBRL data, no Gemini) ---
# Code written with help from Claude (Anthropic, Claude Opus 5.5). Disclosed per directives §9.
#
# Pulls debt, cash and EBITDA from the company's own 10-Q / 10-K numbers (SEC "company facts"
# API, free, structured), builds last-twelve-months (LTM) EBITDA, and computes leverage.
# Demo scope: built and checked for Hasbro (HAS). Other companies may tag their numbers
# differently; the result then says which number is missing.
# IMPORTANT LIMIT: this is REPORTED EBITDA. A credit agreement's "Consolidated EBITDA"
# usually adds back more items, so the covenant ratio is normally LOWER than this one.
#
# Test:  py financials.py HAS

import datetime
import sys

import requests

from edgar import HEADERS, find_company

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Several possible tags for each number: companies choose different ones. First found wins.
DEBT_TOTAL = ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
              "DebtAndCapitalLeaseObligations", "DebtInstrumentCarryingAmount"]   # incl. current part
DEBT_PARTS = ["LongTermDebtNoncurrent", "LongTermDebtCurrent"]          # if no total tag
SHORT_TERM = ["ShortTermBorrowings", "CommercialPaper"]
CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
OPERATING_INCOME = ["OperatingIncomeLoss"]
INTEREST = ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
      "DepreciationAmortizationAndAccretionNet"]


def get_facts(cik):
    return requests.get(FACTS_URL.format(cik=int(cik)), headers=HEADERS, timeout=30).json()


def _entries(facts, tag):
    """All USD values of one tag from 10-Q / 10-K filings, without duplicates."""
    try:
        rows = facts["facts"]["us-gaap"][tag]["units"]["USD"]
    except KeyError:
        return []
    seen, out = set(), []
    for r in rows:
        if r.get("form") not in ("10-Q", "10-K"):
            continue
        key = (r.get("start"), r["end"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _date(s):
    return datetime.date.fromisoformat(s)


def latest_balance(facts, tags):
    """Latest balance-sheet value (a point in time) across all candidate tags: companies
    retire tags, so the MOST RECENT date wins, not the first tag. Returns (value, date, tag) or None."""
    best = None
    for tag in tags:
        rows = [r for r in _entries(facts, tag) if "start" not in r]
        if rows:
            r = max(rows, key=lambda r: r["end"])
            if best is None or r["end"] > best[1]:
                best = (r["val"], r["end"], tag)
    return best


def debt_at(facts, date):
    """Total debt on one balance-sheet date: non-current + current long-term debt if both are
    reported on that date, otherwise a total-debt tag on that date."""
    def on(tag):
        rows = [r for r in _entries(facts, tag) if "start" not in r and r["end"] == date]
        return rows[0]["val"] if rows else None
    nc, cur = on("LongTermDebtNoncurrent"), on("LongTermDebtCurrent")
    if nc is not None:
        return nc + (cur or 0), "LongTermDebtNoncurrent + LongTermDebtCurrent"
    for tag in DEBT_TOTAL:
        v = on(tag)
        if v is not None:
            return v, tag
    return None


def ltm_flow(facts, tags):
    """Last-twelve-months value of an income/cash-flow item.
    LTM = latest fiscal year + current year-to-date - same year-to-date last year.
    Returns (value, period_end, tag, how) or None."""
    def latest_end(tag):
        rows = [r for r in _entries(facts, tag) if "start" in r]
        return max((r["end"] for r in rows), default="")
    for tag in sorted(tags, key=latest_end, reverse=True):     # most recent tag first
        rows = [r for r in _entries(facts, tag) if "start" in r]
        if not rows:
            continue
        for r in rows:
            r["_days"] = (_date(r["end"]) - _date(r["start"])).days
        end = max(r["end"] for r in rows)
        latest = [r for r in rows if r["end"] == end]
        annual = [r for r in latest if 350 <= r["_days"] <= 380]
        if annual:                                    # latest period is a full year
            return annual[0]["val"], end, tag, "fiscal year"
        ytd = max(latest, key=lambda r: r["_days"])   # longest period ending at `end` = year-to-date
        prior_end = _date(end) - datetime.timedelta(days=365)
        prior = [r for r in rows if abs((_date(r["end"]) - prior_end).days) <= 10
                 and abs(r["_days"] - ytd["_days"]) <= 10]
        years = [r for r in rows if 350 <= r["_days"] <= 380
                 and _date(r["end"]) < _date(ytd["start"]) + datetime.timedelta(days=10)
                 and _date(r["end"]) > _date(ytd["start"]) - datetime.timedelta(days=10)]
        if prior and years:
            val = years[0]["val"] + ytd["val"] - prior[0]["val"]
            return val, end, tag, f"FY to {years[0]['end']} + YTD to {end} - YTD to {prior[0]['end']}"
    return None


def leverage_from_statements(cik):
    """Debt, cash, LTM EBITDA and leverage from the company's own filings."""
    out = {"status": "error", "error": None, "inputs": [], "total_debt": None, "cash": None,
           "ebitda": None, "total_leverage": None, "net_leverage": None, "as_of": None,
           "interest": None, "interest_coverage": None}
    try:
        facts = get_facts(cik)
        op = ltm_flow(facts, OPERATING_INCOME)
        da = ltm_flow(facts, DA)
        if op is None or da is None:
            out["error"] = "Could not build last-twelve-months EBITDA from the company's XBRL data."
            return out
        date = op[1]                                   # every number must be on this date
        d = debt_at(facts, date)
        if d is None:
            out["error"] = f"No debt figure reported on {date}, the end of the latest income period."
            return out
        debt = (d[0], date, d[1])
        short = latest_balance(facts, SHORT_TERM)
        cash = latest_balance(facts, CASH)
        if cash and cash[1] != date:
            out["error"] = f"Latest cash figure is from {cash[1]}, not {date}; numbers would not line up."
            return out
        if da[1] != date:
            out["error"] = f"D&A runs to {da[1]} but operating income to {date}; numbers would not line up."
            return out

        total_debt = debt[0] + (short[0] if short and short[1] == debt[1] else 0)
        ebitda = op[0] + da[0]
        out["inputs"] = [
            {"item": "Debt", "value": debt[0], "as_of": debt[1], "source": debt[2]},
            {"item": "Short-term borrowings", "value": short[0] if short and short[1] == debt[1] else 0,
             "as_of": short[1] if short else "-", "source": short[2] if short else "none reported"},
            {"item": "Cash", "value": cash[0] if cash else 0, "as_of": cash[1] if cash else "-",
             "source": cash[2] if cash else "not found"},
            {"item": "Operating income (LTM)", "value": op[0], "as_of": op[1], "source": f"{op[2]}: {op[3]}"},
            {"item": "Depreciation & amortization (LTM)", "value": da[0], "as_of": da[1],
             "source": f"{da[2]}: {da[3]}"},
        ]
        if ebitda <= 0:
            out["error"] = "LTM EBITDA is zero or negative, so leverage cannot be computed."
            return out
        interest = ltm_flow(facts, INTEREST)
        if interest and interest[1] == date and interest[0] > 0:
            out["interest"] = interest[0]
            out["interest_coverage"] = ebitda / interest[0]
            out["inputs"].append({"item": "Interest expense (LTM)", "value": interest[0], "as_of": interest[1],
                                  "source": f"{interest[2]}: {interest[3]}"})
        out.update(status="ok", total_debt=total_debt, cash=cash[0] if cash else 0, ebitda=ebitda,
                   total_leverage=total_debt / ebitda,
                   net_leverage=(total_debt - (cash[0] if cash else 0)) / ebitda,
                   as_of=debt[1])
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


def list_tags(cik, words=("Debt", "Borrowing", "Cash", "Depreciation", "Amortization", "OperatingIncome", "Interest")):
    """Diagnostic: every tag whose name contains one of `words`, with its latest date and value."""
    facts = get_facts(cik)
    rows = []
    for tag in facts["facts"].get("us-gaap", {}):
        if any(w.lower() in tag.lower() for w in words):
            e = _entries(facts, tag)
            if e:
                r = max(e, key=lambda r: r["end"])
                rows.append((r["end"], tag, r["val"], "period" if "start" in r else "point"))
    for end, tag, val, kind in sorted(rows, reverse=True):
        if end >= "2025-01-01":
            print(f"  {end}  {kind:<6} {val / 1e6:>10,.1f}M  {tag}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "--tags":
        list_tags(find_company(sys.argv[1])["cik"])
        sys.exit()
    ticker = sys.argv[1] if len(sys.argv) > 1 else "HAS"
    company = find_company(ticker)
    r = leverage_from_statements(company["cik"])
    print(company["name"], "|", r["status"], r["error"] or "")
    for i in r["inputs"]:
        print(f'  {i["item"]:<36} {i["value"] / 1e6:>10,.1f}M  as of {i["as_of"]}  [{i["source"]}]')
    if r["status"] == "ok":
        print(f'  LTM EBITDA {r["ebitda"] / 1e6:,.1f}M  |  total leverage {r["total_leverage"]:.2f}x'
              f'  |  net leverage {r["net_leverage"]:.2f}x  (as of {r["as_of"]})')
        if r["interest_coverage"]:
            print(f'  Interest coverage (EBITDA / interest) {r["interest_coverage"]:.2f}x')
        else:
            print("  Interest coverage: interest expense not found for the same period")
