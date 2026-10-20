from datetime import date

import pytest

from adapters.broker.paper import PaperBroker
from adapters.data.quotes import StaticQuotes
from core import approval, rebalance, risk, sizing, tax
from core.models import Order
from core.store import Store

# ------------------------------------------------------------------ sizing


def test_cap_weights_redistributes_and_rejects_impossible_caps():
    w = sizing.cap_weights({"A": 0.7, "B": 0.2, "C": 0.1}, 0.4)
    assert w["A"] == pytest.approx(0.4) and sum(w.values()) == pytest.approx(1.0) and w["B"] > 0.2
    with pytest.raises(sizing.SizingError):
        sizing.cap_weights({"A": 0.5, "B": 0.5}, 0.4)         # 2 x 40% < 100%


def test_size_buys_whole_shares_and_budget_respected():
    r = sizing.size_buys({"TCS": 50, "ITC": 30, "INFY": 20}, {"TCS": 4000, "ITC": 400, "INFY": 1500},
                         budget=1_000_000, cash_buffer_pct=5, max_position_pct=50)
    assert all(isinstance(o["qty"], int) and o["qty"] > 0 for o in r["orders"])
    assert r["invested"] <= 950_000 and r["invested"] + r["leftover"] == pytest.approx(1_000_000)
    assert r["leftover"] >= 50_000 and r["leftover"] < 50_000 + 4000       # buffer + less than the dearest share
    assert max(o["weight_actual"] for o in r["orders"]) <= 0.5 + 1e-6


def test_size_buys_skips_unpriced_small_and_unaffordable():
    r = sizing.size_buys({"TCS": 50, "NOPRICE": 25, "PENNY": 25}, {"TCS": 4000, "PENNY": 10}, 20000, cash_buffer_pct=0,
                         min_order_value=1000)
    assert [o["symbol"] for o in r["orders"]] == ["TCS", "PENNY"] or [o["symbol"] for o in r["orders"]] == ["TCS"]
    assert ("NOPRICE", "no price") in r["skipped"]
    with pytest.raises(sizing.SizingError):
        sizing.size_buys({"TCS": 1}, {"TCS": 4000}, 1000)         # cannot afford one share
    with pytest.raises(sizing.SizingError):
        sizing.size_buys({"TCS": 1}, {"TCS": 4000}, 0)

# ------------------------------------------------------------------ risk


CFG = risk.RiskConfig(max_position_pct=25, max_order_value=100000, min_order_value=1000, cash_buffer_pct=5,
                      max_orders_per_day=3, price_band_pct=10, blocked=["BADCO"])


def verdicts(orders, cash=100000, positions=None, prices=None, **kw):
    return risk.check_orders(orders, CFG, cash=cash, positions=positions or {}, prices=prices or {"TCS": 4000, "ITC": 400, "BADCO": 100},
                             **kw)


def test_risk_pass_and_each_block_reason():
    assert verdicts([Order("TCS", "BUY", 5)])[0]["verdict"] == "PASS"            # 20000 = 20% of 100000
    cases = [(Order("BADCO", "BUY", 20), "blocked list"), (Order("TCS", "BUY", 8), "of the portfolio"),
             (Order("TCS", "BUY", 100), "exceeds max"), (Order("ITC", "BUY", 1), "below minimum"),
             (Order("ITC", "SELL", 5), "cannot sell"), (Order("TCS", "BUY", 5, order_type="LIMIT", price=5000), "from last price"),
             (Order("tcs", "BUY", 5), "bad symbol"), (Order("NOPX", "BUY", 5), "no price")]
    for o, why in cases:
        v = verdicts([o])[0]
        assert v["verdict"] == "BLOCK" and any(why in r for r in v["reasons"]), (o, v["reasons"])


def test_risk_simulates_earlier_fills_duplicates_and_daily_limit():
    # two 20% buys of different names: the second would leave cash under the 5% buffer after the first filled
    vs = verdicts([Order("TCS", "BUY", 5), Order("ITC", "BUY", 200)], cash=100000)
    assert [v["verdict"] for v in vs] == ["PASS", "BLOCK"] and any("buffer" in r for r in vs[1]["reasons"])
    dup = verdicts([Order("ITC", "BUY", 5), Order("ITC", "BUY", 5)])
    assert dup[1]["verdict"] == "BLOCK" and "duplicate" in dup[1]["reasons"][0]
    assert verdicts([Order("ITC", "BUY", 5)], orders_today=3)[0]["verdict"] == "BLOCK"
    held = {"ITC": {"qty": 10, "avg_price": 390.0}}
    assert verdicts([Order("ITC", "SELL", 10)], positions=held)[0]["verdict"] == "PASS"


