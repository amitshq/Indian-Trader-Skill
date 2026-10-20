#!/usr/bin/env python3
"""Compute screenable metrics from reported results JSON (format: core/fundamentals.py).
    python facts.py FILE.json [SYMBOL ...] [--json] [--out metrics.json]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.data.fundamentals import JsonFundamentals  # noqa: E402

SHOW = ["latest_quarter", "revenue_growth_yoy", "profit_growth_yoy", "operating_margin",
        "net_margin", "eps_ttm", "roce", "roe", "debt_to_equity", "promoter_holding", "promoter_pledge"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help='results JSON, or "live" to fetch the SYMBOLS via yfinance')
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.file == "live":
            from adapters.data.crosscheck import CrossCheckedFundamentals
            from adapters.data.nse_results import NSEResults
            from adapters.data.yf_fundamentals import YFinanceFundamentals
            src = CrossCheckedFundamentals(NSEResults(a.symbols), YFinanceFundamentals(a.symbols))
            rows = src.metrics()
            for sym, why in src.errors.items():
                print(f"facts: no data for {sym}: {why}", file=sys.stderr)
            a.symbols = []
        else:
            rows = JsonFundamentals(a.file).metrics()
    except (OSError, ValueError, KeyError) as e:
        print(f"facts: {e}", file=sys.stderr)
        return 2
    want = {s.upper() for s in a.symbols}
    if want:
        rows = [r for r in rows if r["ticker"] in want]
    if not rows:
        return 1
    if a.out:
        Path(a.out).write_text(json.dumps({"companies": rows}, indent=2), encoding="utf-8")
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['ticker']} - {r.get('name')}" + ("  [latest quarter DERIVED from annual]" if r.get("latest_is_derived") else ""))
            if r.get("data_warnings"):
                print(f"   WARN: {r['data_warnings']}")
            for k in SHOW:
                if r.get(k) is not None:
                    print(f"   {k:<20} {r[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
