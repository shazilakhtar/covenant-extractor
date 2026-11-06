# disclosed_ratio.py
# Author: Adwoa | Task: find the covenant ratio a company reports in its latest 10-Q / 10-K
# Written with help from Claude (Anthropic), per course rule §9.


def empty_result():
    """The dict shape Norbesida's screen expects, with every field blank.
    We start from this every time so the shape never changes."""
    return {
        "status": "error",        # "found" | "not_disclosed" | "error"
        "ratio_name": None,       # the ratio's name as the filing writes it
        "value": None,            # e.g. 2.4 for "2.4 to 1.00"
        "as_of": None,            # "YYYY-MM-DD", the date the ratio is measured at
        "quote": None,            # copied word for word from the filing
        "quote_found": False,     # our own check: is the quote really in the text?
        "filing_form": None,      # "10-Q" or "10-K"
        "filing_date": None,      # "YYYY-MM-DD"
        "filing_url": None,       # link to the filing on EDGAR
        "tokens_in": 0,           # Gemini tokens sent
        "tokens_out": 0,          # Gemini tokens received
        "error": None,            # the reason, if status is "error"
    }


def find_disclosed_ratio(cik, covenant_name):
    """Find the covenant ratio the company itself reports in its latest 10-Q / 10-K.
    FIRST VERSION: returns the right shape but doesn't search yet."""
    result = empty_result()
    result["error"] = "Not built yet (first version so the screen can connect)."
    return result


if __name__ == "__main__":
    # Test on ONE company: Hasbro.
    print(find_disclosed_ratio(46080, "Consolidated Net Total Leverage Ratio"))