"""Quote providers. QuoteProvider.ltp(symbols) -> {symbol: last price}."""
from typing import Dict, Iterable


class QuoteProvider:
    source = "base"

    def ltp(self, symbols: Iterable[str]) -> Dict[str, float]:
        raise NotImplementedError


class StaticQuotes(QuoteProvider):
    """In-memory prices for tests and offline demos."""
    source = "static"

    def __init__(self, prices: Dict[str, float] = None):
        self.prices = dict(prices or {})

    def ltp(self, symbols):
        return {s: self.prices[s] for s in symbols if s in self.prices}


class YFinanceQuotes(QuoteProvider):
    """Delayed, unofficial NSE prices via yfinance (RELIANCE -> RELIANCE.NS).
    Prototyping only: not suitable for execution decisions."""
    source = "yfinance (delayed, unofficial)"

    def ltp(self, symbols):
        try:
            import yfinance as yf
        except ImportError as e:
            raise RuntimeError("pip install yfinance to use this provider") from e
        out = {}
        for s in symbols:
            price = yf.Ticker(f"{s}.NS").fast_info.get("last_price")
            if price:
                out[s] = float(price)
        return out
