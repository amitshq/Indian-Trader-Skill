"""Shared helpers for the skill command-line tools (prices, paper store, JSON output)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def common_parser():
    """Parent parser so --prices/--db/--json work AFTER a subcommand too."""
    import argparse
    ap = argparse.ArgumentParser(add_help=False)
    add_common(ap)
    return ap


def add_common(ap):
    ap.add_argument("--prices", help='JSON file {"prices": {"TCS": 4000}} (otherwise delayed Yahoo quotes are used)')
    ap.add_argument("--db", help="paper-trading database (default data/india_trader.db)")
    ap.add_argument("--json", action="store_true")


def load_prices(path, symbols):
    """-> {symbol: price}. File first; otherwise delayed, unofficial Yahoo quotes."""
    if path:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {k.upper(): float(v) for k, v in (d.get("prices", d)).items()}
    from adapters.data.quotes import YFinanceQuotes
    return YFinanceQuotes().ltp(sorted(set(symbols)))


def open_store(db=None):
    from core.store import DEFAULT_DB, Store
    return Store(db or DEFAULT_DB)


def emit(obj, as_json, text_fn):
    if as_json:
        print(json.dumps(obj, indent=1, default=str))
    else:
        print(text_fn(obj))


def fail(msg, code=2):
    print(msg, file=sys.stderr)
    return code
