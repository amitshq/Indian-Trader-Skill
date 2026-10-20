"""Live fundamentals for NSE stocks via yfinance (unofficial, Yahoo-sourced; prototyping grade).

What it gives: up to ~5 recent quarters, up to 4 annual statements, balance sheet ratios.
What it does NOT give: promoter pledge, true promoter holding (only Yahoo's "insider" share),
standalone-vs-consolidated flag, long history. Rules that need those metrics will show them as
missing rather than guessed. Amounts are converted from rupees to INR crore.

Always check a couple of numbers against the company's exchange filing before trusting a screen.
"""
import json
import math
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core import fundamentals as fnd

from .fundamentals import FundamentalsSource

CRORE = 1e7
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "fundamentals"
Q_FIELDS = {"revenue": ("Total Revenue",), "operating_profit": ("Operating Income",),
            "net_profit": ("Net Income",), "eps": ("Diluted EPS", "Basic EPS")}


def _clean(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _pick(col: dict, names) -> Optional[float]:
    for n in names:
        v = _clean(col.get(n))
        if v is not None:
            return v
    return None


def _crore(v):
    return None if v is None else round(v / CRORE, 2)


def build_company(symbol: str, quarterly: Dict[str, dict], annual: Dict[str, dict],
                  balance: Dict[str, dict], info: dict) -> dict:
    """Pure function: plain dicts ({'YYYY-MM-DD': {line item: value}}) -> company dict for
    core.fundamentals.metrics_for. Testable offline."""
    quarters = []
    for d, col in sorted(quarterly.items()):
        if date.fromisoformat(d).month not in fnd.Q_END_MONTHS:
            continue
        row = {"period_end": d}
        for k, names in Q_FIELDS.items():
            v = _pick(col, names)
            row[k] = v if k == "eps" else _crore(v)
        if row.get("revenue") is not None or row.get("net_profit") is not None:
            quarters.append(row)

    annual_rows = []
    for d, col in sorted(annual.items()):
        dt = date.fromisoformat(d)
        row = {"fy": dt.year + 1 if dt.month > 3 else dt.year}
        for k, names in Q_FIELDS.items():
            v = _pick(col, names)
            row[k] = v if k == "eps" else _crore(v)
        annual_rows.append(row)

    ratios = {}
    if balance and annual:
        bd = max(balance)  # latest balance sheet date
        b, ad = balance[bd], max(annual)
        a = annual[ad]
        debt, equity = _clean(b.get("Total Debt")), _clean(b.get("Stockholders Equity"))
        ta, cl = _clean(b.get("Total Assets")), _clean(b.get("Current Liabilities"))
        ebit, ni = _clean(a.get("EBIT")), _clean(a.get("Net Income"))
        if debt is not None and equity and equity > 0:
            ratios["debt_to_equity"] = round(debt / equity, 2)
        if ni is not None and equity and equity > 0:
            ratios["roe"] = round(ni / equity * 100, 2)
        if ebit is not None and ta and cl is not None and ta - cl > 0:
            ratios["roce"] = round(ebit / (ta - cl) * 100, 2)
    if "roe" not in ratios and _clean(info.get("returnOnEquity")) is not None:
        ratios["roe"] = round(info["returnOnEquity"] * 100, 2)
    insider = _clean(info.get("heldPercentInsiders"))
    if insider is not None:
        ratios["insider_holding"] = round(insider * 100, 2)  # Yahoo "insiders", not SEBI promoter

    return {"symbol": symbol.upper(), "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"), "consolidated": None,
            "quarters": quarters, "annual": annual_rows, "ratios": ratios}


def _frame_to_dict(df) -> Dict[str, dict]:
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for col in df.columns:
        key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        out[key] = {str(i): v for i, v in df[col].items()}
    return out


def fetch_raw(symbol: str, ticker_factory: Optional[Callable] = None) -> dict:
    """Network call: one yfinance Ticker -> plain dicts."""
    if ticker_factory is None:
        try:
            import yfinance as yf
        except ImportError as e:
            raise RuntimeError("pip install yfinance for live fundamentals") from e
        ticker_factory = yf.Ticker
    t = ticker_factory(f"{symbol}.NS")
    return {"quarterly": _frame_to_dict(t.quarterly_income_stmt),
            "annual": _frame_to_dict(t.income_stmt),
            "balance": _frame_to_dict(t.balance_sheet),
            "info": dict(t.info or {})}


class YFinanceFundamentals(FundamentalsSource):
    source = "yfinance (live, unofficial)"

    def __init__(self, symbols: List[str], cache_dir: Path = CACHE_DIR, ttl_hours: float = 24,
                 ticker_factory: Optional[Callable] = None, pause: float = 0.5):
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.cache_dir, self.ttl, self.factory, self.pause = Path(cache_dir), ttl_hours * 3600, ticker_factory, pause
        self.errors: Dict[str, str] = {}

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / (symbol.replace("&", "_AND_") + ".json")

    def company(self, symbol: str) -> Optional[dict]:
        p = self._cache_path(symbol)
        if p.exists():
            cached = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - cached["fetched_ts"] < self.ttl:
                return cached["company"]
        try:
            raw = fetch_raw(symbol, self.factory)
            comp = build_company(symbol, raw["quarterly"], raw["annual"], raw["balance"], raw["info"])
        except Exception as e:  # network / delisted / rate limited
            self.errors[symbol] = f"{type(e).__name__}: {e}"
            if p.exists():  # stale cache beats nothing, but say so
                cached = json.loads(p.read_text(encoding="utf-8"))
                cached["company"]["meta"] = {**cached["company"].get("meta", {}), "stale": True}
                return cached["company"]
            return None
        if not comp["quarters"]:
            self.errors[symbol] = "no quarterly results returned"
            return None
        now = datetime.now(timezone.utc)
        comp["meta"] = {"data_source": "yfinance", "fetched_at": now.isoformat(timespec="seconds")}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"fetched_ts": now.timestamp(), "company": comp}), encoding="utf-8")
        if self.pause:
            time.sleep(self.pause)
        return comp

    def metrics(self):
        rows = []
        for s in self.symbols:
            c = self.company(s)
            if c:
                rows.append(fnd.metrics_for(c))
        return rows
