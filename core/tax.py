"""Lot matching and capital-gains estimate for listed-equity DELIVERY trades (CNC) in India.

Scope: STCG/LTCG on delivery equity only. Intraday and F&O are business income and are NOT handled.
Rates/exemption live in config/tax.json (dated, unverified): confirm with the current Finance Act or a CA.
Ignores surcharge, cess, the 31-Jan-2018 grandfathering of old holdings, and other accounts.
"""
import json
from datetime import date
from pathlib import Path
from typing import Dict, List

CONFIG = Path(__file__).resolve().parent.parent / "config" / "tax.json"


class TaxError(ValueError):
    pass


def load_rates(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fy_of(d: date) -> str:
    """Indian financial year label: 2026-04-01..2027-03-31 -> 'FY2026-27'."""
    y = d.year if d.month >= 4 else d.year - 1
    return f"FY{y}-{str(y + 1)[2:]}"


def _plus_12_months(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + 1, day=28)


def term(buy: date, sell: date, months: int = 12) -> str:
    """'LTCG' when held for MORE than 12 months, else 'STCG'."""
    return "LTCG" if sell > _plus_12_months(buy) else "STCG"


def match_lots(lots: List[dict], qty: int, method: str = "FIFO") -> List[dict]:
    """Pick lots to sell `qty` from. lots: [{id,qty,price,date(ISO),charges_per_share}] -> [{lot_id,qty,price,date,...}].
    FIFO = oldest first; HIFO = highest cost first (realises the smallest gain)."""
    if method not in ("FIFO", "HIFO"):
        raise TaxError("method must be FIFO or HIFO")
    key = (lambda l: (l["date"], l["id"])) if method == "FIFO" else (lambda l: (-l["price"], l["date"], l["id"]))
    need, out = qty, []
    for l in sorted((l for l in lots if l["qty"] > 0), key=key):
        take = min(need, l["qty"])
        out.append({"lot_id": l["id"], "qty": take, "price": l["price"], "date": l["date"],
                    "charges": round(take * l.get("charges_per_share", 0.0), 4)})
        need -= take
        if need == 0:
            break
    if need:
        raise TaxError(f"only {qty - need} shares available in lots, tried to sell {qty}")
    return out


def realize(matches: List[dict], sell_price: float, sell_date: date, sell_charges: float = 0.0) -> List[dict]:
    """Realised gain rows for one sale; sell charges are split across matches by quantity."""
    total = sum(m["qty"] for m in matches)
    rows = []
    for m in matches:
        buy_d = date.fromisoformat(m["date"])
        sc = sell_charges * m["qty"] / total
        gross = (sell_price - m["price"]) * m["qty"]
        rows.append({"lot_id": m["lot_id"], "qty": m["qty"], "buy_date": m["date"], "sell_date": sell_date.isoformat(),
                     "buy_price": m["price"], "sell_price": sell_price, "gross_pnl": round(gross, 2),
                     "charges": round(m["charges"] + sc, 2), "net_pnl": round(gross - m["charges"] - sc, 2),
                     "term": term(buy_d, sell_date), "fy": fy_of(sell_date)})
    return rows


def estimate_tax(realized: List[dict], fy: str, rates: dict = None) -> dict:
    """Capital-gains tax estimate for one FY from realised rows (net of charges).
    Short-term losses set off against short- and long-term gains; long-term losses only against long-term gains."""
    r = rates or load_rates()
    rows = [x for x in realized if x["fy"] == fy]
    stcg = sum(x["net_pnl"] for x in rows if x["term"] == "STCG")
    ltcg = sum(x["net_pnl"] for x in rows if x["term"] == "LTCG")
    st_taxable, lt_net = stcg, ltcg
    if st_taxable < 0 and lt_net > 0:       # short-term loss absorbs long-term gain
        used = min(-st_taxable, lt_net)
        st_taxable += used
        lt_net -= used
    st_taxable = max(st_taxable, 0.0)
    lt_taxable = max(lt_net - r["ltcg_exemption"], 0.0)
    tax = st_taxable * r["stcg_rate_pct"] / 100 + lt_taxable * r["ltcg_rate_pct"] / 100
    return {"fy": fy, "stcg_net": round(stcg, 2), "ltcg_net": round(ltcg, 2),
            "stcg_taxable": round(st_taxable, 2), "ltcg_taxable_after_exemption": round(lt_taxable, 2),
            "estimated_tax": round(tax, 2), "rates_as_of": r.get("as_of"),
            "note": "Estimate only: excludes surcharge, cess, grandfathering and other accounts. Verify rates with a CA."}


def harvest_candidates(positions: List[dict], prices: Dict[str, float], lots_by_symbol: Dict[str, List[dict]],
                       today: date, min_loss: float = 1000.0) -> List[dict]:
    """Holdings showing an unrealised loss >= min_loss (candidates to book a loss). Indian rules have no US-style
    wash-sale rule, but re-buying at once may be questioned: check with a CA. Information only."""
    out = []
    for p in positions:
        px = prices.get(p["symbol"])
        if px is None:
            continue
        loss = (px - p["avg_price"]) * p["qty"]
        if loss <= -min_loss:
            terms = {term(date.fromisoformat(l["date"]), today) for l in lots_by_symbol.get(p["symbol"], []) if l["qty"] > 0}
            out.append({"symbol": p["symbol"], "qty": p["qty"], "avg_price": p["avg_price"], "price": px,
                        "unrealised": round(loss, 2), "terms": sorted(terms)})
    return sorted(out, key=lambda r: r["unrealised"])
