"""Upstox adapter tests against a FAKE transport. The real Upstox API was never called."""
import json
from datetime import date

import pytest

from adapters.broker.upstox import (LIVE_PHRASE, InstrumentMap, LiveBlocked, UpstoxBroker, UpstoxClient, UpstoxError)
from core import risk
from core.models import Order
from core.store import Store

CSV = """instrument_key,exchange_token,tradingsymbol,name,instrument_type,exchange
NSE_EQ|INE467B01029,11536,TCS,TATA CONSULTANCY SERV LT,EQUITY,NSE_EQ
NSE_EQ|INE154A01025,1660,ITC,ITC LTD,EQUITY,NSE_EQ
NSE_EQ|INE002A01018,2885,RELIANCE,RELIANCE INDUSTRIES LTD,EQUITY,NSE_EQ
NSE_FO|12345,12345,TCS26NOVFUT,TCS FUT,FUTSTK,NSE_FO
BSE_EQ|500325,500325,RELIANCE,RELIANCE BSE,EQUITY,BSE_EQ
"""


class R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        if isinstance(self._b, Exception):
            raise self._b
        return self._b


class FakeHttp:
    """routes: {(METHOD, path_suffix): body or callable(kwargs)->(code, body)}."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, suffix), body in self.routes.items():
            if m == method and url.endswith(suffix):
                code, b = body(kw) if callable(body) else (200, body)
                return R(code, b)
        raise AssertionError(f"unexpected {method} {url}")

    def placed(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/order/place")]


def ok(data):
    return {"status": "success", "data": data}


def routes(funds=100000.0, holdings=(), ltp=None, place_id="2610210001"):
    ltp = ltp or {"NSE_EQ|INE467B01029": 4000.0, "NSE_EQ|INE154A01025": 400.0}
    return {("GET", "/user/get-funds-and-margin"): ok({"equity": {"available_margin": funds}}),
            ("GET", "/portfolio/long-term-holdings"): ok(list(holdings)),
            ("GET", "/market-quote/ltp"): ok({k.replace("|", ":"): {"instrument_token": k, "last_price": v} for k, v in ltp.items()}),
            ("POST", "/order/place"): ok({"order_id": place_id}),
            ("GET", "/order/details"): ok({"status": "complete", "average_price": 4001.5})}


def make(tmp_path, *, enabled=True, env_ok=True, token="SECRET-ACCESS-TOKEN-123", http=None, cfg=None, **kw):
    http = http or FakeHttp(routes(**kw))
    client = UpstoxClient(token=token, http=http)
    live_cfg = {"live_enabled": enabled, "max_order_value": 10000, "max_orders_per_day": 5,
                "kill_switch_file": str(tmp_path / "KILL"), **(cfg or {})}
    store = Store(":memory:")
    b = UpstoxBroker(store, client, InstrumentMap.from_csv_text(CSV), risk_cfg=risk.RiskConfig(max_position_pct=100, cash_buffer_pct=0, max_order_value=1e9),
                     live_cfg=live_cfg, audit_path=tmp_path / "audit.jsonl",
                     env={"INDIA_TRADER_LIVE": LIVE_PHRASE} if env_ok else {}, clock=lambda: date(2026, 10, 21))
    return b, store, http


def audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_instrument_map_only_nse_equity():
    m = InstrumentMap.from_csv_text(CSV)
    assert m.key("tcs") == "NSE_EQ|INE467B01029" and m.key("RELIANCE") == "NSE_EQ|INE002A01018"   # NSE row, not BSE
    with pytest.raises(UpstoxError, match="no Upstox instrument"):
        m.key("TCS26NOVFUT")


def test_client_errors_login_and_token_exchange():
    c = UpstoxClient(token=None, http=FakeHttp({}), api_key="K", api_secret="S", redirect_uri="http://localhost:8000/api/live/callback")
    assert "client_id=K" in c.login_url() and "response_type=code" in c.login_url()
    with pytest.raises(UpstoxError, match="no access token"):
        c.funds()
    ex = UpstoxClient(http=FakeHttp({("POST", "/login/authorization/token"): lambda kw: (200, {"access_token": "T1"})}),
                      api_key="K", api_secret="S", redirect_uri="http://x")
    assert ex.exchange_code("abc") == "T1" and ex.token == "T1"
    bad = UpstoxClient(token="t", http=FakeHttp({("GET", "/user/get-funds-and-margin"): lambda kw: (401, {"status": "error", "errors": [{"message": "Invalid token"}]})}))
    with pytest.raises(UpstoxError, match="Invalid token"):
        bad.funds()
    html = UpstoxClient(token="t", http=FakeHttp({("GET", "/user/get-funds-and-margin"): lambda kw: (502, ValueError("x"))}))
    with pytest.raises(UpstoxError, match="not JSON"):
        html.funds()


@pytest.mark.parametrize("kwargs,why", [
    ({"enabled": False}, "disabled in config"), ({"env_ok": False}, "INDIA_TRADER_LIVE"), ({"token": None}, "not logged in")])
def test_gates_stop_orders_and_nothing_is_sent(tmp_path, kwargs, why):
    b, store, http = make(tmp_path, **kwargs)
    o = b.submit(Order("ITC", "BUY", 5))                # queueing is allowed; sending is not
    assert o.status in ("PENDING", "REJECTED")
    if o.status == "PENDING":
        with pytest.raises(LiveBlocked, match=why):
            b.approve(o.id)
    assert http.placed() == []
    assert any(e["event"] == "blocked" for e in audit(tmp_path)) or o.status == "REJECTED"


def test_kill_switch_cap_daily_limit_and_risk_gate(tmp_path):
    b, store, http = make(tmp_path)
    o = b.submit(Order("ITC", "BUY", 5))                 # 2,000
    (tmp_path / "KILL").write_text("stop")
    with pytest.raises(LiveBlocked, match="kill switch"):
        b.approve(o.id)
    (tmp_path / "KILL").unlink()
    big = b.submit(Order("TCS", "BUY", 3))               # 12,000 > live cap 10,000
    with pytest.raises(LiveBlocked, match="live cap"):
        b.approve(big.id)
    b2, _, http2 = make(tmp_path, cfg={"max_orders_per_day": 0})
    o2 = b2.submit(Order("ITC", "BUY", 5))
    with pytest.raises(LiveBlocked, match="daily order cap"):
        b2.approve(o2.id)
    poor, _, http3 = make(tmp_path, funds=500.0)         # broker only has Rs 500
    blocked = poor.submit(Order("ITC", "BUY", 5))
    assert blocked.status == "BLOCKED"
    assert http.placed() == [] and http2.placed() == [] and http3.placed() == []


def test_happy_path_sends_one_delivery_order_and_audits(tmp_path):
    b, store, http = make(tmp_path)
    o = b.submit(Order("ITC", "BUY", 5))
    assert o.status == "PENDING"
    sent = b.approve(o.id)
    assert sent.status == "SENT" and sent.reason == "upstox order id 2610210001"
    (call,) = http.placed()
    p = call[2]["json"]
    assert p["instrument_token"] == "NSE_EQ|INE154A01025" and p["product"] == "D" and p["transaction_type"] == "BUY"
    assert p["quantity"] == 5 and p["order_type"] == "MARKET" and p["price"] == 0 and p["tag"] == f"it{o.id}"
    assert call[2]["headers"]["Authorization"] == "Bearer SECRET-ACCESS-TOKEN-123"
    with pytest.raises(ValueError):
        b.approve(o.id)                                   # cannot send the same order twice
    assert len(http.placed()) == 1
    events = [e["event"] for e in audit(tmp_path)]
    assert events == ["place_attempt", "sent"]
    assert "SECRET-ACCESS-TOKEN-123" not in (tmp_path / "audit.jsonl").read_text()   # secrets never reach the audit log
    http.routes[("GET", "/order/details")] = ok({"status": "complete", "average_price": 401.5})
    done = b.refresh(o.id)
    assert done.status == "FILLED" and done.fill_price == 401.5


def test_broker_rejection_and_unknown_symbol(tmp_path):
    http = FakeHttp({**routes(), ("POST", "/order/place"): lambda kw: (400, {"status": "error", "errors": [{"message": "Insufficient funds"}]})})
    b, store, _ = make(tmp_path, http=http)
    o = b.submit(Order("ITC", "BUY", 5))
    r = b.approve(o.id)
    assert r.status == "REJECTED" and "Insufficient funds" in r.reason
    bad = b.submit(Order("NOSUCH", "BUY", 1))
    assert bad.status == "REJECTED" and "no Upstox instrument" in bad.reason
    http.routes[("GET", "/order/details")] = ok({"status": "rejected", "status_message": "RMS: margin"})


def test_amo_flag_when_market_closed(tmp_path):
    b, store, http = make(tmp_path)
    b.market_status = lambda: "closed"
    o = b.submit(Order("ITC", "BUY", 5))
    b.approve(o.id)
    assert http.placed()[0][2]["json"]["is_amo"] is True
