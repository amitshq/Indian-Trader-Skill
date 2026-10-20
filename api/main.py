"""FastAPI backend. Paper trading only in phase 1. Run: uvicorn api.main:app --reload"""
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from adapters.broker.paper import PaperBroker
from adapters.broker.upstox import InstrumentMap, LiveBlocked, UpstoxBroker, UpstoxClient, UpstoxError
from adapters.data.fundamentals import CsvMetrics, JsonFundamentals
from adapters.data.quotes import StaticQuotes, YFinanceQuotes
from adapters.data.yf_fundamentals import YFinanceFundamentals
from core import alerts as alert_engine
from core import calendar_in, charges, rebalance as rebal, risk as risk_mod, screener, sizing, tax
from core.models import Order
from core.store import Store


class OrderIn(BaseModel):
    symbol: str
    side: str
    qty: int
    exchange: str = "NSE"
    order_type: str = "MARKET"
    price: Optional[float] = None


class AlertIn(BaseModel):
    symbol: str
    kind: str
    value: float
    ref_price: Optional[float] = None


ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "fixtures" / "sample_fundamentals.json"


def universe_symbols():
    env = os.getenv("SYMBOLS")
    if env:
        return [s for s in env.split(",") if s.strip()]
    return json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["symbols"]


def default_fundamentals():
    mode = os.getenv("FUNDAMENTALS")
    if mode in ("live", "yahoo"):
        return YFinanceFundamentals(universe_symbols())
    if mode in ("nse", "verified"):
        from adapters.data.crosscheck import CrossCheckedFundamentals
        from adapters.data.nse_results import NSEResults
        syms = universe_symbols()
        nse = NSEResults(syms)
        return nse if mode == "nse" else CrossCheckedFundamentals(nse, YFinanceFundamentals(syms))
    p = os.getenv("FUNDAMENTALS_PATH")
    if p and p.lower().endswith(".csv"):
        return CsvMetrics(p)
    return JsonFundamentals(p or SAMPLE)


def make_broker(store, quotes):
    """PAPER unless BROKER=upstox. Live mode still needs config/live.json + INDIA_TRADER_LIVE (checked per order)."""
    if os.getenv("BROKER") != "upstox":
        return PaperBroker(store, quotes)
    import httpx
    client = UpstoxClient()
    instruments = InstrumentMap.download(lambda u: httpx.get(u, timeout=60, follow_redirects=True).content)
    b = UpstoxBroker(store, client, instruments)
    b.cash = client.funds
    return b


class ScreenIn(BaseModel):
    spec: dict


