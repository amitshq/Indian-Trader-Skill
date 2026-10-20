#!/usr/bin/env python3
"""Order tickets and explicit one-order approvals for the PAPER broker (live brokers use the same gate).
    python ticket.py show                       # pending orders, each as a ticket with risk verdict and charges
    python ticket.py approve ID --reply "yes buy 10 TCS"   # approves only if the reply passes the strict yes-parser
    python ticket.py decline ID
    python ticket.py log                        # order history
Approval re-runs the risk gate at that moment. 'sure', 'yes to all', or a wrong quantity/stock are refused.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.broker.paper import PaperBroker  # noqa: E402
from core import approval, charges, cli  # noqa: E402
from core.fmt import inr  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = cli.common_parser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", parents=[common])
    p = sub.add_parser("approve", parents=[common])
    p.add_argument("id", type=int)
    p.add_argument("--reply", required=True, help="the user's literal words")
    d = sub.add_parser("decline", parents=[common])
    d.add_argument("id", type=int)
    sub.add_parser("log", parents=[common])
    a = ap.parse_args(argv)
    store = cli.open_store(a.db)
    syms = {o.symbol for o in store.list_orders()} | {p["symbol"] for p in store.positions()}
    prices = cli.load_prices(a.prices, syms) if syms else {}
    from adapters.data.quotes import StaticQuotes
    broker = PaperBroker(store, StaticQuotes(prices))
    try:
        if a.cmd == "show":
            for o in store.list_orders("PENDING"):
                v = broker.risk_verdict(o, exclude_id=o.id)
                px = o.price or prices.get(o.symbol)
                est = charges.estimate(o.side, o.qty, px)["total"] if px else None
                print(f"#{o.id}  {o.side} {o.qty} {o.symbol} {o.order_type} {o.product}  ~{inr(o.qty * px) if px else 'no price'}"
                      f"  est. charges {inr(est) if est is not None else '-'}  risk {v['verdict']} [{v['fingerprint']}]")
                for x in v["reasons"] + v["warnings"]:
                    print("      -", x)
            print("PAPER mode. Reply 'yes' naming this one order to approve it.")
            return 0
        if a.cmd == "log":
            for o in store.list_orders():
                print(f"#{o.id} {o.created_at[:19]} {o.side} {o.qty} {o.symbol} {o.status}"
                      f"{' @ ' + str(o.fill_price) if o.fill_price else ''} {o.reason}")
            return 0
        o = store.get_order(a.id)
        if o is None:
            return cli.fail(f"no order #{a.id}")
        if a.cmd == "decline":
            print(broker.reject(a.id).status)
            return 0
        ok, why = approval.parse_yes(a.reply, o)
        if not ok:
            return cli.fail(f"not approved: {why}", 1)
        r = broker.approve(a.id)
        print(f"#{r.id} {r.status}" + (f" @ {r.fill_price}" if r.fill_price else f" {r.reason}"))
        return 0 if r.status == "FILLED" else 1
    except (KeyError, ValueError) as e:
        return cli.fail(f"ticket: {e}")


if __name__ == "__main__":
    sys.exit(main())
