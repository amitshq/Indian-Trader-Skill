from datetime import datetime, timedelta

from adapters.broker.paper import PaperBroker
from adapters.data.quotes import StaticQuotes
from core import calendar_in, demo
from core.store import Store

IST = calendar_in.IST
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=IST)          # a Wednesday, market open


class Q:
    """Stands in for YFinanceQuotes.detail."""
    def __init__(self, data, later=None):
        self.data, self.later, self.calls = data, later, 0

    def detail(self, symbols):
        self.calls += 1
        src = self.later if (self.later and self.calls > 1) else self.data
        return {s: src[s] for s in symbols if s in src}


def px(price, prev, minutes_old=1):
    return {"price": price, "prev_close": prev, "as_of": (NOW - timedelta(minutes=minutes_old)).isoformat()}


DATA = {"TCS": px(4000.0, 3950.0), "ITC": px(400.0, 405.0), "INFY": px(1500.0, 1490.0), "RELIANCE": px(1400.0, 1390.0), "SBIN": px(800.0, 790.0)}
OPEN = lambda: {"state": "Open", "message": "Normal Market is Open", "trade_date": "21-Oct-2026 09:30", "nifty": 23000, "nifty_change_pct": 0.2}


def run(quotes=None, state=OPEN, screen=lambda syms: [], **kw):
    store = Store(":memory:", 100000.0)
    syms = kw.pop("symbols", ["TCS", "ITC", "INFY", "RELIANCE", "SBIN"])
    rep = demo.run_demo(quotes=quotes or Q(DATA), store=store,
                        broker_factory=lambda prices: PaperBroker(store, StaticQuotes(prices), market_status=lambda: "open"),
                        symbols=syms, capital=100000.0, market_state=state, screen=screen, now=lambda: NOW, **kw)
    return rep, store


def step(rep, name):
    return next(s for s in rep["steps"] if s.name.startswith(name))


def test_full_run_on_open_market_with_fresh_prices():
    rep, store = run(intel={"Flows": lambda: ("ok", ["DII +1"])})
    assert rep["counts"]["FAIL"] == 0 and not rep["aborted"]
    assert step(rep, "Exchange status").status == demo.OK and step(rep, "Quotes").status == demo.OK
    assert step(rep, "Screen").status == demo.WARN                       # nothing passed -> fallback basket, said out loud
    assert "arbitrary equal weights" in step(rep, "Basket").summary
    assert step(rep, "Approval").status == demo.OK and "YOU approve" in step(rep, "Approval").summary
    assert 0 < len(rep["positions"]) <= 5 and rep["cash_left"] < 100000.0 and rep["estimated_charges_paid"] > 0
    assert any(o["side"] == "SELL" and o["status"] == "FILLED" for o in rep["orders"])
    assert store.list_realized() and step(rep, "Sell").status == demo.OK
    text = demo.render(rep)
    assert "DUMMY money" in text and "Not investment advice" in text and "SIMULATED" in text


def test_closed_market_and_old_prices_are_called_last_close():
    old = {k: px(v["price"], v["prev_close"], minutes_old=900) for k, v in DATA.items()}
    rep, _ = run(quotes=Q(old), state=lambda: {"state": "Closed", "message": "Normal Market has Closed", "trade_date": "19-Oct", "nifty": 1, "nifty_change_pct": 0})
    q = step(rep, "Quotes")
    assert q.status == demo.WARN and "LAST-CLOSE" in q.summary and "900 min old" in "\n".join(q.lines)


def test_nse_and_our_calendar_disagreeing_is_flagged():
    rep, _ = run(state=lambda: {"state": "Closed", "message": "x", "trade_date": "d", "nifty": 1, "nifty_change_pct": 0})
    assert step(rep, "Exchange status").status == demo.WARN and "disagree" in "\n".join(step(rep, "Exchange status").lines)
    rep2, _ = run(state=lambda: (_ for _ in ()).throw(RuntimeError("403")))
    assert step(rep2, "Exchange status").status == demo.WARN and "could not read" in step(rep2, "Exchange status").summary


def test_no_quotes_aborts_without_trading():
    rep, store = run(quotes=Q({}))
    assert rep["aborted"] and rep["counts"]["FAIL"] == 1 and store.positions() == [] and rep["orders"] == []


def test_missing_symbol_dropped_and_screen_passes_are_used():
    scr = lambda syms: [{"ticker": "TCS", "passed": True, "score": 1.0, "fails": []}, {"ticker": "ITC", "passed": False, "score": None, "fails": ["roce is missing"]}]
    rep, _ = run(symbols=["TCS", "ITC", "NOPRICE"], screen=scr)
    assert "missing: NOPRICE" in step(rep, "Quotes").summary
    assert step(rep, "Screen").status == demo.OK and step(rep, "Basket").summary.startswith("1 stocks from stocks that passed")
    assert [p["symbol"] for p in rep["positions"]] == ["TCS"]


def test_crashing_screen_and_intel_do_not_stop_the_run():
    def boom(syms):
        raise ValueError("nse down")
    rep, _ = run(screen=boom, intel={"News": lambda: (_ for _ in ()).throw(OSError("offline"))})
    assert step(rep, "Screen").status == demo.FAIL and step(rep, "News").status == demo.WARN
    assert step(rep, "Approval").status == demo.OK                      # the trading path still ran


def test_holding_period_remarks_prices_and_uses_them():
    later = {k: px(v["price"] * 1.01, v["prev_close"]) for k, v in DATA.items()}
    waited = []
    rep, store = run(quotes=Q(DATA, later=later), hold_minutes=10, sleep=lambda s: waited.append(s))
    assert waited == [600.0] and step(rep, "Mark to market").status == demo.OK
    assert "unrealised P&L Rs " in step(rep, "Mark to market").summary and "-" not in step(rep, "Mark to market").summary.split("Rs ")[1][:1]
    sold = next(o for o in rep["orders"] if o["side"] == "SELL")
    assert sold["fill_price"] == round(DATA[sold["symbol"]]["price"] * 1.01, 2) or abs(sold["fill_price"] - DATA[sold["symbol"]]["price"] * 1.01) < 0.01   # sale used the refreshed price


def test_skipped_screen_is_reported_as_skipped_not_zero_of_zero():
    rep, _ = run(screen=lambda syms: None)
    s = step(rep, "Screen")
    assert s.status == demo.SKIP and "skipped" in s.summary and "0 of 0" not in s.summary
    assert "screen skipped" in step(rep, "Basket").summary and rep["counts"]["FAIL"] == 0
