#!/usr/bin/env python3
"""Latest bulk/block deals and FII/DII flows from NSE.
    python deals.py deals [--min-cr 10] [--json]     per-stock buy/sell value (INR crore) in the latest session
    python deals.py flows [--json]                   FII/FPI and DII cash-market buy/sell/net (INR crore)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.data.nse_market import NSEMarket, summarize_deals  # noqa: E402
from adapters.data.nse_results import NSEError  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=["deals", "flows"])
    ap.add_argument("--min-cr", type=float, default=10.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    m = NSEMarket()
    try:
        if a.what == "flows":
            rows = m.fii_dii()
            print(json.dumps(rows, indent=1) if a.json else "\n".join(
                f"{r['date']} {r['category']:<8} buy {r['buy']:>10,.2f}  sell {r['sell']:>10,.2f}  net {r['net']:>+10,.2f}" for r in rows))
            return 0 if rows else 1
        d = m.large_deals()
        rows = summarize_deals(d, a.min_cr)
        if a.json:
            print(json.dumps({"as_on": d["as_on"], "stocks": rows}, indent=1))
        else:
            print(f"Bulk+block deals as on {d['as_on']} (value in INR crore; >= {a.min_cr})")
            for r in rows:
                print(f"{r['symbol']:<12} buy {r['buy_cr']:>9,.2f}  sell {r['sell_cr']:>9,.2f}  net {r['net_cr']:>+9,.2f}  ({r['deals']} deals)")
            print("\nA deal shows who traded, not why. Matching buy and sell by funds/brokers is often churn, not conviction.")
        return 0 if rows else 1
    except NSEError as e:
        print(f"deals: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
