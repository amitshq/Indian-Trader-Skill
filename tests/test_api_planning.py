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
