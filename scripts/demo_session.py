#!/usr/bin/env python3
"""Rehearse the whole toolkit on the real Indian market with DUMMY money (nothing touches a broker).

    python scripts/demo_session.py                       # now, Rs 1,00,000 dummy capital, 6 large caps
    python scripts/demo_session.py --wait-for-open       # sleep until ~09:20 IST on the next trading day, then run
    python scripts/demo_session.py --hold-minutes 10     # after buying, wait 10 min, re-quote, show P&L

Writes a report to data/reports/demo_<date>_<time>.md and prints it. The approval step is SIMULATED
(the script plays the user); in real use you approve every order yourself.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import calendar_in  # noqa: E402


def wait_for_open(target_hhmm="09:20"):
    """Sleep until target time (IST) on a trading day. Prints a heartbeat every 10 min."""
    while True:
        now = datetime.now(calendar_in.IST)
        h, m = map(int, target_hhmm.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now >= target or not calendar_in.is_trading_day(now.date()):
            if calendar_in.is_trading_day(now.date()) and now >= target:
                return
            target = datetime.combine(calendar_in.next_open(now, calendar_in.load_holidays()).date(), target.time(), calendar_in.IST)
        left = (target - now).total_seconds()
        if left <= 0:
            return
        print(f"waiting for {target.isoformat(timespec='minutes')} IST ({left / 3600:.1f} h)", flush=True)
        time.sleep(min(left, 600))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capital", type=float, default=100000.0, help="DUMMY rupees")
    ap.add_argument("--symbols", nargs="+", help="default: first 6 of config/universe.json")
    ap.add_argument("--hold-minutes", type=float, default=0)
    ap.add_argument("--wait-for-open", action="store_true")
    ap.add_argument("--no-screen", action="store_true", help="skip the (slow, networked) fundamentals screen")
    a = ap.parse_args(argv)
    if a.wait_for_open:
        wait_for_open()
    from adapters import demo_runner
    res = demo_runner.run(capital=a.capital, symbols=a.symbols, hold_minutes=a.hold_minutes, include_screen=not a.no_screen)
    print(res["text"])
    print(f"\nreport saved: {res['file']}   (paper database: {res['db']})")
    report = res["report"]
    return 1 if report["counts"]["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