def test_risk_market_closed_warns_or_blocks():
    v = verdicts([Order("TCS", "BUY", 5)], market_status="closed")[0]
    assert v["verdict"] == "PASS" and "market is closed" in v["warnings"][0]
    strict = risk.RiskConfig(**{**CFG.__dict__, "allow_when_market_closed": False})
    assert risk.check_orders([Order("TCS", "BUY", 5)], strict, cash=100000, positions={}, prices={"TCS": 4000},
                             market_status="closed")[0]["verdict"] == "BLOCK"


def test_fingerprint_changes_with_any_order_detail():
    a = risk.fingerprint(Order("TCS", "BUY", 5), "2026-10-21")
    assert a == risk.fingerprint(Order("TCS", "BUY", 5), "2026-10-21")
    for o in (Order("TCS", "BUY", 6), Order("TCS", "SELL", 5), Order("ITC", "BUY", 5), Order("TCS", "BUY", 5, order_type="LIMIT", price=1.0)):
        assert risk.fingerprint(o, "2026-10-21") != a
    assert risk.fingerprint(Order("TCS", "BUY", 5), "2026-10-22") != a

# ------------------------------------------------------------------ approval parser


@pytest.mark.parametrize("text,ok", [
    ("yes", True), ("Yes, buy 10 TCS", True), ("confirm", True), ("approve 10 shares of TCS", True),
    ("sure", False), ("yes to all", False), ("yes sell 10 TCS", False), ("yes buy 12 TCS", False),
    ("yes buy 10 INFY", False), ("ok", False), ("maybe yes", False), ("", False), ("do it", False),
    ("yes at 4000", False)])
def test_parse_yes(text, ok):
    assert approval.parse_yes(text, Order("TCS", "BUY", 10))[0] is ok

# ------------------------------------------------------------------ tax


def test_term_boundary_is_more_than_twelve_months():
    assert tax.term(date(2025, 1, 15), date(2026, 1, 15)) == "STCG"       # exactly 12 months: still short
    assert tax.term(date(2025, 1, 15), date(2026, 1, 16)) == "LTCG"
    assert tax.term(date(2024, 2, 29), date(2025, 3, 1)) == "LTCG"        # leap-day buy
    assert tax.fy_of(date(2026, 3, 31)) == "FY2025-26" and tax.fy_of(date(2026, 4, 1)) == "FY2026-27"


LOTS = [{"id": 1, "qty": 10, "price": 100.0, "date": "2024-01-10", "charges_per_share": 0.1},
        {"id": 2, "qty": 10, "price": 150.0, "date": "2025-06-01", "charges_per_share": 0.1}]


def test_match_lots_fifo_hifo_and_oversell():
    f = tax.match_lots(LOTS, 15, "FIFO")
    assert [(m["lot_id"], m["qty"]) for m in f] == [(1, 10), (2, 5)]
    h = tax.match_lots(LOTS, 15, "HIFO")
    assert [(m["lot_id"], m["qty"]) for m in h] == [(2, 10), (1, 5)]
    with pytest.raises(tax.TaxError):
        tax.match_lots(LOTS, 21)


RATES = {"stcg_rate_pct": 20, "ltcg_rate_pct": 12.5, "ltcg_exemption": 125000, "as_of": "t"}


def test_realize_and_estimate_tax_with_setoff():
    rows = tax.realize(tax.match_lots(LOTS, 20, "FIFO"), 200.0, date(2026, 3, 1), sell_charges=20.0)   # lot 2 is 9 months old
    lt = next(r for r in rows if r["lot_id"] == 1)
    st = next(r for r in rows if r["lot_id"] == 2)
    assert lt["term"] == "LTCG" and lt["gross_pnl"] == 1000.0 and lt["net_pnl"] == pytest.approx(1000 - 1 - 10)
    assert st["term"] == "STCG" and st["gross_pnl"] == 500.0 and st["fy"] == "FY2025-26"
    est = tax.estimate_tax(rows, "FY2025-26", RATES)
    assert est["stcg_net"] == pytest.approx(489.0) and est["ltcg_taxable_after_exemption"] == 0     # under the exemption
    assert est["estimated_tax"] == pytest.approx(489.0 * 0.20)
    big = [{"fy": "FY2026-27", "term": "LTCG", "net_pnl": 225000.0}, {"fy": "FY2026-27", "term": "STCG", "net_pnl": -50000.0},
           {"fy": "FY2025-26", "term": "STCG", "net_pnl": 999.0}]
    e2 = tax.estimate_tax(big, "FY2026-27", RATES)
    assert e2["ltcg_taxable_after_exemption"] == 50000.0 and e2["estimated_tax"] == pytest.approx(50000 * 0.125)  # STCL set off first
    lt_loss = tax.estimate_tax([{"fy": "F", "term": "LTCG", "net_pnl": -5000.0}, {"fy": "F", "term": "STCG", "net_pnl": 8000.0}], "F", RATES)
    assert lt_loss["estimated_tax"] == pytest.approx(8000 * 0.2)           # long-term loss cannot reduce short-term gains


