"""Drift table and rebalance proposals (whole shares, sells first). Logic adapted from trader-skill's
trader-rebalance (MIT). A stock is only traded when it is outside the band; proposals are filtered by a
minimum trade value and an estimated-cost check so tiny trades that fees would eat are dropped."""
from typing import Dict, List

from . import charges as chg
from .sizing import cap_weights, normalise


def drift_table(positions: List[dict], prices: Dict[str, float], targets: Dict[str, float], cash: float) -> dict:
    t = normalise(targets)
    values = {p["symbol"]: p["qty"] * prices[p["symbol"]] for p in positions if prices.get(p["symbol"])}
    total = cash + sum(values.values())
    rows = []
    for s in sorted(set(values) | set(t)):
        cur = values.get(s, 0.0) / total * 100 if total else 0.0
        tgt = t.get(s, 0.0) * 100
        rows.append({"symbol": s, "value": round(values.get(s, 0.0), 2), "current_pct": round(cur, 2),
                     "target_pct": round(tgt, 2), "drift_pct": round(cur - tgt, 2), "tracked": s in t})
    return {"total_value": round(total, 2), "cash": round(cash, 2), "rows": rows}


def propose(positions: List[dict], prices: Dict[str, float], targets: Dict[str, float], cash: float, *,
            band_pct: float = 5.0, min_trade_value: float = 5000.0, max_position_pct: float = 100.0,
            cash_buffer_pct: float = 0.0, sell_untracked: bool = False, rates: dict = None) -> dict:
    """-> {orders:[{symbol,side,qty,price,value,reason,est_charges}], skipped:[(symbol, why)], table}.
    Sells come first; buys are scaled down to the cash available after the sells."""
    t = cap_weights(normalise(targets), max_position_pct / 100.0)
    table = drift_table(positions, prices, t, cash)
    total = table["total_value"]
    held = {p["symbol"]: p["qty"] for p in positions}
    sells, buys, skipped = [], [], []
    for row in table["rows"]:
        s, px = row["symbol"], prices.get(row["symbol"])
        if not px:
            skipped.append((s, "no price"))
            continue
        if not row["tracked"]:
            if sell_untracked and held.get(s):
                sells.append((s, held[s], "not in target list"))
            continue
        if abs(row["drift_pct"]) <= band_pct:
            continue
        want = int(t[s] * total // px)                       # whole shares at target weight
        delta = want - held.get(s, 0)
        (sells if delta < 0 else buys).append((s, abs(delta), f"drift {row['drift_pct']:+.1f} pts"))
    orders = []
    for s, q, why in sells:
        if q * prices[s] < min_trade_value and q != held.get(s):
            skipped.append((s, f"sell value below minimum trade {min_trade_value:g}"))
            continue
        orders.append(_o(s, "SELL", q, prices[s], why, rates))
    avail = cash + sum(o["value"] - o["est_charges"] for o in orders) - total * cash_buffer_pct / 100
    for s, q, why in sorted(buys, key=lambda b: -b[1] * prices[b[0]]):
        while q > 0 and q * prices[s] + chg.estimate("BUY", q, prices[s], rates)["total"] > avail:
            q -= 1                                           # scale down to the cash available
        if q <= 0 or q * prices[s] < min_trade_value:
            skipped.append((s, "insufficient cash or below minimum trade"))
            continue
        o = _o(s, "BUY", q, prices[s], why, rates)
        avail -= o["value"] + o["est_charges"]
        orders.append(o)
    return {"orders": orders, "skipped": skipped, "table": table}


def _o(s, side, q, px, why, rates):
    return {"symbol": s, "side": side, "qty": q, "price": px, "value": round(q * px, 2), "reason": why,
            "est_charges": chg.estimate(side, q, px, rates)["total"]}
