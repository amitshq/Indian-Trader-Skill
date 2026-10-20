#!/usr/bin/env python3
"""Run the pre-trade risk gate over proposed orders against the paper portfolio.
    python check.py --orders orders.json [--prices p.json]      # [{"symbol":"TCS","side":"BUY","qty":5}, ...]
Exit 0 = every order passes, 1 = at least one blocked, 2 = bad input.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import calendar_in, cli, risk  # noqa: E402
from core.models import Order  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--orders", required=True)
    ap.add_argument("--config", default=str(risk.CONFIG))
    cli.add_common(ap)
    a = ap.parse_args(argv)
    try:
        raw = json.loads(Path(a.orders).read_text(encoding="utf-8"))
        orders = [Order(symbol=str(o["symbol"]).upper(), side=str(o["side"]).upper(), qty=int(o["qty"]),
                        order_type=str(o.get("order_type", "MARKET")).upper(), price=o.get("price")) for o in raw]
        store = cli.open_store(a.db)
        pos = store.positions()
        prices = cli.load_prices(a.prices, [o.symbol for o in orders] + [p["symbol"] for p in pos])
    except (OSError, KeyError, ValueError, TypeError) as e:
        return cli.fail(f"check: {e}")
    vs = risk.check_orders(orders, risk.RiskConfig.load(Path(a.config)), cash=store.get_cash(),
                           positions={p["symbol"]: p for p in pos}, prices=prices,
                           orders_today=store.count_orders_on(__import__("datetime").date.today().isoformat()),
                           market_status=calendar_in.market_status()["status"])
    out = [{"symbol": v["order"].symbol, "side": v["order"].side, "qty": v["order"].qty, "verdict": v["verdict"],
            "reasons": v["reasons"], "warnings": v["warnings"], "fingerprint": v["fingerprint"]} for v in vs]

    def text(rows):
        lines = []
        for r in rows:
            lines.append(f"{r['verdict']:<5} {r['side']} {r['qty']} {r['symbol']}  [{r['fingerprint']}]")
            lines += [f"        block: {x}" for x in r["reasons"]] + [f"        warn:  {x}" for x in r["warnings"]]
        lines.append("PASS is not advice; it only means the order is inside your own limits.")
        return "\n".join(lines)
    cli.emit(out, a.json, text)
    return 0 if all(r["verdict"] == "PASS" for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
