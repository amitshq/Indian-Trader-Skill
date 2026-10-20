"""Strict yes-parser for approving ONE order in chat (ported idea from trader-skill's trader-broker).
Rejects vague or batch approvals and any 'yes' that names a different stock, quantity or side."""
import re

from .models import Order

YES = re.compile(r"^\s*(yes|y|confirm|confirmed|approve|approved|place it|go ahead)\b", re.I)
VAGUE = re.compile(r"\b(all|everything|both|rest|others?|any|whatever|sure|maybe|probably|ok(ay)?)\b", re.I)


def parse_yes(text: str, order: Order) -> tuple:
    """-> (approved: bool, reason). Accepts e.g. 'yes', 'yes buy 10 TCS', 'confirm'. Anything naming a
    different symbol, side or number, or 'yes to all', is refused."""
    t = (text or "").strip()
    if not YES.match(t):
        return False, "reply must start with yes/confirm/approve"
    if VAGUE.search(t):
        return False, "approval must be for this one order only (no 'all', 'sure', 'ok'...)"
    words = re.findall(r"[A-Za-z&\-]+", t.upper())
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\b\d[\d,]*\b", t)]
    other_side = "SELL" if order.side == "BUY" else "BUY"
    if other_side in words:
        return False, f"you wrote {other_side} but this order is {order.side}"
    stray = [w for w in words if w.isalpha() or "&" in w or "-" in w]
    known = {"YES", "Y", "CONFIRM", "CONFIRMED", "APPROVE", "APPROVED", "PLACE", "IT", "GO", "AHEAD", "BUY", "SELL",
             "SHARES", "SHARE", "OF", "THE", "ORDER", "FOR", "AT", order.symbol.upper()}
    unknown = [w for w in stray if w not in known]
    if unknown:
        return False, f"unrecognised word(s) {unknown}: approve this order ({order.side} {order.qty} {order.symbol}) exactly or decline"
    if any(n != order.qty for n in numbers):
        return False, f"quantity in your reply does not match this order ({order.qty})"
    return True, "approved"
