"""Turn reported results into screenable metrics. Indian fiscal year runs Apr-Mar.

Input per company (see fixtures/sample_fundamentals.json):
  {"symbol","name","sector","consolidated": true,
   "quarters": [{"period_end":"2025-12-31","revenue":..,"operating_profit":..,"net_profit":..,"eps":..}],
   "annual":   [{"fy":2025,"revenue":..,"net_profit":..,"eps":..}],      # FY2025 = Apr-2024..Mar-2025
   "ratios":   {"roce":..,"roe":..,"debt_to_equity":..,"promoter_holding":..,"promoter_pledge":..}}
Amounts in INR crore (consistent within a company); eps in INR.
"""
from datetime import date, timedelta

Q_END_MONTHS = {6: 1, 9: 2, 12: 3, 3: 4}  # period-end month -> fiscal quarter number


def fiscal_label(period_end: str) -> str:
    d = date.fromisoformat(period_end)
    q = Q_END_MONTHS.get(d.month)
    if q is None:
        raise ValueError(f"{period_end} is not a quarter end (Mar/Jun/Sep/Dec)")
    fy = d.year + 1 if d.month > 3 else d.year
    return f"Q{q} FY{str(fy)[2:]}"


def _fy_of(d: date) -> int:
    return d.year + 1 if d.month > 3 else d.year


def with_derived_q4(quarters: list, annual: list) -> list:
    """Add Q4 = annual - (Q1+Q2+Q3) when Q4 is not reported. Derived rows are flagged."""
    out = list(quarters)
    have = {q["period_end"] for q in out}
    for a in annual:
        fy = a["fy"]
        q4_end = f"{fy}-03-31"
        if q4_end in have:
            continue
        q123 = [q for q in out if _fy_of(date.fromisoformat(q["period_end"])) == fy
                and date.fromisoformat(q["period_end"]).month in (6, 9, 12)]
        if len(q123) != 3:
            continue
        row = {"period_end": q4_end, "derived": True}
        for k in ("revenue", "operating_profit", "net_profit", "eps"):
            if a.get(k) is not None and all(q.get(k) is not None for q in q123):
                row[k] = round(a[k] - sum(q[k] for q in q123), 4)
        out.append(row)
    return sorted(out, key=lambda q: q["period_end"])


def _consecutive(qs: list) -> bool:
    """True when the quarters are back to back (3 months apart), so a TTM sum is valid."""
    idx = [date.fromisoformat(q["period_end"]) for q in qs]
    months = [d.year * 12 + d.month for d in idx]
    return all(b - a == 3 for a, b in zip(months, months[1:]))


def _growth(new, old):
    if new is None or old is None or old <= 0:
        return None
    return round((new - old) / old * 100, 2)


def _margin(num, rev):
    if num is None or not rev:
        return None
    return round(num / rev * 100, 2)


def next_results_due(latest_period_end: date) -> date:
    """Filing deadline of the quarter after `latest_period_end`: 45 days after its end
    (60 days for the Mar quarter, which includes audited annual results) per SEBI LODR."""
    months = latest_period_end.year * 12 + latest_period_end.month - 1 + 3
    y, mo = divmod(months, 12)
    mo += 1
    end = date(y, mo, 31 if mo in (3, 12) else 30)  # quarter ends are Mar 31, Jun 30, Sep 30, Dec 31
    return end + timedelta(days=60 if mo == 3 else 45)


def quality_check(company: dict, today: date = None) -> dict:
    """Drop quarters whose figures are identical to another quarter's (a known data-feed bug:
    a stale row repeated under a new date) and record warnings. Returns a new company dict."""
    qs, warnings, seen = [], list(company.get("warnings", [])), {}
    for q in company.get("quarters", []):
        sig = (q.get("revenue"), q.get("net_profit"), q.get("eps"))
        if None not in sig:
            seen.setdefault(sig, []).append(q["period_end"])
    dupes = {p for periods in seen.values() if len(periods) > 1 for p in periods}
    for q in company.get("quarters", []):
        if q["period_end"] in dupes:
            continue
        qs.append(q)
    if dupes:
        warnings.append("identical figures under different quarters, dropped: " + ", ".join(sorted(dupes)))
    return {**company, "quarters": qs, "warnings": warnings}


def metrics_for(company: dict, today: date = None) -> dict:
    """Flat metrics dict ready for core.screener. Missing inputs stay None (never guessed).
    Adds data_warnings and results_overdue (1 when the latest quarter is older than the filing deadline)."""
    company = quality_check(company)
    today = today or date.today()
    qs = with_derived_q4(company.get("quarters", []), company.get("annual", []))
    m = {"ticker": company["symbol"].upper(), "name": company.get("name"),
         "sector": company.get("sector"), "consolidated": company.get("consolidated")}
    if qs:
        latest = qs[-1]
        d = date.fromisoformat(latest["period_end"])
        yago = next((q for q in qs if q["period_end"] == f"{d.year - 1}-{d.month:02d}-{d.day:02d}"), None)
        m["latest_quarter"] = fiscal_label(latest["period_end"])
        m["latest_period_end"] = latest["period_end"]
        m["latest_is_derived"] = bool(latest.get("derived"))
        m["latest_is_unverified"] = 1 if latest.get("unverified") else 0
        m["latest_from_pdf"] = 1 if latest.get("from_pdf") else 0
        m["reporting_basis"] = latest.get("nature")  # Consolidated / Non-Consolidated when known
        m["revenue_growth_yoy"] = _growth(latest.get("revenue"), yago and yago.get("revenue"))
        m["profit_growth_yoy"] = _growth(latest.get("net_profit"), yago and yago.get("net_profit"))
        m["operating_margin"] = _margin(latest.get("operating_profit"), latest.get("revenue"))
        m["net_margin"] = _margin(latest.get("net_profit"), latest.get("revenue"))
        last4 = qs[-4:]
        if len(last4) == 4 and _consecutive(last4):
            for key, out in (("revenue", "revenue_ttm"), ("net_profit", "net_profit_ttm"), ("eps", "eps_ttm")):
                vals = [q.get(key) for q in last4]
                m[out] = round(sum(vals), 4) if all(v is not None for v in vals) else None
        m["quarters_available"] = len(qs)
        due = next_results_due(d)
        m["latest_quarter_age_days"] = (today - d).days
        m["next_results_due"] = due.isoformat()
        m["results_overdue"] = 1 if today > due and not latest.get("derived") else 0
        newest = max((a["period_end"] for a in company.get("announced", [])), default=None)
        if newest and newest > latest["period_end"]:
            a = next(x for x in company["announced"] if x["period_end"] == newest)
            m["announced_newer_than_data"] = 1
            m["announced_period_end"] = newest
            company = {**company, "warnings": company["warnings"] + [
                f"exchange announcements show results for the period ended {newest} (announced {a['announced_at']}, {a['url']}) "
                f"but the structured data stops at {latest['period_end']}: figures here are OUT OF DATE"]}
        elif company.get("announced"):
            m["announced_newer_than_data"] = 0
        if m["results_overdue"]:
            company = {**company, "warnings": company["warnings"] + [
                f"{m['latest_quarter']} is the newest quarter in this feed but the next quarter's results were due by {due}: "
                "they are probably filed and missing here"]}
    m["data_warnings"] = "; ".join(company["warnings"]) or None
    m.update({k: v for k, v in (company.get("ratios") or {}).items()})
    meta = company.get("meta") or {}
    if meta:
        m["data_source"], m["fetched_at"], m["stale"] = meta.get("data_source"), meta.get("fetched_at"), meta.get("stale", False)
    return m
