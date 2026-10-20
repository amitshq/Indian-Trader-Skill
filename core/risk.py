"""Pre-trade risk gate. Every order is checked as if the earlier PASSing orders in the same batch had
filled. The verdict carries a fingerprint of the exact order so approval can prove the order that was
checked is the order being placed. Defaults are deliberately conservative; edit config/risk.json."""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .models import Order

CONFIG = Path(__file__).resolve().parent.parent / "config" / "risk.json"


@dataclass
class RiskConfig:
    max_position_pct: float = 20.0      # one stock, % of portfolio value after the fill
    max_order_value: float = 200000.0   # INR per order
    min_order_value: float = 1000.0
    cash_buffer_pct: float = 5.0        # keep this % of portfolio value in cash after buys
    max_orders_per_day: int = 20
    price_band_pct: float = 20.0        # LIMIT price must be within this % of last price
    blocked: List[str] = field(default_factory=list)
    allow_when_market_closed: bool = True   # paper trading; for live, orders become AMO/next session

    @classmethod
    def load(cls, path: Path = CONFIG) -> "RiskConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


def fingerprint(o: Order, day: Optional[str] = None) -> str:
    key = "|".join(str(x) for x in (o.exchange, o.symbol, o.side, o.qty, o.order_type, o.price or 0, o.product, day or date.today().isoformat()))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def check_orders(orders: List[Order], cfg: RiskConfig, *, cash: float, positions: Dict[str, dict],
                 prices: Dict[str, float], orders_today: int = 0, market_status: str = "open",
                 pending: Optional[List[Order]] = None) -> List[dict]:
    """-> one verdict per order: {order, verdict: PASS|BLOCK, reasons, warnings, checks, fingerprint}.
    `checks` lists EVERY rule that was looked at ({name, ok, detail}; ok None = not evaluated) so a UI can explain
    why an order passed, not only why it was blocked."""
    pos = {s: dict(p) for s, p in positions.items()}
    cash_now = cash
    pending_keys = {(p.symbol, p.side) for p in (pending or [])}
    out, used = [], orders_today
    seen_batch = set()
    for o in orders:
        reasons, warns, checks = list(o.validate()), [], []

        def chk(name, ok, good, bad):
            checks.append({"name": name, "ok": ok, "detail": good if ok else bad})
            if ok is False:
                reasons.append(bad)

        checks.append({"name": "Order is well-formed", "ok": not reasons,
                       "detail": "symbol, side, whole-number quantity and delivery product are valid" if not reasons else "; ".join(reasons)})
        px = o.price if o.order_type == "LIMIT" else prices.get(o.symbol)
        ref = prices.get(o.symbol)
        value = (o.qty or 0) * (px or 0)
        chk("Not on your blocked list", o.symbol not in {b.upper() for b in cfg.blocked},
            f"{o.symbol} is allowed", f"{o.symbol} is on your blocked list")
        have_px = bool(px and px > 0)
        chk("A price is available", have_px, f"price {px:,.2f}" if have_px else "", "no price available to value this order")
        if have_px:
            chk("Order value is not too large", value <= cfg.max_order_value, f"{value:,.0f} <= max {cfg.max_order_value:,.0f}",
                f"order value {value:,.0f} exceeds max {cfg.max_order_value:,.0f}")
            chk("Order value is not too small", value >= cfg.min_order_value, f"{value:,.0f} >= min {cfg.min_order_value:,.0f}",
                f"order value {value:,.0f} is below minimum {cfg.min_order_value:,.0f}")
        if o.order_type == "LIMIT" and ref and o.price:
            off = abs(o.price - ref) / ref * 100
            chk("Limit price is sane", off <= cfg.price_band_pct, f"{off:.1f}% from the last price {ref:,.2f} (allowed {cfg.price_band_pct:g}%)",
                f"limit price {o.price} is more than {cfg.price_band_pct:g}% from last price {ref}")
        chk("Daily order limit", used < cfg.max_orders_per_day, f"{used} of {cfg.max_orders_per_day} orders used today",
            f"daily order limit {cfg.max_orders_per_day} reached")
        key = (o.symbol, o.side)
        dup = key in seen_batch or key in pending_keys
        chk("No duplicate order waiting", not dup, f"no other {o.side} {o.symbol} is waiting",
            f"duplicate: another {o.side} {o.symbol} order is already in this batch or the pending queue")
        if market_status not in ("open", "pre_open"):
            if cfg.allow_when_market_closed:
                warns.append(f"market is {market_status}: a paper order fills at the last price; a live order would wait or go AMO")
                checks.append({"name": "Market hours", "ok": None, "detail": warns[-1]})
            else:
                chk("Market hours", False, "", f"market is {market_status}")
        else:
            checks.append({"name": "Market hours", "ok": True, "detail": f"market is {market_status}"})
        if px and not reasons:
            holding = pos.get(o.symbol, {"qty": 0, "avg_price": 0.0})
            if o.side == "BUY":
                total_value = cash_now + sum(p["qty"] * prices.get(s, p["avg_price"]) for s, p in pos.items())
                after = (holding["qty"] * (prices.get(o.symbol) or px) + value) / total_value * 100 if total_value else 100
                chk("Position size limit", after <= cfg.max_position_pct, f"{o.symbol} would be {after:.1f}% of the portfolio (max {cfg.max_position_pct:g}%)",
                    f"{o.symbol} would be {after:.1f}% of the portfolio (max {cfg.max_position_pct:g}%)")
                left = cash_now - value
                need = total_value * cfg.cash_buffer_pct / 100
                chk("Cash buffer kept", left >= need, f"{left:,.0f} cash left >= {need:,.0f} buffer ({cfg.cash_buffer_pct:g}%)",
                    f"cash after this buy ({left:,.0f}) is below the {cfg.cash_buffer_pct:g}% buffer")
            else:
                chk("You own enough to sell", o.qty <= holding["qty"], f"holding {holding['qty']}, selling {o.qty}",
                    f"cannot sell {o.qty}: holding {holding['qty']} (no short selling in delivery)")
        else:
            checks.append({"name": "Position size / cash buffer / holdings", "ok": None, "detail": "not evaluated until the earlier checks pass"})
        verdict = "BLOCK" if reasons else "PASS"
        if verdict == "PASS":  # simulate the fill for the next order in the batch
            seen_batch.add(key)
            used += 1
            h = pos.setdefault(o.symbol, {"qty": 0, "avg_price": 0.0})
            if o.side == "BUY":
                cash_now -= value
                h["avg_price"] = (h["qty"] * h["avg_price"] + value) / (h["qty"] + o.qty)
                h["qty"] += o.qty
            else:
                cash_now += value
                h["qty"] -= o.qty
        out.append({"order": o, "verdict": verdict, "reasons": reasons, "warnings": warns, "checks": checks, "fingerprint": fingerprint(o)})
    return out
