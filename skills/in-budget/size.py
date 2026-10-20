#!/usr/bin/env python3
"""Whole-share BUY proposals from target weights and a budget (INR). Writes nothing to the broker.
    python size.py --budget 500000 --weights '{"TCS":40,"ITC":30,"INFY":30}' [--prices p.json] [--max-position 35]
    python size.py --budget 500000 --targets targets.json     # {"weights": {...}}  (e.g. from a screener shortlist)
Add --queue to submit the proposals to the paper broker's approval queue (risk-checked; nothing fills).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import cli, sizing  # noqa: E402
from core.fmt import inr  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, required=True)
    ap.add_argument("--weights", help="JSON object symbol -> weight")
    ap.add_argument("--targets", help="JSON file with a 'weights' object")
    ap.add_argument("--cash-buffer", type=float, default=5.0)
    ap.add_argument("--max-position", type=float, default=100.0, help="max %% of the invested amount in one stock")
    ap.add_argument("--min-order", type=float, default=1000.0)
    ap.add_argument("--queue", action="store_true", help="submit to the paper approval queue")
    cli.add_common(ap)
    a = ap.parse_args(argv)
    try:
        w = json.loads(a.weights) if a.weights else json.loads(Path(a.targets).read_text(encoding="utf-8"))["weights"]
        w = {k.upper(): float(v) for k, v in w.items()}
        prices = cli.load_prices(a.prices, w)
        res = sizing.size_buys(w, prices, a.budget, cash_buffer_pct=a.cash_buffer,
                               max_position_pct=a.max_position, min_order_value=a.min_order)
    except (sizing.SizingError, OSError, KeyError, ValueError) as e:
        return cli.fail(f"size: {e}")
    if a.queue:
        from adapters.broker.paper import PaperBroker
        from adapters.data.quotes import StaticQuotes
        from core.models import Order
        store = cli.open_store(a.db)
        broker = PaperBroker(store, StaticQuotes(prices))
        res["queued"] = [{"symbol": o["symbol"], **{k: v for k, v in broker.submit(Order(o["symbol"], "BUY", o["qty"])).to_dict().items()
                                                   if k in ("id", "status", "reason")}} for o in res["orders"]]

    def text(r):
        lines = [f"{'symbol':<12}{'qty':>6}{'price':>12}{'value':>14}{'target':>8}{'actual':>8}"]
        lines += [f"{o['symbol']:<12}{o['qty']:>6}{o['price']:>12,.2f}{o['value']:>14,.2f}{o['weight_target']:>8.1%}{o['weight_actual']:>8.1%}"
                  for o in r["orders"]]
        lines.append(f"invested {inr(r['invested'])}, leftover {inr(r['leftover'])} (includes the {a.cash_buffer:g}% cash buffer)")
        lines += [f"skipped {s}: {why}" for s, why in r["skipped"]]
        lines += [f"queued #{q['id']} {q['symbol']}: {q['status']} {q['reason']}" for q in r.get("queued", [])]
        lines.append("Proposals only. Orders still need the risk gate and your explicit approval.")
        return "\n".join(lines)
    cli.emit(res, a.json, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
