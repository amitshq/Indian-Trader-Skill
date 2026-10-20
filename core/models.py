"""Broker-agnostic order model. Equity delivery (CNC) only in phase 1."""
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# NSE symbols may contain '&' and '-' (M&M, BAJAJ-AUTO).
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")

SIDES = ("BUY", "SELL")
ORDER_TYPES = ("MARKET", "LIMIT")
EXCHANGES = ("NSE", "BSE")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Order:
    symbol: str
    side: str
    qty: int
    exchange: str = "NSE"
    series: str = "EQ"
    product: str = "CNC"
    order_type: str = "MARKET"
    validity: str = "DAY"
    price: Optional[float] = None
    id: Optional[int] = None
    status: str = "PENDING"  # PENDING -> FILLED | REJECTED | CANCELLED
    reason: str = ""
    fill_price: Optional[float] = None
    created_at: str = field(default_factory=now_iso)

    def validate(self) -> list:
        errs = []
        if not SYMBOL_RE.match(self.symbol or ""):
            errs.append(f"bad symbol {self.symbol!r}")
        if self.side not in SIDES:
            errs.append(f"side must be one of {SIDES}")
        if not isinstance(self.qty, int) or self.qty <= 0:
            errs.append("qty must be a positive whole number (no fractional shares)")
        if self.exchange not in EXCHANGES:
            errs.append(f"exchange must be one of {EXCHANGES}")
        if self.product != "CNC":
            errs.append("only CNC (delivery) is supported in phase 1")
        if self.order_type not in ORDER_TYPES:
            errs.append(f"order_type must be one of {ORDER_TYPES}")
        if self.order_type == "LIMIT" and (self.price is None or self.price <= 0):
            errs.append("LIMIT orders need a positive price")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)
