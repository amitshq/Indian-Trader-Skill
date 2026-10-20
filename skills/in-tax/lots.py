#!/usr/bin/env python3
"""Tax lots, realised gains and a capital-gains estimate for DELIVERY equity in the paper account.
    python lots.py lots [SYMBOL]            open lots with age and short/long term
    python lots.py realized                 realised gains per sale
    python lots.py estimate [--fy FY2026-27]
    python lots.py simulate SYMBOL QTY PRICE [--method FIFO|HIFO]    what selling would realise
    python lots.py harvest [--min-loss 1000]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import charges, cli, tax  # noqa: E402
from core.fmt import inr  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = cli.common_parser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lots", parents=[common])
    s.add_argument("symbol", nargs="?")
    sub.add_parser("realized", parents=[common])
    e = sub.add_parser("estimate", parents=[common])
    e.add_argument("--fy", default=tax.fy_of(date.today()))
    m = sub.add_parser("simulate", parents=[common])
    m.add_argument("symbol"), m.add_argument("qty", type=int), m.add_argument("price", type=float)
    m.add_argument("--method", default="FIFO", choices=["FIFO", "HIFO"])
    h = sub.add_parser("harvest", parents=[common])
    h.add_argument("--min-loss", type=float, default=1000.0)
    a = ap.parse_args(argv)
    store, today = cli.open_store(a.db), date.today()
    try:
        if a.cmd == "lots":
            for l in store.list_lots(a.symbol.upper() if a.symbol else None):
                d = date.fromisoformat(l["date"])
                print(f"lot {l['id']:<4}{l['symbol']:<12}{l['qty']:>6} @ {l['price']:>10,.2f}  bought {l['date']}  now {tax.term(d, today)}")
        elif a.cmd == "realized":
            for r in store.list_realized():
                print(f"{r['sell_date']} {r['symbol']:<12}{r['qty']:>6}  bought {r['buy_date']} @ {r['buy_price']:,.2f}, sold @ {r['sell_price']:,.2f}"
                      f"  net {inr(r['net_pnl'])} {r['term']} {r['fy']}")
        elif a.cmd == "estimate":
            est = tax.estimate_tax(store.list_realized(), a.fy)
            print(f"{est['fy']}: STCG {inr(est['stcg_net'])}, LTCG {inr(est['ltcg_net'])} -> estimated tax {inr(est['estimated_tax'])}"
                  f"  (rates as of {est['rates_as_of']}, UNVERIFIED)\n{est['note']}")
        elif a.cmd == "simulate":
            sym = a.symbol.upper()
            fee = charges.estimate("SELL", a.qty, a.price)["total"]
            rows = tax.realize(tax.match_lots(store.list_lots(sym), a.qty, a.method), a.price, today, fee)
            for r in rows:
                print(f"{r['qty']:>6} from lot {r['lot_id']} bought {r['buy_date']} @ {r['buy_price']:,.2f}: net {inr(r['net_pnl'])} {r['term']}")
            est = tax.estimate_tax(store.list_realized() + rows, tax.fy_of(today))
            print(f"estimated tax this FY if sold: {inr(est['estimated_tax'])} ({est['note']})")
        elif a.cmd == "harvest":
            pos = store.positions()
            prices = cli.load_prices(a.prices, [p["symbol"] for p in pos]) if pos else {}
            lots = {p["symbol"]: store.list_lots(p["symbol"]) for p in pos}
            for r in tax.harvest_candidates(pos, prices, lots, today, a.min_loss):
                print(f"{r['symbol']:<12}{r['qty']:>6} unrealised {inr(r['unrealised'])} ({'/'.join(r['terms'])})")
            print("Information only. Check the tax treatment of re-buying with a CA.")
    except (tax.TaxError, KeyError, ValueError) as ex:
        return cli.fail(f"tax: {ex}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