def test_harvest_candidates():
    pos = [{"symbol": "A", "qty": 100, "avg_price": 100.0}, {"symbol": "B", "qty": 10, "avg_price": 100.0}]
    got = tax.harvest_candidates(pos, {"A": 80.0, "B": 99.0}, {"A": [{"qty": 100, "date": "2024-01-01"}]}, date(2026, 10, 21))
    assert [g["symbol"] for g in got] == ["A"] and got[0]["unrealised"] == -2000.0 and got[0]["terms"] == ["LTCG"]

# ------------------------------------------------------------------ rebalance


def test_rebalance_sells_first_scales_buys_and_respects_band():
    pos = [{"symbol": "TCS", "qty": 100, "avg_price": 3000.0}, {"symbol": "ITC", "qty": 100, "avg_price": 400.0}]
    prices = {"TCS": 4000.0, "ITC": 400.0, "INFY": 1500.0}
    r = rebalance.propose(pos, prices, {"TCS": 40, "ITC": 30, "INFY": 30}, cash=10000, band_pct=5, min_trade_value=1000)
    sides = [o["side"] for o in r["orders"]]
    assert sides == sorted(sides, key=lambda s: s != "SELL")                   # all sells before buys
    sell = next(o for o in r["orders"] if o["symbol"] == "TCS")
    assert sell["side"] == "SELL" and sell["qty"] > 0
    total_cash = 10000 + sum(o["value"] - o["est_charges"] for o in r["orders"] if o["side"] == "SELL")
    assert sum(o["value"] + o["est_charges"] for o in r["orders"] if o["side"] == "BUY") <= total_cash + 1e-6
    inside = rebalance.propose(pos, prices, {"TCS": 91, "ITC": 9}, cash=0, band_pct=10)
    assert inside["orders"] == []                                              # within band: nothing to do


def test_rebalance_untracked_and_min_trade():
    pos = [{"symbol": "OLD", "qty": 10, "avg_price": 100.0}, {"symbol": "TCS", "qty": 10, "avg_price": 4000.0}]
    prices = {"OLD": 100.0, "TCS": 4000.0}
    keep = rebalance.propose(pos, prices, {"TCS": 100}, cash=0, band_pct=1)
    assert all(o["symbol"] != "OLD" for o in keep["orders"])
    drop = rebalance.propose(pos, prices, {"TCS": 100}, cash=0, band_pct=1, sell_untracked=True)
    assert any(o["symbol"] == "OLD" and o["side"] == "SELL" and o["qty"] == 10 for o in drop["orders"])
    tiny = rebalance.propose(pos, prices, {"TCS": 97, "NEW": 3}, cash=0, band_pct=0.5, min_trade_value=50000)
    assert tiny["orders"] == []

# ------------------------------------------------------------------ broker integration


def broker(cash=1_000_000, day=date(2026, 10, 21), status="open", prices=None):
    store = Store(":memory:", cash)
    today = {"d": day}
    b = PaperBroker(store, StaticQuotes(prices or {"TCS": 4000.0, "ITC": 400.0}), risk_cfg=CFG, clock=lambda: today["d"],
                    market_status=lambda: status)
    return b, store, today


def test_broker_blocks_then_never_fills_blocked_orders():
    b, store, _ = broker()
    o = b.submit(Order("BADCO", "BUY", 5))
    assert o.status == "BLOCKED" and "blocked list" in o.reason
    with pytest.raises(ValueError):
        b.approve(o.id)
    assert store.positions() == []


def test_broker_rechecks_risk_at_approval_time():
    b, store, _ = broker(cash=100000)
    o1 = b.submit(Order("TCS", "BUY", 5))                 # 20% of the portfolio: passes alone
    assert o1.status == "PENDING"
    store.set_cash(10000)                                  # cash drops after the order was queued
    assert b.approve(o1.id).status == "BLOCKED"
    assert store.positions() == []


def test_broker_lots_realised_gains_term_and_tax_estimate():
    b, store, today = broker(prices={"ITC": 400.0})
    b.approve(b.submit(Order("ITC", "BUY", 100)).id)
    assert [(l["qty"], l["date"]) for l in store.list_lots("ITC")] == [(100, "2026-10-21")]
    today["d"] = date(2027, 11, 5)                          # held more than 12 months
    b.quotes.prices["ITC"] = 500.0
    s = b.approve(b.submit(Order("ITC", "SELL", 40)).id)
    assert s.status == "FILLED"
    r = store.list_realized()
    assert len(r) == 1 and r[0]["term"] == "LTCG" and r[0]["qty"] == 40 and r[0]["fy"] == "FY2027-28"
    assert r[0]["gross_pnl"] == 4000.0 and r[0]["net_pnl"] < 4000.0
    assert store.list_lots("ITC")[0]["qty"] == 60 and store.get_position("ITC")["qty"] == 60
    est = tax.estimate_tax(r, "FY2027-28", RATES)
    assert est["estimated_tax"] == 0                        # LTCG far below the exemption
