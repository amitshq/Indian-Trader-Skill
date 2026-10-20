from datetime import date

from fastapi.testclient import TestClient

from adapters.data.nse_results import NSEError
from adapters.data.quotes import StaticQuotes
from api.main import create_app
from core.store import Store


class FakeMarket:
    client = None

    def large_deals(self):
        return {"as_on": "2026-10-19", "bulk": [{"date": "2026-10-19", "symbol": "KROSS", "name": "Kross", "client": "A", "side": "BUY",
                                                  "qty": 1000000, "price": 300.0, "remarks": None}], "block": [], "short": []}

    def fii_dii(self):
        return [{"category": "DII", "date": "2026-10-19", "buy": 1.0, "sell": 2.0, "net": -1.0}]

    def shareholding(self, symbol):
        if symbol == "BOOM":
            raise NSEError("HTTP 403")
        return [{"as_of": "2026-09-30", "promoter_pct": 71.77, "public_pct": 28.2, "employee_trusts_pct": 0.0, "broadcast": "2026-10-13"},
                {"as_of": "2026-06-30", "promoter_pct": 72.0, "public_pct": 28.0, "employee_trusts_pct": 0.0, "broadcast": "2026-07-13"}]


def client(cash=1_000_000):
    q = StaticQuotes({"TCS": 4000.0, "ITC": 400.0, "INFY": 1500.0})
    return TestClient(create_app(Store(":memory:", cash), q, market=FakeMarket()))


def test_size_endpoint_and_queue_through_risk_gate():
    c = client()
    r = c.post("/api/size", json={"weights": {"tcs": 40, "itc": 30, "infy": 30}, "budget": 500000, "max_position_pct": 45}).json()
    assert r["invested"] <= 475000 and all(o["qty"] > 0 for o in r["orders"]) and r["price_source"] == "static"
    q = c.post("/api/size", json={"weights": {"TCS": 40, "ITC": 30, "INFY": 30}, "budget": 500000, "queue": True}).json()
    assert len(q["queued"]) == 3
    assert {x["status"] for x in q["queued"]} <= {"PENDING", "BLOCKED"}           # the gate decided, nothing filled
    assert c.get("/api/portfolio").json()["positions"] == []
    assert c.post("/api/size", json={"weights": {"TCS": 1}, "budget": 100}).status_code == 422


def test_order_response_carries_risk_verdict_and_blocks_oversize():
    c = client()
    ok = c.post("/api/orders", json={"symbol": "ITC", "side": "BUY", "qty": 50}).json()
    assert ok["risk"]["verdict"] == "PASS" and ok["mode"] == "PAPER" and ok["order"]["status"] == "PENDING"
    big = c.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "qty": 100}).json()   # 4 lakh > max order value
    assert big["order"]["status"] == "BLOCKED" and big["risk"]["verdict"] == "BLOCK"
    assert c.get("/api/risk/config").json()["max_order_value"] == 200000


def test_rebalance_and_tax_flow_end_to_end():
    c = client()
    oid = c.post("/api/orders", json={"symbol": "ITC", "side": "BUY", "qty": 100}).json()["order"]["id"]
    assert c.post(f"/api/orders/{oid}/approve").json()["status"] == "FILLED"
    lots = c.get("/api/tax/lots").json()
    assert lots[0]["qty"] == 100 and lots[0]["term"] == "STCG"
    sim = c.get("/api/tax/simulate", params={"symbol": "ITC", "qty": 40, "price": 450}).json()
    assert sim["rows"][0]["gross_pnl"] == 2000.0 and sim["estimate_if_sold"]["stcg_net"] < 2000.0
    assert c.get("/api/tax/simulate", params={"symbol": "ITC", "qty": 500, "price": 450}).status_code == 422
    rb = c.post("/api/rebalance", json={"targets": {"ITC": 50, "TCS": 50}, "band_pct": 2, "min_trade_value": 1000}).json()
    assert any(o["symbol"] == "TCS" and o["side"] == "BUY" for o in rb["orders"]) and rb["table"]["total_value"] > 0
    assert c.get("/api/tax/estimate").json()["estimated_tax"] == 0
    assert c.get("/api/tax/realized").json() == []
    assert c.get("/api/tax/harvest").json() == []


def test_market_endpoints_and_upstream_failure():
    c = client()
    d = c.get("/api/deals", params={"min_cr": 1}).json()
    assert d["as_on"] == "2026-10-19" and d["stocks"][0]["symbol"] == "KROSS" and d["stocks"][0]["buy_cr"] == 30.0
    assert c.get("/api/flows").json()[0]["category"] == "DII"
    o = c.get("/api/ownership/tcs").json()
    assert o["latest"]["promoter_holding"] == 71.77 and o["latest"]["promoter_holding_change"] == -0.23
    assert c.get("/api/ownership/BOOM").status_code == 502                       # upstream failure is reported, not hidden
    cal = c.get("/api/calendar").json()
    assert "2026-12-25" in cal["holidays"] and "2026-11-08" in cal["special_sessions"]
    assert cal["status"]["status"] in ("open", "pre_open", "closed", "holiday", "special_session")


