from fastapi.testclient import TestClient

from adapters.data.quotes import StaticQuotes
from api.main import create_app
from core.store import Store


def client(cash=100000):
    q = StaticQuotes({"TCS": 4000.0, "ITC": 400.0})
    return TestClient(create_app(Store(":memory:", cash), q))


def test_submit_does_not_fill_until_approved():
    c = client()
    r = c.post("/api/orders", json={"symbol": "tcs", "side": "buy", "qty": 5}).json()
    assert r["order"]["status"] == "PENDING" and r["estimated_charges"]["total"] > 0
    assert c.get("/api/portfolio").json()["positions"] == []
    f = c.post(f"/api/orders/{r['order']['id']}/approve").json()
    assert f["status"] == "FILLED" and f["fill_price"] == 4000.0
    p = c.get("/api/portfolio").json()
    assert p["positions"][0]["qty"] == 5 and p["cash"] < 100000 - 20000


def test_cannot_approve_twice_or_oversell():
    c = client()
    oid = c.post("/api/orders", json={"symbol": "ITC", "side": "BUY", "qty": 10}).json()["order"]["id"]
    c.post(f"/api/orders/{oid}/approve")
    assert c.post(f"/api/orders/{oid}/approve").status_code == 409
    sold = c.post("/api/orders", json={"symbol": "ITC", "side": "SELL", "qty": 11}).json()["order"]
    assert sold["status"] == "BLOCKED" and "holding 10" in sold["reason"]      # the risk gate stops it before the queue
    assert c.post(f"/api/orders/{sold['id']}/approve").status_code == 409     # a blocked order can never be approved


def test_insufficient_cash_and_invalid_order():
    c = client(cash=1000)
    o = c.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "qty": 5}).json()["order"]
    assert o["status"] == "BLOCKED" and "buffer" in o["reason"]
    bad = c.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "qty": 0}).json()
    assert bad["order"]["status"] == "REJECTED"


def test_reject_and_alert_flow():
    c = client()
    oid = c.post("/api/orders", json={"symbol": "TCS", "side": "BUY", "qty": 1}).json()["order"]["id"]
    assert c.post(f"/api/orders/{oid}/reject").json()["status"] == "REJECTED"
    c.post("/api/alerts", json={"symbol": "tcs", "kind": "above", "value": 3900})
    assert len(c.get("/api/alerts/check").json()["fired"]) == 1
    assert c.get("/api/market/status").json()["status"] in ("open", "pre_open", "closed", "holiday")
