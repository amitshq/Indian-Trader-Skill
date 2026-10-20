"""Rule-based screener: every pass/fail comes with the number and threshold behind it.

Logic ported from trader-skill's trader-screener (MIT, Jakeschincariol/trader-skill),
adapted into a library. Rules:
    {"name": "...", "rules": [{"metric": "roce", "op": ">=", "value": 15}],
     "rank": [{"metric": "revenue_growth_yoy", "order": "desc", "weight": 2}],
     "missing": "fail" | "skip", "top": 10}
ops: > >= < <= == != between ([low, high]) in / not in (list)
A screen is a filter on reported numbers, not a recommendation.
"""
OPS = (">", ">=", "<", "<=", "==", "!=", "between", "in", "not in")


class ScreenError(Exception):
    pass


def to_number(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s == "" or s.lower() in ("na", "n/a", "none", "null", "-"):
        return None
    t = s.replace(",", "").replace("₹", "").replace("%", "")
    try:
        return float(t)
    except ValueError:
        return s


def check_rules(spec: dict):
    if not isinstance(spec, dict) or not isinstance(spec.get("rules", []), list):
        raise ScreenError('rules must be {"rules": [...]}')
    for i, r in enumerate(spec.get("rules", []), 1):
        if "metric" not in r or "op" not in r or "value" not in r:
            raise ScreenError(f"rule #{i} needs metric, op and value: {r!r}")
        if r["op"] not in OPS:
            raise ScreenError(f"rule #{i}: unknown op {r['op']!r} (use one of {', '.join(OPS)})")
        if r["op"] == "between" and not (isinstance(r["value"], list) and len(r["value"]) == 2):
            raise ScreenError(f"rule #{i}: between needs [low, high]")
        if r["op"] in ("in", "not in") and not isinstance(r["value"], list):
            raise ScreenError(f"rule #{i}: {r['op']} needs a list")
    for i, k in enumerate(spec.get("rank", []), 1):
        if "metric" not in k or k.get("order", "desc") not in ("asc", "desc"):
            raise ScreenError(f"rank #{i} needs a metric and order asc or desc")
    if spec.get("missing", "fail") not in ("fail", "skip"):
        raise ScreenError('missing must be "fail" or "skip"')


def _fmt(v):
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    if isinstance(v, list):
        return "[%s]" % ", ".join(_fmt(x) for x in v)
    return str(v)


def check(company: dict, rule: dict):
    """(passed, reason). passed is None when the metric is missing."""
    m, op, want = rule["metric"], rule["op"], rule["value"]
    have = company.get(m)
    if have is None or have == "":
        return None, f"{m} is missing"
    if op in ("in", "not in"):
        inside = str(have).upper() in [str(x).upper() for x in want]
        ok = inside if op == "in" else not inside
        return ok, f"{m} {_fmt(have)} {'is in' if inside else 'is not in'} {_fmt(want)}"
    if op in ("==", "!=") and not isinstance(have, (int, float)):
        ok = (str(have).upper() == str(want).upper()) == (op == "==")
        return ok, f"{m} {_fmt(have)} {op} {_fmt(want)}"
    if not isinstance(have, (int, float)):
        return False, f"{m} is {have!r}, not a number"
    if op == "between":
        lo, hi = want
        ok = lo <= have <= hi
        return ok, f"{m} {_fmt(have)} {'is within' if ok else 'is outside'} {_fmt(lo)} to {_fmt(hi)}"
    ok = {">": have > want, ">=": have >= want, "<": have < want, "<=": have <= want,
          "==": have == want, "!=": have != want}[op]
    return ok, (f"{m} {_fmt(have)} {op} {_fmt(want)}" if ok
                else f"{m} {_fmt(have)}, needs {op} {_fmt(want)}")


def screen(companies: list, spec: dict) -> list:
    """Every company with pass/fail and reasons; passing ones ranked first."""
    check_rules(spec)
    rules, missing = spec.get("rules", []), spec.get("missing", "fail")
    results = []
    for c in companies:
        fails, passes, gaps = [], [], []
        for r in rules:
            ok, why = check(c, r)
            if ok is None:
                (fails if missing == "fail" else gaps).append(why)
            elif ok:
                passes.append(why)
            else:
                fails.append(why)
        results.append({"ticker": c["ticker"], "name": c.get("name"), "passed": not fails,
                        "fails": fails, "passes": passes, "skipped": gaps, "metrics": c})
    _rank(results, spec.get("rank", []))
    results.sort(key=lambda r: (not r["passed"], -(r.get("score") or 0), len(r["fails"]), r["ticker"]))
    top = spec.get("top")
    if top:
        kept = 0
        for r in results:
            if r["passed"]:
                kept += 1
                r["shown"] = kept <= top
    return results


def _rank(results: list, keys: list):
    winners = [r for r in results if r["passed"]]
    for r in winners:
        r["score"], r["rank_parts"] = 0.0, {}
    if not keys or not winners:
        for r in winners:
            r["score"] = None
        return
    for k in keys:
        m, desc = k["metric"], k.get("order", "desc") == "desc"
        vals = [(r, r["metrics"].get(m)) for r in winners]
        vals = [(r, v) for r, v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not vals:
            continue
        ordered = sorted(v for _, v in vals)
        n = len(ordered)
        for r, v in vals:
            below = sum(1 for x in ordered if x < v)
            equal = sum(1 for x in ordered if x == v)
            pos = (below + (equal - 1) / 2.0) / (n - 1) if n > 1 else 1.0
            r["rank_parts"][m] = round(pos if desc else 1.0 - pos, 3)
    weights = {k["metric"]: float(k.get("weight", 1)) for k in keys}
    for r in winners:
        parts = r["rank_parts"]
        total = sum(weights[m] for m in parts)
        r["score"] = round(sum(parts[m] * weights[m] for m in parts) / total, 3) if total else None
        r["rank_gaps"] = [k["metric"] for k in keys if k["metric"] not in parts]


def add_prices(companies: list, prices: dict):
    """Adds price, pe (eps_ttm > 0) and earnings_yield (%) from a {symbol: price} map."""
    for c in companies:
        p = to_number(prices.get(c["ticker"]))
        if not isinstance(p, (int, float)) or p <= 0:
            continue
        c["price"] = p
        eps = to_number(c.get("eps_ttm"))
        if isinstance(eps, (int, float)):
            c["earnings_yield"] = round(100.0 * eps / p, 2)
            if eps > 0:
                c["pe"] = round(p / eps, 1)
