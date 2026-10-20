"""Paper broker: simulated fills at LTP (or limit price) with estimated charges and tax lots.

Flow: submit() -> risk gate -> PENDING (or BLOCKED) -> approve() re-checks risk and fills / reject() declines.
A human (UI button or an explicit chat yes) must call approve(); nothing fills on submit.
"""
from datetime import date
from typing import Callable, Optional

from core import calendar_in, charges, risk, tax
from core.models import Order
from core.store import Store

from .base import Executor


class PaperBroker(Executor):
    live = False

    def __init__(self, store: Store, quotes, rates: dict = None, risk_cfg: Optional[risk.RiskConfig] = None,
                 clock: Callable[[], date] = date.today, market_status: Callable[[], str] = None):
        self.store, self.quotes, self.rates = store, quotes, rates
        self.risk_cfg = risk_cfg or risk.RiskConfig.load()
        self.clock = clock
        self.market_status = market_status or (lambda: calendar_in.market_status()["status"])

    # ---------------------------------------------------------------- risk
    def risk_verdict(self, order: Order, exclude_id: Optional[int] = None) -> dict:
        syms = {p["symbol"] for p in self.store.positions()} | {order.symbol}
        prices = self.quotes.ltp(sorted(syms))
        pend = [o for o in self.store.list_orders("PENDING") if o.id != exclude_id and o.id != order.id]
        return risk.check_orders(
            [order], self.risk_cfg, cash=self.store.get_cash(),
            positions={p["symbol"]: p for p in self.store.positions()}, prices=prices,
            orders_today=self.store.count_orders_on(self.clock().isoformat()), market_status=self.market_status(),
            pending=pend)[0]

    def submit(self, order: Order) -> Order:
        errs = order.validate()
        if errs:
            order.status, order.reason = "REJECTED", "; ".join(errs)
            return self.store.save_order(order)
        v = self.risk_verdict(order)
        if v["verdict"] == "BLOCK":
            order.status, order.reason = "BLOCKED", "RISK: " + "; ".join(v["reasons"])
        return self.store.save_order(order)

    def reject(self, order_id: int, reason: str = "") -> Order:
        o = self._pending(order_id)
        o.status, o.reason = "REJECTED", reason or "declined by user"
        return self.store.save_order(o)

    # ---------------------------------------------------------------- execution
    def approve(self, order_id: int) -> Order:
        o = self._pending(order_id)
        v = self.risk_verdict(o, exclude_id=o.id)       # gate re-checked at the moment of approval
        if v["verdict"] == "BLOCK":
            o.status, o.reason = "BLOCKED", "RISK: " + "; ".join(v["reasons"])
            return self.store.save_order(o)
        px = o.price if o.order_type == "LIMIT" else self.quotes.ltp([o.symbol]).get(o.symbol)
        if not px:
            o.status, o.reason = "REJECTED", "no price available"
            return self.store.save_order(o)
        fee = charges.estimate(o.side, o.qty, px, self.rates)["total"]
        pos = self.store.get_position(o.symbol) or {"qty": 0, "avg_price": 0.0}
        cash, today = self.store.get_cash(), self.clock()
        if o.side == "BUY":
            cost = o.qty * px + fee
            if cost > cash:
                o.status, o.reason = "REJECTED", f"insufficient cash: need {cost:.2f}, have {cash:.2f}"
                return self.store.save_order(o)
            new_qty = pos["qty"] + o.qty
            avg = (pos["qty"] * pos["avg_price"] + o.qty * px) / new_qty
            self.store.set_position(o.symbol, new_qty, round(avg, 4))
            self.store.set_cash(cash - cost)
            self.store.add_lot(o.symbol, o.qty, px, today.isoformat(), fee / o.qty)
        else:
            if o.qty > pos["qty"]:
                o.status, o.reason = "REJECTED", f"cannot sell {o.qty}; holding {pos['qty']} (no short selling)"
                return self.store.save_order(o)
            matches = tax.match_lots(self.store.list_lots(o.symbol), o.qty, "FIFO")
            for m in matches:
                left = next(l for l in self.store.list_lots(o.symbol) if l["id"] == m["lot_id"])["qty"] - m["qty"]
                self.store.set_lot_qty(m["lot_id"], left)
            self.store.add_realized(o.symbol, tax.realize(matches, px, today, fee))
            self.store.set_position(o.symbol, pos["qty"] - o.qty, pos["avg_price"])
            self.store.set_cash(cash + o.qty * px - fee)
        o.status, o.fill_price, o.reason = "FILLED", px, ""
        return self.store.save_order(o)

    def positions(self) -> list:
        return self.store.positions()

    def _pending(self, order_id: int) -> Order:
        o = self.store.get_order(order_id)
        if o is None:
            raise KeyError(f"order {order_id} not found")
        if o.status != "PENDING":
            raise ValueError(f"order {order_id} is {o.status}, not PENDING")
        return o
