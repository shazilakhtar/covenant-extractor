# headroom.py
# Author: Norbesida | Task: headroom calculator for the IS883 Covenant Extractor
# Code written with help from Claude (Anthropic, Claude Sonnet 5.5). Disclosed per directives §9.


def calculate_headroom(covenant_kind, limit, numerator, denominator):
    """
    covenant_kind: "maximum" (e.g. leverage) or "minimum" (e.g. interest coverage)
    limit:         the covenant level, e.g. 3.75 for "3.75x"
    numerator:     e.g. debt (leverage) or EBITDA (coverage)
    denominator:   e.g. EBITDA (leverage) or interest expense (coverage)
    Returns a dict. If the input is bad, the dict has only an "error" key.
    """

    # --- Step A: check the inputs; return a clear message instead of crashing ---
    if covenant_kind not in ("maximum", "minimum"):
        return {"error": 'covenant_kind must be "maximum" or "minimum".'}

    # A number must be present and be an int or float (None or text is rejected)
    for name, value in [("limit", limit), ("numerator", numerator),
                        ("denominator", denominator)]:
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"error": f"{name} is missing or is not a number."}

    if denominator <= 0:
        return {"error": "The denominator must be greater than 0 "
                         "(for leverage, EBITDA must be positive)."}
    if limit <= 0:
        return {"error": "The covenant limit must be greater than 0."}

    # --- Step B: the actual ratio, e.g. debt / EBITDA ---
    actual = numerator / denominator

    # --- Step C: headroom, which depends on the covenant kind ---
    if covenant_kind == "maximum":
        # Safe while actual is BELOW the limit
        in_compliance = actual <= limit
        headroom = (limit - actual) / limit
        # EBITDA is the denominator. Breach happens when numerator / EBITDA = limit,
        # so EBITDA at the breach point = numerator / limit.
        ebitda_at_breach = numerator / limit
        cushion = (denominator - ebitda_at_breach) / denominator
    else:
        # Safe while actual is ABOVE the limit
        in_compliance = actual >= limit
        headroom = (actual - limit) / limit
        # EBITDA is the numerator. Breach happens when EBITDA / denominator = limit,
        # so EBITDA at the breach point = limit * denominator.
        ebitda_at_breach = limit * denominator
        # If the numerator is 0 we can't express a percentage cushion
        cushion = (numerator - ebitda_at_breach) / numerator if numerator != 0 else None

    return {
        "actual_ratio": round(actual, 2),
        "limit": limit,
        "in_compliance": in_compliance,
        "headroom_pct": round(headroom * 100, 1),
        "ebitda_cushion_pct": round(cushion * 100, 1) if cushion is not None else None,
    }


def headroom_from_ratio(covenant_kind, limit, actual_ratio):
    """
    Compare a ratio the company REPORTED (e.g. "leverage was 2.4x") with the covenant limit.
    covenant_kind: "maximum" (leverage) or "minimum" (coverage)
    limit:         the covenant level, e.g. 3.75
    actual_ratio:  the ratio reported in the filing, e.g. 2.4
    Returns {"actual_ratio", "limit", "in_compliance", "headroom_pct"},
    or {"error": "..."} if the input is bad.
    """

    # --- Step A: check the inputs ---
    if covenant_kind not in ("maximum", "minimum"):
        return {"error": 'covenant_kind must be "maximum" or "minimum".'}

    for name, value in [("limit", limit), ("actual_ratio", actual_ratio)]:
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return {"error": f"{name} is missing or is not a number."}

    if limit <= 0:
        return {"error": "The covenant limit must be greater than 0."}
    if actual_ratio < 0:
        return {"error": "The reported ratio cannot be negative."}

    # --- Step B: headroom, which depends on the covenant kind ---
    if covenant_kind == "maximum":
        # Safe while actual is BELOW (or equal to) the limit
        in_compliance = actual_ratio <= limit
        headroom = (limit - actual_ratio) / limit
    else:
        # Safe while actual is ABOVE (or equal to) the limit
        in_compliance = actual_ratio >= limit
        headroom = (actual_ratio - limit) / limit

    return {
        "actual_ratio": actual_ratio,
        "limit": limit,
        "in_compliance": in_compliance,
        "headroom_pct": round(headroom * 100, 1),
    }


# --- Tests: compare each printed result with the hand calculations ---
# Run with: py headroom.py
if __name__ == "__main__":
    print("(a) expect 3.0x, 20%, 20%:   ", calculate_headroom("maximum", 3.75, 750, 250))
    print("(b) expect 4.2x, -12%, -12%: ", calculate_headroom("maximum", 3.75, 1050, 250))
    print("(c) expect 5.0x, 66.7%, 40%: ", calculate_headroom("minimum", 3.00, 500, 100))
    print("(d) expect an error message: ", calculate_headroom("maximum", 3.75, 750, 0))

    print()
    print("Tests for headroom_from_ratio:")
    print("(a) expect compliance, 36.0%: ", headroom_from_ratio("maximum", 3.75, 2.4))
    print("(b) expect breach, -12.0%:    ", headroom_from_ratio("maximum", 3.75, 4.2))
    print("(c) expect compliance, 66.7%: ", headroom_from_ratio("minimum", 3.00, 5.0))
    print("(d) expect an error message:  ", headroom_from_ratio("maximum", 3.75, None))