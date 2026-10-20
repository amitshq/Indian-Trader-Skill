"""Price-alert rule engine. Pure function: rules + prices -> triggered rules.

Rule: {"symbol": "RELIANCE", "kind": "above"|"below"|"pct_move", "value": float,
       "ref_price": float (pct_move only)}
"""


def evaluate(rules: list, prices: dict) -> list:
    fired = []
    for r in rules:
        px = prices.get(r["symbol"])
        if px is None:
            continue
        kind, v = r["kind"], r["value"]
        if kind == "above" and px >= v:
            hit = f"{r['symbol']} {px} >= {v}"
        elif kind == "below" and px <= v:
            hit = f"{r['symbol']} {px} <= {v}"
        elif kind == "pct_move" and r.get("ref_price"):
            move = (px - r["ref_price"]) / r["ref_price"] * 100
            if abs(move) < v:
                continue
            hit = f"{r['symbol']} moved {move:+.2f}% from {r['ref_price']}"
        else:
            continue
        fired.append({**r, "message": hit, "price": px})
    return fired
