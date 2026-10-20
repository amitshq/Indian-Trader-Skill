"""Human-verified quarterly results, entered from the company's results PDF (or typed by Claude
while reading the PDF with the user). Stored in data/manual/<SYMBOL>.json and merged into the NSE
source. Every entry is validated, source-tagged, and shown with a warning until reviewed."""
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List

from core import fundamentals as fnd

MANUAL_DIR = Path(__file__).resolve().parents[2] / "data" / "manual"


class EntryError(ValueError):
    pass


def _path(symbol: str, base: Path) -> Path:
    return Path(base) / (re.sub(r"[^A-Za-z0-9]", "_", symbol.upper()) + ".json")


def validate_entry(e: dict) -> dict:
    """Normalise and check an entry (amounts INR crore). Raises EntryError."""
    for k in ("symbol", "period_end", "nature", "revenue", "net_profit", "eps", "pdf_url"):
        if e.get(k) in (None, ""):
            raise EntryError(f"missing {k}")
    try:
        d = date.fromisoformat(e["period_end"])
    except ValueError as x:
        raise EntryError(f"period_end must be YYYY-MM-DD: {x}")
    if d.month not in fnd.Q_END_MONTHS or (d.month, d.day) not in ((3, 31), (6, 30), (9, 30), (12, 31)):
        raise EntryError(f"{e['period_end']} is not a quarter end (31 Mar / 30 Jun / 30 Sep / 31 Dec)")
    if e["nature"] not in ("Consolidated", "Non-Consolidated"):
        raise EntryError("nature must be Consolidated or Non-Consolidated")
    for k in ("revenue", "other_income", "total_income", "net_profit", "eps"):
        if e.get(k) is not None and not isinstance(e[k], (int, float)):
            raise EntryError(f"{k} must be a number")
    oi, ti = e.get("other_income"), e.get("total_income")
    if oi is not None and ti is not None and abs(e["revenue"] + oi - ti) > max(1.0, 0.001 * abs(ti)):
        raise EntryError(f"revenue + other_income ({e['revenue']}+{oi}) does not equal total_income ({ti})")
    base = ti if ti is not None else e["revenue"]
    if abs(e["net_profit"]) > abs(base):
        raise EntryError("net_profit is larger than total income/revenue: check units (crore) and the row")
    py = e.get("prior_year")
    if py:
        for k in ("revenue", "net_profit", "eps"):
            if not isinstance(py.get(k), (int, float)):
                raise EntryError(f"prior_year.{k} must be a number (the same filing's year-ago column)")
    return {**e, "symbol": e["symbol"].upper(),
            "entered_at": e.get("entered_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")}


def save_entry(entry: dict, base: Path = MANUAL_DIR) -> dict:
    e = validate_entry(entry)
    p = _path(e["symbol"], base)
    existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    existing = [x for x in existing if not (x["period_end"] == e["period_end"] and x["nature"] == e["nature"])]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(existing + [e], key=lambda x: x["period_end"]), indent=1), encoding="utf-8")
    return e


def load_entries(symbol: str, base: Path = MANUAL_DIR) -> List[dict]:
    p = _path(symbol, base)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def merge_into(company: dict, entries: List[dict]) -> dict:
    """Add manual quarters (and their same-filing year-ago comparatives) the company dict lacks.
    Never overwrites a quarter that came from an exchange XBRL filing."""
    if not entries:
        return company
    have = {q["period_end"] for q in company["quarters"]}
    quarters, warnings = [dict(q) for q in company["quarters"]], list(company.get("warnings", []))
    for e in sorted(entries, key=lambda x: x["period_end"]):
        # prefer consolidated if the company's filings are consolidated
        if e["period_end"] in have:
            continue
        quarters.append({"period_end": e["period_end"], "revenue": e["revenue"], "operating_profit": None,
                         "net_profit": e["net_profit"], "eps": e["eps"], "nature": e["nature"],
                         "audited": e.get("audited"), "from_pdf": True, "pdf_url": e["pdf_url"]})
        have.add(e["period_end"])
        warnings.append(f"{e['period_end']} entered from results PDF ({e['pdf_url']}) by {e.get('entered_by', 'user')} "
                        f"on {e['entered_at'][:10]}; not machine-verified, review against the filing")
        py = e.get("prior_year")
        if py:
            d = date.fromisoformat(e["period_end"])
            prior_end = f"{d.year - 1}-{d.month:02d}-{d.day:02d}"
            if prior_end not in have:
                quarters.append({"period_end": prior_end, "revenue": py["revenue"], "operating_profit": None,
                                 "net_profit": py["net_profit"], "eps": py["eps"], "nature": e["nature"],
                                 "from_pdf": True, "pdf_url": e["pdf_url"], "comparative": True})
                have.add(prior_end)
    quarters.sort(key=lambda q: q["period_end"])
    return {**company, "quarters": quarters, "warnings": warnings}
