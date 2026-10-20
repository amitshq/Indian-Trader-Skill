"""Estimated equity-delivery charges. Rates come from config/charges.json (unverified estimates)."""
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "charges.json"


def load_rates(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def estimate(side: str, qty: int, price: float, rates: dict = None) -> dict:
    r = rates or load_rates()
    turnover = qty * price
    brokerage = r["brokerage_per_order"]
    stt = turnover * r["stt_pct_buy" if side == "BUY" else "stt_pct_sell"] / 100
    txn = turnover * r["exchange_txn_pct"] / 100
    sebi = turnover * r["sebi_pct"] / 100
    stamp = turnover * r["stamp_duty_pct_buy"] / 100 if side == "BUY" else 0.0
    dp = r["dp_charge_per_sell_scrip"] if side == "SELL" else 0.0
    gst = (brokerage + txn + sebi) * r["gst_pct"] / 100
    total = brokerage + stt + txn + sebi + stamp + dp + gst
    return {
        "turnover": round(turnover, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(txn, 2),
        "sebi": round(sebi, 2),
        "stamp_duty": round(stamp, 2),
        "dp": round(dp, 2),
        "gst": round(gst, 2),
        "total": round(total, 2),
    }
