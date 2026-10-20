"""Exchange filings (NSE XBRL) as the authority, Yahoo as the cross-check and the source of
balance-sheet ratios. Disagreements become data_warnings instead of silent choices."""
from typing import Dict, Optional

from core import fundamentals as fnd

from .fundamentals import FundamentalsSource

COMPARE = ("revenue", "net_profit", "eps")


def compare_quarters(nse_quarters: list, yahoo_quarters: list, tolerance: float = 0.02):
    """-> (compared_periods, mismatch_messages) over quarter-ends present in both sources."""
    y = {q["period_end"]: q for q in yahoo_quarters}
    compared, msgs = 0, []
    for q in nse_quarters:
        other = y.get(q["period_end"])
        if not other:
            continue
        compared += 1
        for k in COMPARE:
            a, b = q.get(k), other.get(k)
            if a is None or b is None or a == 0:
                continue
            diff = (b - a) / abs(a)
            if abs(diff) > tolerance:
                msgs.append(f"{q['period_end']} {k}: NSE {a} vs Yahoo {b} ({diff:+.1%})")
    return compared, msgs


class CrossCheckedFundamentals(FundamentalsSource):
    source = "NSE filings (XBRL) cross-checked with Yahoo"

    def __init__(self, nse, yahoo, tolerance: float = 0.02, fill_newer: bool = False,
                 allow_yahoo_only: bool = False):
        self.nse, self.yahoo, self.tolerance = nse, yahoo, tolerance
        self.fill_newer, self.allow_yahoo_only = fill_newer, allow_yahoo_only
        self.symbols = nse.symbols
        self.errors: Dict[str, str] = {}

    def company(self, symbol: str) -> Optional[dict]:
        n, y = self.nse.company(symbol), self.yahoo.company(symbol)
        if n is None:
            self.errors[symbol] = self.nse.errors.get(symbol, "no NSE filing data")
            if y is not None and self.allow_yahoo_only:
                return {**y, "warnings": list(y.get("warnings", [])) + ["NSE filings unavailable: Yahoo only, unverified"]}
            return None
        warnings = list(n.get("warnings", []))
        out = {**n, "quarters": [dict(q) for q in n["quarters"]]}
        meta = {**n.get("meta", {}), "data_source": "nse-xbrl"}
        if y is None:
            warnings.append("Yahoo unavailable: not cross-checked, no balance-sheet ratios")
        else:
            compared, msgs = compare_quarters(n["quarters"], y["quarters"], self.tolerance)
            out["crosscheck"] = {"compared": compared, "mismatches": len(msgs)}
            warnings += [f"cross-check: {m}" for m in msgs]
            if compared == 0:
                warnings.append("cross-check: no quarter in common between NSE and Yahoo, nothing verified")
            n_latest = max(q["period_end"] for q in n["quarters"])
            newer = [q for q in y["quarters"] if q["period_end"] > n_latest]
            if newer:
                warnings.append("Yahoo has newer quarter(s) "
                                + ", ".join(q["period_end"] for q in newer)
                                + " not found in NSE data" + (" (added, UNVERIFIED)" if self.fill_newer else " (ignored)"))
                if self.fill_newer:
                    out["quarters"] += [{**q, "unverified": True, "nature": None} for q in newer]
            out["ratios"] = {**y.get("ratios", {}), **n.get("ratios", {})}   # NSE's own figures win
            if y.get("ratios"):
                warnings.append("ROCE, ROE, debt/equity and insider holding come from Yahoo, not from filings"
                                + ("; promoter holding is from the NSE shareholding pattern" if "promoter_holding" in n.get("ratios", {}) else ""))
            out["sector"] = out.get("sector") or y.get("sector")
            meta["data_source"] = "nse-xbrl+yahoo"
        out["warnings"], out["meta"] = warnings, meta
        return out

    def metrics(self):
        rows = []
        for s in self.symbols:
            c = self.company(s)
            if c:
                m = fnd.metrics_for(c)
                m["crosscheck_mismatches"] = (c.get("crosscheck") or {}).get("mismatches")
                rows.append(m)
        return rows