class FakeMarket2(FakeMarket):
    class _C:
        def announcements(self, *a):
            return []
    client = _C()

    def market_state(self):
        return {"state": "Closed", "message": "Normal Market has Closed", "trade_date": "19-Oct-2026 15:30", "nifty": 22888.95, "nifty_change_pct": -1.11}


class DetailQuotes(StaticQuotes):
    def detail(self, symbols):
        return {s: {"price": p, "prev_close": p, "as_of": "2026-10-19T15:29:00+05:30"} for s, p in self.prices.items() if s in symbols}


def test_preview_explains_every_check_and_saves_nothing():
    q = DetailQuotes({"TCS": 4000.0, "ITC": 400.0})
    c = TestClient(create_app(Store(":memory:", 1_000_000), q, market=FakeMarket2()))
    ok = c.post("/api/orders/preview", json={"symbol": "itc", "side": "buy", "qty": 100}).json()
    assert ok["valid"] and ok["price"] == 400.0 and ok["value"] == 40000.0 and ok["charges"]["total"] > 0
    names = [x["name"] for x in ok["risk"]["checks"]]
    assert ok["risk"]["verdict"] == "PASS" and "Position size limit" in names and "Cash buffer kept" in names
    assert all(x["detail"] for x in ok["risk"]["checks"])                       # every check is explained in words
    big = c.post("/api/orders/preview", json={"symbol": "TCS", "side": "BUY", "qty": 400}).json()
    failed = [x for x in big["risk"]["checks"] if x["ok"] is False]
    assert big["risk"]["verdict"] == "BLOCK" and failed and "exceeds max" in failed[0]["detail"]
    bad = c.post("/api/orders/preview", json={"symbol": "ITC", "side": "BUY", "qty": 0}).json()
    assert not bad["valid"] and bad["risk"] is None
    assert c.get("/api/orders").json() == []                                    # previews never create orders
    qs = c.get("/api/quotes", params={"symbols": "TCS,NOPE"}).json()
    assert qs["prices"] == {"TCS": 4000.0} and qs["missing"] == ["NOPE"] and qs["detail"]["TCS"]["as_of"].startswith("2026-10-19")


def test_demo_endpoint_runs_a_full_dummy_money_rehearsal():
    q = DetailQuotes({"TCS": 4000.0, "ITC": 400.0, "INFY": 1500.0, "RELIANCE": 1400.0, "SBIN": 800.0, "ICICIBANK": 1300.0})
    real = Store(":memory:", 1_000_000)
    c = TestClient(create_app(real, q, market=FakeMarket2(), demo_quotes=q))
    r = c.post("/api/demo/run", json={"capital": 100000, "symbols": ["TCS", "ITC", "INFY", "RELIANCE", "SBIN", "ICICIBANK"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"]["counts"]["FAIL"] == 0 and "DUMMY money" in body["text"] and body["report"]["steps"][0]["name"] == "Exchange status"
    assert real.positions() == [] and real.list_orders() == []                  # your own paper book is untouched
    assert c.post("/api/demo/run", json={"capital": 5}).status_code == 422


class FakeSource:
    source = "NSE filings (XBRL) cross-checked with Yahoo"
    errors = {}

    def __init__(self, symbols):
        self.symbols = symbols

    def metrics(self):
        return [{"ticker": s, "name": s, "roce": 20.0, "revenue_growth_yoy": 12.0, "results_overdue": 0,
                 "data_warnings": None if s != "OLD" else "OUT OF DATE"} for s in self.symbols]


def test_stock_lookup_and_real_screen_use_the_injected_sources():
    seen = []

    def factory(kind, symbols, client):
        seen.append((kind, symbols))
        return FakeSource(symbols)
    q = DetailQuotes({"TCS": 4000.0, "OLD": 10.0})
    c = TestClient(create_app(Store(":memory:"), q, market=FakeMarket2(), source_factory=factory))
    s = c.get("/api/stock/tcs").json()
    assert s["symbol"] == "TCS" and s["quote"]["price"] == 4000.0 and s["results"]["roce"] == 20.0
    assert s["promoter"]["promoter_holding"] == 71.77 and seen[-1] == ("verified", ["TCS"])
    spec = {"rules": [{"metric": "roce", "op": ">=", "value": 15}]}
    r = c.post("/api/screen", json={"spec": spec, "source": "verified", "symbols": ["tcs", "old"]}).json()
    assert sorted(p["ticker"] for p in r["passed"]) == ["OLD", "TCS"] and r["sample_data"] is False
    assert r["data_warnings"] == {"OLD": "OUT OF DATE"} and seen[-1] == ("verified", ["TCS", "OLD"])
    sample = c.post("/api/screen", json={"spec": spec, "source": "sample"}).json()
    assert sample["sample_data"] is True and sample["source"].startswith("json:")
    assert c.post("/api/screen", json={"spec": spec, "source": "verified", "symbols": [f"S{i}" for i in range(25)]}).status_code == 422
