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

    def __init__(self, ticker_factory=None, ttl_seconds: float = 30.0, clock=None):
        import time
        self._factory, self._ttl, self._clock = ticker_factory, ttl_seconds, clock or time.monotonic
        self._cache = {}     # symbol -> (fetched_at, detail): a page refresh must not hit Yahoo for every symbol again

    def _ticker(self, symbol):
        if self._factory:
            return self._factory(f"{symbol}.NS")
        try:
            import yfinance as yf
        except ImportError as e:
            raise RuntimeError("pip install yfinance to use this provider") from e
        return yf.Ticker(f"{symbol}.NS")

    def detail(self, symbols):
        """-> {symbol: {price, prev_close, as_of}}. as_of is the timestamp of the last 1-minute bar when
        Yahoo has one (so you can SEE how old the price is), else None. Symbols with no data are omitted."""
        out = {}
        for s in symbols:
            hit = self._cache.get(s)
            if hit and self._clock() - hit[0] < self._ttl:
                out[s] = hit[1]
                continue
            try:
                t = self._ticker(s)
                fi = t.fast_info
                price = _first(fi, "last_price", "lastPrice")
                prev = _first(fi, "previous_close", "previousClose")
                as_of = None
                try:
                    h = t.history(period="1d", interval="1m")
                    if h is not None and len(h):
                        as_of = h.index[-1].isoformat()
                        price = price or float(h["Close"].iloc[-1])
                except Exception:
                    pass
                if price:
                    out[s] = {"price": round(float(price), 2), "prev_close": round(float(prev), 2) if prev else None, "as_of": as_of}  # NSE ticks are 0.05
                    self._cache[s] = (self._clock(), out[s])
            except Exception:
                continue
        return out

    def ltp(self, symbols):
        return {s: d["price"] for s, d in self.detail(symbols).items()}


def _first(obj, *names):
    """fast_info answers to attribute names (last_price) and camelCase keys (lastPrice); read either."""
    for n in names:
        try:
            v = getattr(obj, n)
            if v:
                return v
        except Exception:
            pass
        try:
            v = obj[n]
            if v:
                return v
        except Exception:
            pass
    return None
