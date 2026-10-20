from datetime import date, datetime

from core import alerts, calendar_in, charges, fmt
from core.calendar_in import IST
from core.models import Order


def test_inr_grouping():
    assert fmt.inr(1234567.5) == "₹12,34,567.50"
    assert fmt.inr(999) == "₹999.00"
    assert fmt.inr(-100000, 0) == "₹-1,00,000".replace("₹-", "-₹")


def test_market_status_sessions():
    h = set()
    mon = lambda hh, mm: datetime(2026, 10, 19, hh, mm, tzinfo=IST)  # Monday
    assert calendar_in.market_status(mon(9, 5), h)["status"] == "pre_open"
    assert calendar_in.market_status(mon(10, 0), h)["status"] == "open"
    assert calendar_in.market_status(mon(15, 30), h)["status"] == "closed"
    sat = datetime(2026, 10, 17, 11, 0, tzinfo=IST)
    s = calendar_in.market_status(sat, h)
    assert s["status"] == "holiday" and s["next_open"].startswith("2026-10-19T09:15")


def test_holiday_skipped_for_next_open():
    h = {date(2026, 10, 20)}
    now = datetime(2026, 10, 19, 16, 0, tzinfo=IST)
    assert calendar_in.market_status(now, h)["next_open"].startswith("2026-10-21T09:15")


def test_order_validation():
    assert Order("M&M", "BUY", 5).validate() == []
    assert Order("BAJAJ-AUTO", "SELL", 1).validate() == []
    assert Order("tcs", "BUY", 5).validate()  # lowercase
    assert Order("TCS", "BUY", 0).validate()
    assert Order("TCS", "BUY", 1.5).validate()  # fractional
    assert Order("TCS", "BUY", 1, product="MIS").validate()
    assert Order("TCS", "BUY", 1, order_type="LIMIT").validate()  # no price


def test_charges_buy_vs_sell():
    rates = {"brokerage_per_order": 0, "stt_pct_buy": 0.1, "stt_pct_sell": 0.1,
             "exchange_txn_pct": 0.00297, "sebi_pct": 0.0001, "stamp_duty_pct_buy": 0.015,
             "gst_pct": 18, "dp_charge_per_sell_scrip": 15.34}
    buy = charges.estimate("BUY", 100, 1000, rates)
    sell = charges.estimate("SELL", 100, 1000, rates)
    assert buy["stt"] == 100.0 and buy["stamp_duty"] == 15.0 and buy["dp"] == 0
    assert sell["dp"] == 15.34 and sell["stamp_duty"] == 0


def test_alert_rules():
    rules = [{"symbol": "TCS", "kind": "above", "value": 4000},
             {"symbol": "INFY", "kind": "below", "value": 1500},
             {"symbol": "ITC", "kind": "pct_move", "value": 3, "ref_price": 400},
             {"symbol": "HDFCBANK", "kind": "above", "value": 1}]
    fired = alerts.evaluate(rules, {"TCS": 4100, "INFY": 1600, "ITC": 413})
    assert [f["symbol"] for f in fired] == ["TCS", "ITC"]


def test_special_session_day_is_not_called_a_holiday():
    sun = datetime(2026, 11, 8, 18, 30, tzinfo=IST)   # Muhurat Sunday
    assert calendar_in.market_status(sun, set(), {date(2026, 11, 8)})["status"] == "special_session"
    assert calendar_in.market_status(sun, set(), set())["status"] == "holiday"


def test_real_nse_holiday_config_is_loaded():
    hs = calendar_in.load_holidays()
    assert date(2026, 1, 26) in hs and date(2026, 12, 25) in hs   # Republic Day, Christmas (NSE list)
