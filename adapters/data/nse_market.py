"""Market-wide NSE data beyond results: holidays, bulk/block deals, FII/DII flows, shareholding
pattern (promoter %), insider (SEBI PIT) trades. All through NSEClient (rate limited, retried).
Unofficial endpoints: shapes were checked live in Oct 2026; parsers tolerate missing keys.
"""
import json
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from .nse_results import BASE, NSEClient, NSEError

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _d(s: Optional[str]) -> Optional[str]:
    """'19-Oct-2026' / '30-SEP-2026' / '15-Oct-2026 19:20:08' / '19-10-2026' -> ISO date (None if unparseable)."""
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y"):  # %b matching is case-insensitive
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _f(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


class NSEMarket:
    def __init__(self, client: Optional[NSEClient] = None):
        self.client = client or NSEClient(min_interval=0.7)

    def _json(self, path: str):
        try:
            return self.client._get(BASE + path).json()
        except ValueError as e:
            raise NSEError(f"{path}: response was not JSON") from e

    # --- trading holidays (equity segment)
    def holidays(self) -> List[dict]:
        data = self._json("/api/holiday-master?type=trading")
        return [{"date": _d(h["tradingDate"]), "description": h.get("description"),
                 "weekday": h.get("weekDay"),
                 # NSE marks the Muhurat (Diwali evening) session with '*' in the name; timings are announced separately
                 "special_session": bool(h.get("morning_session") or h.get("evening_session")
                                         or (h.get("description") or "").rstrip().endswith("*"))}
                for h in data.get("CM", []) if _d(h.get("tradingDate"))]

    def write_holidays_config(self, path: Path = CONFIG_DIR / "holidays.json") -> dict:
        hs = self.holidays()
        if not hs:
            raise NSEError("NSE returned no holidays; config left unchanged")
        years = sorted({h["date"][:4] for h in hs})
        weekday_holidays = [h["date"] for h in hs if date.fromisoformat(h["date"]).weekday() < 5]
        doc = {"_note": "Source: NSE holiday-master (CM segment), fetched " + date.today().isoformat() +
                        ". Weekend entries are listed in 'on_weekend' for information only.",
               "year": years[0] if len(years) == 1 else years,
               "holidays": weekday_holidays,
               "on_weekend": [h["date"] for h in hs if date.fromisoformat(h["date"]).weekday() >= 5],
               "descriptions": {h["date"]: h["description"] for h in hs},
               "special_sessions": [h["date"] for h in hs if h["special_session"]]}
        path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        return doc

    # --- deals
    def large_deals(self) -> dict:
        """Latest session's bulk, block and short deals: {as_on, bulk:[...], block:[...], short:[...]}."""
        d = self._json("/api/snapshot-capital-market-largedeal")

        def norm(rows):
            return [{"date": _d(r.get("date")), "symbol": r.get("symbol"), "name": r.get("name"),
                     "client": r.get("clientName"), "side": r.get("buySell"), "qty": int(_f(r.get("qty")) or 0),
                     "price": _f(r.get("watp")), "remarks": r.get("remarks")} for r in rows or []]
        return {"as_on": _d(d.get("as_on_date")), "bulk": norm(d.get("BULK_DEALS_DATA")),
                "block": norm(d.get("BLOCK_DEALS_DATA")), "short": norm(d.get("SHORT_DEALS_DATA"))}

    # --- institutional flows
    def fii_dii(self) -> List[dict]:
        return [{"category": r["category"], "date": _d(r["date"]), "buy": _f(r["buyValue"]),
                 "sell": _f(r["sellValue"]), "net": _f(r["netValue"])} for r in self._json("/api/fiidiiTradeReact")]

    # --- ownership
    def shareholding(self, symbol: str) -> List[dict]:
        """Shareholding-pattern filings, newest first: promoter & promoter-group % and public %."""
        rows = self._json(f"/api/corporate-share-holdings-master?index=equities&symbol={quote(symbol, safe='')}")
        out = [{"as_of": _d(r.get("date")), "promoter_pct": _f(r.get("pr_and_prgrp")), "public_pct": _f(r.get("public_val")),
                "employee_trusts_pct": _f(r.get("employeeTrusts")), "broadcast": _d(r.get("broadcastDate"))} for r in rows]
        return sorted([o for o in out if o["as_of"]], key=lambda o: o["as_of"], reverse=True)

    # --- insider trading (SEBI PIT regulation disclosures)
    def insider_trades(self, symbol: Optional[str], from_date: str, to_date: str) -> List[dict]:
        q = f"index=equities&from_date={from_date}&to_date={to_date}" + (f"&symbol={quote(symbol, safe='')}" if symbol else "")
        rows = self._json("/api/corporates-pit?" + q).get("data", [])
        return [normalize_pit(r) for r in rows]


def normalize_pit(r: dict) -> dict:
    """NSE PIT rows -> stable keys. Raw row kept for anything not mapped."""
    g = r.get
    return {"symbol": g("symbol"), "company": g("company"), "person": g("acqName"), "category": g("personCategory"),
            "security": g("secType"), "qty": _f(g("secAcq")), "value": _f(g("secVal")),
            "type": g("tdpTransactionType"), "mode": g("acqMode"),
            "from_date": _d(g("acqfromDt")), "to_date": _d(g("acqtoDt")), "intimated": _d(g("intimDt")),
            "after_pct": _f(g("afterAcqSharesPer")), "raw": r}


# ------------------------------------------------------------------ analytics (pure)

def summarize_deals(deals: dict, min_value_cr: float = 0.0) -> List[dict]:
    """Per-symbol net quantity and value across bulk+block rows, biggest absolute value first.
    value = qty * price in INR crore. Same client on both sides of one trade nets to zero."""
    agg = {}
    for kind in ("bulk", "block"):
        for r in deals.get(kind, []):
            if r["price"] is None:
                continue
            sign = 1 if (r["side"] or "").upper().startswith("B") else -1
            a = agg.setdefault(r["symbol"], {"symbol": r["symbol"], "name": r["name"], "buy_cr": 0.0, "sell_cr": 0.0, "deals": 0})
            v = r["qty"] * r["price"] / 1e7
            a["buy_cr" if sign > 0 else "sell_cr"] += v
            a["deals"] += 1
    rows = []
    for a in agg.values():
        a["net_cr"] = round(a["buy_cr"] - a["sell_cr"], 2)
        a["buy_cr"], a["sell_cr"] = round(a["buy_cr"], 2), round(a["sell_cr"], 2)
        if max(a["buy_cr"], a["sell_cr"]) >= min_value_cr:
            rows.append(a)
    return sorted(rows, key=lambda a: max(a["buy_cr"], a["sell_cr"]), reverse=True)


def promoter_signals(history: List[dict]) -> dict:
    """Latest promoter % and the change vs the previous filing (percentage points)."""
    if not history or history[0]["promoter_pct"] is None:
        return {}
    cur = history[0]
    prev = next((h for h in history[1:] if h["promoter_pct"] is not None), None)
    return {"promoter_holding": cur["promoter_pct"], "promoter_holding_as_of": cur["as_of"],
            "promoter_holding_change": round(cur["promoter_pct"] - prev["promoter_pct"], 2) if prev else None}
