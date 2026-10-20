#!/usr/bin/env python3
"""Promoter holding (SEBI shareholding pattern) and insider-trading disclosures (SEBI PIT).
    python insider.py promoter SYMBOL [SYMBOL ...]
    python insider.py trades [SYMBOL] [--days 30]
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.data.nse_market import NSEMarket, promoter_signals  # noqa: E402
from adapters.data.nse_results import NSEError  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("promoter")
    p.add_argument("symbols", nargs="+")
    t = sub.add_parser("trades")
    t.add_argument("symbol", nargs="?")
    t.add_argument("--days", type=int, default=30)
    a = ap.parse_args(argv)
    m = NSEMarket()
    try:
        if a.cmd == "promoter":
            for s in a.symbols:
                sig = promoter_signals(m.shareholding(s.upper()))
                print(f"{s.upper():<12}", json.dumps(sig) if sig else "no shareholding filing found")
            print("\n0% promoter holding means the company has no identified promoter (e.g. ITC, HDFC Bank), not missing data.")
            return 0
        today = date.today()
        rows = m.insider_trades(a.symbol.upper() if a.symbol else None,
                                (today - timedelta(days=a.days)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y"))
        for r in rows:
            print(f"{r['intimated'] or '-'} {r['symbol']:<10} {r['person']} ({r['category']}) {r['type']} {r['qty']} sh, value {r['value']}, after {r['after_pct']}%")
        if not rows:
            print("no disclosures returned (an empty answer can also mean the NSE endpoint ignored the filter)")
        print("\nInsider disclosures are lagged filings under SEBI PIT rules; they are not proof of inside information.")
        return 0 if rows else 1
    except NSEError as e:
        print(f"insider: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