def create_app(store: Store = None, quotes=None, fundamentals=None, market=None) -> FastAPI:
    store = store or Store()
    fundamentals = fundamentals or default_fundamentals()
    quotes = quotes or (YFinanceQuotes() if os.getenv("QUOTES") == "yfinance" else StaticQuotes())
    broker = make_broker(store, quotes)
    live = bool(getattr(broker, "live", False))
    mode_name = "LIVE" if live else "PAPER"
    if live:
        quotes = broker.quotes
    _market = {}

    def get_market():
        if market is not None:
            return market
        if "m" not in _market:
            from adapters.data.nse_market import NSEMarket
            _market["m"] = NSEMarket()
        return _market["m"]
    app = FastAPI(title="india-trader", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": mode_name, "quotes": quotes.source}

    @app.get("/api/market/status")
    def market_status():
        return calendar_in.market_status()

    @app.get("/api/quotes")
    def get_quotes(symbols: str):
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        return {"source": quotes.source, "prices": quotes.ltp(syms)}

    @app.get("/api/portfolio")
    def portfolio():
        pos = store.positions()
        px = quotes.ltp([p["symbol"] for p in pos])
        rows, value = [], 0.0
        for p in pos:
            ltp = px.get(p["symbol"])
            mv = p["qty"] * ltp if ltp else None
            value += mv or 0.0
            rows.append({**p, "ltp": ltp, "market_value": mv,
                         "pnl": (ltp - p["avg_price"]) * p["qty"] if ltp else None})
        return {"mode": mode_name, "cash": broker.cash() if live else store.get_cash(), "holdings_value": value, "positions": rows}

    @app.post("/api/orders")
    def submit_order(body: OrderIn):
        o = broker.submit(Order(symbol=body.symbol.upper(), side=body.side.upper(), qty=body.qty,
                                exchange=body.exchange.upper(), order_type=body.order_type.upper(),
                                price=body.price))
        est, verdict = None, None
        px = o.price or quotes.ltp([o.symbol]).get(o.symbol)
        if o.status in ("PENDING", "BLOCKED") and px:
            est = charges.estimate(o.side, o.qty, px)
        if o.status in ("PENDING", "BLOCKED"):
            v = broker.risk_verdict(o, exclude_id=o.id)
            verdict = {"verdict": v["verdict"], "reasons": v["reasons"], "warnings": v["warnings"], "fingerprint": v["fingerprint"]}
        return {"order": o.to_dict(), "estimated_charges": est, "risk": verdict, "mode": mode_name}

    @app.get("/api/orders")
    def list_orders(status: Optional[str] = None):
        return [o.to_dict() for o in store.list_orders(status)]

    @app.post("/api/orders/{oid}/approve")
    def approve(oid: int):
        try:
            return broker.approve(oid).to_dict()
        except LiveBlocked as e:
            raise HTTPException(403, f"live order blocked, nothing sent: {e}")
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/orders/{oid}/reject")
    def reject(oid: int):
        try:
            return broker.reject(oid).to_dict()
        except KeyError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/orders/{oid}/refresh")
    def refresh(oid: int):
        if not live:
            raise HTTPException(409, "paper orders fill immediately; refresh is for live orders")
        try:
            return broker.refresh(oid).to_dict()
        except (ValueError, UpstoxError) as e:
            raise HTTPException(409, str(e))

    @app.get("/api/live/status")
    def live_status():
        from adapters.broker.upstox import ROOT as BROOT, load_live_config
        cfg = load_live_config()
        return {"mode": mode_name, "live_enabled_in_config": cfg["live_enabled"], "caps": {"max_order_value": cfg["max_order_value"],
                "max_orders_per_day": cfg["max_orders_per_day"]}, "kill_switch": (BROOT / cfg["kill_switch_file"]).exists(),
                "gate_errors": broker.gate_errors() if live else ["running in PAPER mode (start with BROKER=upstox for live)"]}

    @app.post("/api/live/kill")
    def kill_on():
        from adapters.broker.upstox import ROOT as BROOT, load_live_config
        p = BROOT / load_live_config()["kill_switch_file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stop", encoding="utf-8")
        return {"kill_switch": True}

    @app.get("/api/live/login-url")
    def live_login_url():
        if not live:
            raise HTTPException(409, "not in live mode")
        try:
            return {"url": broker.client.login_url()}
        except UpstoxError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/live/callback")
    def live_callback(code: str):
        if not live:
            raise HTTPException(409, "not in live mode")
        try:
            broker.client.exchange_code(code)   # token kept in memory only
        except UpstoxError as e:
            raise HTTPException(502, str(e))
        return {"logged_in": True, "note": "token is held in memory only and expires daily"}

    @app.post("/api/alerts")
    def add_alert(body: AlertIn):
        rule = {**body.model_dump(), "symbol": body.symbol.upper()}
        return {"id": store.add_alert(rule), **rule}

    @app.get("/api/alerts")
    def list_alerts():
        return store.list_alerts()

    @app.delete("/api/alerts/{aid}")
    def delete_alert(aid: int):
        store.delete_alert(aid)
        return {"deleted": aid}

    @app.get("/api/alerts/check")
    def check_alerts():
        rules = store.list_alerts()
        prices = quotes.ltp({r["symbol"] for r in rules})
        return {"fired": alert_engine.evaluate(rules, prices)}

    def _metrics_with_prices():
        rows = fundamentals.metrics()
        try:
            screener.add_prices(rows, quotes.ltp([r["ticker"] for r in rows]))
        except Exception:  # prices are optional for screening
            pass
        return rows

    @app.get("/api/fundamentals")
    def get_fundamentals():
        rows = _metrics_with_prices()
        return {"source": fundamentals.source, "sample_data": "sample" in fundamentals.source,
                "errors": getattr(fundamentals, "errors", {}), "companies": rows}

    @app.get("/api/screen/example-rules")
    def example_rules():
        live = not isinstance(fundamentals, JsonFundamentals) and not isinstance(fundamentals, CsvMetrics)
        name = "rules.live.example.json" if live else "rules.example.json"
        return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))

    @app.post("/api/screen")
    def run_screen(body: ScreenIn):
        try:
            results = screener.screen(_metrics_with_prices(), body.spec)
        except screener.ScreenError as e:
            raise HTTPException(422, str(e))
        top = body.spec.get("top")
        passed = [r for r in results if r["passed"]]
        return {"source": fundamentals.source, "sample_data": "sample" in fundamentals.source,
                "errors": getattr(fundamentals, "errors", {}),
                "passed": [{k: r[k] for k in ("ticker", "name", "score", "passes", "skipped")}
                           for r in (passed[:top] if top else passed)],
                "failed": [{"ticker": r["ticker"], "name": r["name"], "fails": r["fails"]}
                           for r in results if not r["passed"]],
                "note": "A filter on reported numbers, not a recommendation."}

    # ------------------------------------------------------------ planning: sizing, risk, rebalance, tax
    class SizeIn(BaseModel):
        weights: dict
        budget: float
        cash_buffer_pct: float = 5.0
        max_position_pct: float = 100.0
        min_order_value: float = 1000.0
        queue: bool = False

    class RebalanceIn(BaseModel):
        targets: dict
        band_pct: float = 5.0
        min_trade_value: float = 5000.0
        max_position_pct: float = 100.0
        sell_untracked: bool = False
        queue: bool = False

    def _queue(proposals):
        out = []
        for o in proposals:
            q = broker.submit(Order(o["symbol"], o["side"], o["qty"]))
            out.append({"id": q.id, "symbol": q.symbol, "side": q.side, "status": q.status, "reason": q.reason})
        return out

    @app.get("/api/risk/config")
    def risk_config():
        return risk_mod.RiskConfig.load().__dict__

    @app.post("/api/size")
    def size(body: SizeIn):
        w = {k.upper(): float(v) for k, v in body.weights.items()}
        try:
            res = sizing.size_buys(w, quotes.ltp(list(w)), body.budget, cash_buffer_pct=body.cash_buffer_pct,
                                   max_position_pct=body.max_position_pct, min_order_value=body.min_order_value)
        except sizing.SizingError as e:
            raise HTTPException(422, str(e))
        if body.queue:
            res["queued"] = _queue(res["orders"])
        return {**res, "price_source": quotes.source}

    @app.post("/api/rebalance")
    def rebalance_ep(body: RebalanceIn):
        pos = store.positions()
        t = {k.upper(): float(v) for k, v in body.targets.items()}
        prices = quotes.ltp(list(t) + [p["symbol"] for p in pos])
        try:
            res = rebal.propose(pos, prices, t, store.get_cash(), band_pct=body.band_pct, min_trade_value=body.min_trade_value,
                                max_position_pct=body.max_position_pct, sell_untracked=body.sell_untracked,
                                cash_buffer_pct=risk_mod.RiskConfig.load().cash_buffer_pct)
        except sizing.SizingError as e:
            raise HTTPException(422, str(e))
        if body.queue:
            res["queued"] = _queue(res["orders"])
        return {**res, "price_source": quotes.source}

    @app.get("/api/tax/lots")
    def tax_lots():
        today = date.today()
        return [{**l, "term": tax.term(date.fromisoformat(l["date"]), today)} for l in store.list_lots()]

    @app.get("/api/tax/realized")
    def tax_realized():
        return store.list_realized()

    @app.get("/api/tax/estimate")
    def tax_estimate(fy: Optional[str] = None):
        return tax.estimate_tax(store.list_realized(), fy or tax.fy_of(date.today()))

    @app.get("/api/tax/simulate")
    def tax_simulate(symbol: str, qty: int, price: float, method: str = "FIFO"):
        symbol = symbol.upper()
        try:
            rows = tax.realize(tax.match_lots(store.list_lots(symbol), qty, method),
                               price, date.today(), charges.estimate("SELL", qty, price)["total"])
        except tax.TaxError as e:
            raise HTTPException(422, str(e))
        est = tax.estimate_tax(store.list_realized() + rows, tax.fy_of(date.today()))
        return {"rows": rows, "estimate_if_sold": est}

    @app.get("/api/tax/harvest")
    def tax_harvest(min_loss: float = 1000.0):
        pos = store.positions()
        return tax.harvest_candidates(pos, quotes.ltp([p["symbol"] for p in pos]),
                                      {p["symbol"]: store.list_lots(p["symbol"]) for p in pos}, date.today(), min_loss)

    # ------------------------------------------------------------ market intelligence (NSE, rate limited)
    def _nse(fn):
        from adapters.data.nse_results import NSEError
        try:
            return fn()
        except NSEError as e:
            raise HTTPException(502, f"NSE data unavailable: {e}")

    @app.get("/api/calendar")
    def calendar():
        hs = sorted(calendar_in.load_holidays())
        return {"status": calendar_in.market_status(), "holidays": [h.isoformat() for h in hs],
                "special_sessions": sorted(d.isoformat() for d in calendar_in.load_special_sessions())}

    @app.get("/api/deals")
    def deals(min_cr: float = 10.0):
        from adapters.data.nse_market import summarize_deals
        d = _nse(lambda: get_market().large_deals())
        return {"as_on": d["as_on"], "stocks": summarize_deals(d, min_cr)}

    @app.get("/api/flows")
    def flows():
        return _nse(lambda: get_market().fii_dii())

    @app.get("/api/ownership/{symbol}")
    def ownership(symbol: str):
        from adapters.data.nse_market import promoter_signals
        hist = _nse(lambda: get_market().shareholding(symbol.upper()))
        return {"symbol": symbol.upper(), "latest": promoter_signals(hist), "history": hist[:6]}

    @app.get("/api/news/{symbol}")
    def news_ep(symbol: str, days: int = 30):
        import httpx
        from adapters.data import news as news_mod
        m = get_market()
        today = date.today()
        items, errors = news_mod.fetch_news(
            symbol.upper(), None, m.client, lambda u: httpx.get(u, timeout=20, follow_redirects=True).text,
            (today - timedelta(days=days)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y"))
        items.sort(key=lambda i: i["time"] or "", reverse=True)
        return {"symbol": symbol.upper(), "items": items, "errors": errors}

    # demo helper so the UI works offline with static quotes
    if isinstance(quotes, StaticQuotes):
        @app.put("/api/dev/quotes")
        def set_quotes(prices: dict):
            quotes.prices.update({k.upper(): float(v) for k, v in prices.items()})
            return quotes.prices

    return app


app = create_app()
