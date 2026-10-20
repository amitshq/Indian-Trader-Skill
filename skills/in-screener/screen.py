#!/usr/bin/env python3
"""CLI over core.screener. Usage:
    python screen.py [--data FILE.json|FILE.csv] [--rules RULES.json] [--prices PRICES.json] [--json]
Exit codes: 0 some pass, 1 none pass, 2 bad input.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.data.fundamentals import CsvMetrics, JsonFundamentals  # noqa: E402
from core import screener  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(ROOT / "fixtures" / "sample_fundamentals.json"))
    ap.add_argument("--rules", default=str(ROOT / "config" / "rules.example.json"))
    ap.add_argument("--symbols", nargs="+", help="fetch LIVE results for these NSE symbols instead of --data")
    ap.add_argument("--source", choices=["verified", "nse", "yahoo"], default="verified",
                    help="with --symbols: verified = NSE filings cross-checked with Yahoo (default), "
                         "nse = filings only, yahoo = Yahoo only")
    ap.add_argument("--prices", help='JSON {"prices": {"TCS": 4000}}; adds price, pe, earnings_yield')
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        spec = json.loads(Path(a.rules).read_text(encoding="utf-8"))
        if a.symbols:
            from adapters.data.yf_fundamentals import YFinanceFundamentals
            if a.source == "yahoo":
                src = YFinanceFundamentals(a.symbols)
            else:
                from adapters.data.nse_results import NSEResults
                nse = NSEResults(a.symbols)
                if a.source == "nse":
                    src = nse
                else:
                    from adapters.data.crosscheck import CrossCheckedFundamentals
                    src = CrossCheckedFundamentals(nse, YFinanceFundamentals(a.symbols))
        else:
            src = CsvMetrics(a.data) if a.data.lower().endswith(".csv") else JsonFundamentals(a.data)
        rows = src.metrics()
        for sym, why in getattr(src, "errors", {}).items():
            print(f"screen: no data for {sym}: {why}", file=sys.stderr)
        if a.prices:
            d = json.loads(Path(a.prices).read_text(encoding="utf-8"))
            screener.add_prices(rows, {k.upper(): v for k, v in d.get("prices", d).items()})
        results = screener.screen(rows, spec)
    except (screener.ScreenError, OSError, ValueError) as e:
        print(f"screen: {e}", file=sys.stderr)
        return 2
    passed = [r for r in results if r["passed"]]
    if a.json:
        print(json.dumps([{k: r[k] for k in ("ticker", "passed", "score", "passes", "fails")}
                          for r in results], indent=2))
    else:
        print(f"{spec.get('name', 'screen')}: {len(passed)} of {len(results)} pass (data: {src.source})")
        for i, r in enumerate(passed, 1):
            print(f"{i:2}. PASS {r['ticker']:<10} score {r['score']}  ({r['metrics'].get('latest_quarter', 'period n/a')})")
            for w in r["passes"]:
                print(f"        ok   {w}")
            if r["metrics"].get("data_warnings"):
                print(f"        WARN {r['metrics']['data_warnings']}")
        for r in results:
            if not r["passed"]:
                print(f"    FAIL {r['ticker']:<10} " + "; ".join(r["fails"]))
        print("\nA screen is a filter on reported numbers, not a recommendation.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
