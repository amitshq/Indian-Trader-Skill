#!/usr/bin/env python3
"""Drift table and rebalance proposals for the paper portfolio (whole shares, sells first).
    python rebalance.py --targets '{"TCS":40,"ITC":30,"INFY":30}' [--band 5] [--min-trade 5000] [--sell-untracked] [--queue]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import cli, rebalance, risk, sizing  # noqa: E402
from core.fmt import inr  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--targets", required=True, help="JSON object symbol -> weight, or a JSON file with 'weights'")
    ap.add_argument("--band", type=float, default=5.0, help="only trade names this many %% points off target")
    ap.add_argument("--min-trade", type=float, default=5000.0)
    ap.add_argument("--max-position", type=float, default=100.0)
    ap.add_argument("--sell-untracked", action="store_true")
    ap.add_argument("--queue", action="store_true", help="submit proposals to the paper approval queue")
    cli.add_common(ap)
    a = ap.parse_args(argv)
    try:
        raw = a.targets
        t = json.loads(Path(raw).read_text(encoding="utf-8"))["weights"] if Path(raw).exists() else json.loads(raw)
        t = {k.upper(): float(v) for k, v in t.items()}
        store = cli.open_store(a.db)
        pos = store.positions()
        prices = cli.load_prices(a.prices, list(t) + [p["symbol"] for p in pos])
        res = rebalance.propose(pos, prices, t, store.get_cash(), band_pct=a.band, min_trade_value=a.min_trade,
                                max_position_pct=a.max_position, sell_untracked=a.sell_untracked,
                                cash_buffer_pct=risk.RiskConfig.load().cash_buffer_pct)
    except (sizing.SizingError, OSError, KeyError, ValueError) as e:
        return cli.fail(f"rebalance: {e}")
    if a.queue:
        from adapters.broker.paper import PaperBroker
        from adapters.data.quotes import StaticQuotes
        from core.models import Order
        b = PaperBroker(store, StaticQuotes(prices))
        res["queued"] = [{"symbol": o["symbol"], "side": o["side"], "id": (q := b.submit(Order(o["symbol"], o["side"], o["qty"]))).id,
                          "status": q.status, "reason": q.reason} for o in res["orders"]]

    def text(r):
        tb = r["table"]
        lines = [f"portfolio {inr(tb['total_value'])} (cash {inr(tb['cash'])})", f"{'symbol':<12}{'now':>8}{'target':>8}{'drift':>8}"]
        lines += [f"{x['symbol']:<12}{x['current_pct']:>7.1f}%{x['target_pct']:>7.1f}%{x['drift_pct']:>+7.1f}{'' if x['tracked'] else '  (untracked)'}"
                  for x in tb["rows"]]
        lines.append("proposed:" if r["orders"] else "nothing to do: every tracked stock is inside the band")
        lines += [f"  {o['side']:<4}{o['qty']:>6} {o['symbol']:<12}@ {o['price']:>10,.2f} = {inr(o['value'])}  est. charges {inr(o['est_charges'])}  ({o['reason']})"
                  for o in r["orders"]]
        lines += [f"  skipped {s}: {why}" for s, why in r["skipped"]]
        lines += [f"  queued #{q['id']} {q['side']} {q['symbol']}: {q['status']} {q['reason']}" for q in r.get("queued", [])]
        lines.append("Selling realises tax (see in-tax simulate). Proposals need the risk gate and your explicit approval.")
        return "\n".join(lines)
    cli.emit(res, a.json, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
