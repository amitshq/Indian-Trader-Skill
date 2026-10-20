"""Turn target weights + a budget into whole-share BUY proposals (no fractional shares in India).

Logic adapted from trader-skill's trader-budget (MIT): cash buffer off the top, renormalise,
cap each stock with iterative redistribution, drop slices below the minimum order, round down to
whole shares and hand leftover cash to the stocks furthest below target one share at a time.
"""
from typing import Dict, List, Optional


class SizingError(ValueError):
    pass


def normalise(weights: Dict[str, float]) -> Dict[str, float]:
    pos = {k: float(v) for k, v in weights.items() if v and float(v) > 0}
    total = sum(pos.values())
    if total <= 0:
        raise SizingError("no positive weights")
    return {k: v / total for k, v in pos.items()}


def cap_weights(w: Dict[str, float], cap: float) -> Dict[str, float]:
    """Cap each weight at `cap` (fraction) and redistribute the excess to uncapped names."""
    if cap * len(w) < 1 - 1e-9:
        raise SizingError(f"cap {cap:.0%} x {len(w)} stocks cannot reach 100%: add stocks or raise the cap")
    w, capped = dict(w), set()
    for _ in range(len(w) + 1):
        over = {k for k, v in w.items() if v > cap + 1e-12 and k not in capped}
        if not over:
            break
        capped |= over
        excess = sum(w[k] - cap for k in over)
        for k in over:
            w[k] = cap
        free = {k: v for k, v in w.items() if k not in capped}
        tot = sum(free.values())
        if not free or tot <= 0:
            break
        for k in free:
            w[k] += excess * free[k] / tot
    return w


def size_buys(weights: Dict[str, float], prices: Dict[str, float], budget: float, *, cash_buffer_pct: float = 5.0,
              max_position_pct: float = 100.0, min_order_value: float = 0.0) -> dict:
    """-> {orders:[{symbol,side,qty,price,value,weight_target,weight_actual}], invested, leftover, skipped:[(sym,reason)]}"""
    if budget <= 0:
        raise SizingError("budget must be positive")
    skipped = []
    w = normalise(weights)
    for s in list(w):
        if not prices.get(s) or prices[s] <= 0:
            skipped.append((s, "no price"))
            del w[s]
    if not w:
        raise SizingError("none of the symbols has a price")
    w = cap_weights(normalise(w), max_position_pct / 100.0)
    investable = budget * (1 - cash_buffer_pct / 100.0)
    qty = {s: int(investable * w[s] // prices[s]) for s in w}
    for s in [s for s in qty if qty[s] == 0 or qty[s] * prices[s] < min_order_value]:
        skipped.append((s, f"slice below minimum order {min_order_value:g}" if qty[s] else "cannot afford one share"))
        del qty[s]
    if not qty:
        raise SizingError("nothing left after minimum order and whole-share rounding")
    spent = sum(q * prices[s] for s, q in qty.items())
    cap_val = investable * max_position_pct / 100.0 if max_position_pct < 100 else investable
    while True:  # leftover cash: add one share to the name furthest below its target, if it fits
        left = investable - spent
        cands = [(w[s] - qty[s] * prices[s] / investable, s) for s in qty
                 if prices[s] <= left and (qty[s] + 1) * prices[s] <= cap_val + 1e-9]
        if not cands:
            break
        _, pick = max(cands)
        qty[pick] += 1
        spent += prices[pick]
    orders = [{"symbol": s, "side": "BUY", "qty": q, "price": prices[s], "value": round(q * prices[s], 2),
               "weight_target": round(w[s], 4), "weight_actual": round(q * prices[s] / spent, 4)}
              for s, q in sorted(qty.items(), key=lambda kv: -kv[1] * prices[kv[0]])]
    return {"orders": orders, "invested": round(spent, 2), "leftover": round(budget - spent, 2), "skipped": skipped}
