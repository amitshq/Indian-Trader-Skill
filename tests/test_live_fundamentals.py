"""Offline tests for the yfinance fundamentals adapter (fake Ticker, no network)."""
from datetime import date

import pandas as pd
import pytest

from adapters.data import yf_fundamentals as yf_f
from adapters.data.yf_fundamentals import YFinanceFundamentals, build_company
from core import fundamentals as fnd

CR = 1e7  # rupees per crore


def quarterly():
    return {
        "2025-06-30": {"Total Revenue": 1000 * CR, "Operating Income": 200 * CR, "Net Income": 120 * CR, "Diluted EPS": 6.0},
        "2025-09-30": {"Total Revenue": 1100 * CR, "Operating Income": 220 * CR, "Net Income": 130 * CR, "Diluted EPS": 6.5},
        "2025-12-31": {"Total Revenue": 1200 * CR, "Operating Income": 240 * CR, "Net Income": 140 * CR, "Diluted EPS": 7.0},
        "2026-03-31": {"Total Revenue": 1300 * CR, "Operating Income": 260 * CR, "Net Income": 150 * CR, "Diluted EPS": 7.5},
        "2026-06-30": {"Total Revenue": 1250 * CR, "Operating Income": 250 * CR, "Net Income": 156 * CR, "Diluted EPS": float("nan"), "Basic EPS": 7.8},
        "2026-05-15": {"Total Revenue": 1.0},  # not a quarter end: ignored
    }


ANNUAL = {"2026-03-31": {"Total Revenue": 4600 * CR, "Net Income": 540 * CR, "Diluted EPS": 27.0, "EBIT": 800 * CR}}
BALANCE = {"2026-03-31": {"Total Debt": 500 * CR, "Stockholders Equity": 2000 * CR,
                          "Total Assets": 3500 * CR, "Current Liabilities": 1000 * CR}}
INFO = {"longName": "Test Co Ltd", "sector": "Technology", "heldPercentInsiders": 0.55, "returnOnEquity": 0.5}


def test_build_company_units_and_ratios():
    c = build_company("test", quarterly(), ANNUAL, BALANCE, INFO)
    assert c["symbol"] == "TEST" and len(c["quarters"]) == 5   # non-quarter-end dropped
    assert c["quarters"][0]["revenue"] == 1000.0               # rupees -> crore
    assert c["quarters"][-1]["eps"] == 7.8                     # NaN diluted falls back to basic
    assert c["annual"] == [{"fy": 2026, "revenue": 4600.0, "operating_profit": None,
                            "net_profit": 540.0, "eps": 27.0}]
    r = c["ratios"]
    assert r["debt_to_equity"] == 0.25 and r["roe"] == 27.0    # computed, not Yahoo's 50%
    assert r["roce"] == 32.0                                   # 800 / (3500-1000)
    assert r["insider_holding"] == 55.0
    assert "promoter_pledge" not in r and "promoter_holding" not in r


def test_metrics_from_built_company():
    m = fnd.metrics_for(build_company("TEST", quarterly(), ANNUAL, BALANCE, INFO))
    assert m["latest_quarter"] == "Q1 FY27"
    assert m["revenue_growth_yoy"] == 25.0          # 1250 vs 1000 a year earlier
    assert m["profit_growth_yoy"] == 30.0           # 156 vs 120
    assert m["eps_ttm"] == pytest.approx(6.5 + 7.0 + 7.5 + 7.8)   # last 4 consecutive: Sep25..Jun26


def test_ttm_skipped_when_quarter_missing():
    q = quarterly()
    del q["2025-12-31"]
    m = fnd.metrics_for(build_company("TEST", q, ANNUAL, BALANCE, INFO))
    assert "eps_ttm" not in m                         # gap -> no misleading TTM


def test_sparse_company_has_missing_not_guessed():
    c = build_company("BANK", {"2026-06-30": {"Net Income": 100 * CR, "Total Revenue": 500 * CR}}, {}, {}, {})
    m = fnd.metrics_for(c)
    assert m["net_margin"] == 20.0 and m.get("roce") is None and m.get("operating_margin") is None


def test_duplicate_quarter_rows_dropped_with_warning():
    q = quarterly()
    q["2025-12-31"] = dict(q["2025-06-30"])  # same figures repeated under another date (seen on a real feed)
    m = fnd.metrics_for(build_company("TEST", q, ANNUAL, BALANCE, INFO), today=date(2026, 7, 20))
    assert "2025-06-30" in m["data_warnings"] and "2025-12-31" in m["data_warnings"]
    assert "eps_ttm" not in m                         # dropped rows break the 4 consecutive quarters
    assert m["revenue_growth_yoy"] is None            # year-ago quarter was dropped, so no YoY guess


def test_overdue_results_flagged():
    c = build_company("TEST", {"2025-06-30": {"Total Revenue": 100 * CR, "Net Income": 10 * CR}}, {}, {}, {})
    stale = fnd.metrics_for(c, today=date(2026, 10, 20))
    fresh = fnd.metrics_for(c, today=date(2025, 8, 1))
    assert stale["results_overdue"] == 1 and "were due by 2025-11-14" in stale["data_warnings"]
    assert fresh["results_overdue"] == 0 and fresh["data_warnings"] is None
    # boundary: Sep-quarter results are due 14 Nov; not overdue on the day, overdue the day after
    assert fnd.metrics_for(c, today=date(2025, 11, 14))["results_overdue"] == 0
    assert fnd.metrics_for(c, today=date(2025, 11, 15))["results_overdue"] == 1


def test_next_results_due_dates():
    assert fnd.next_results_due(date(2026, 6, 30)) == date(2026, 11, 14)   # Sep qtr
    assert fnd.next_results_due(date(2026, 9, 30)) == date(2027, 2, 14)    # Dec qtr
    assert fnd.next_results_due(date(2025, 12, 31)) == date(2026, 5, 30)   # Mar qtr: 60 days
    assert fnd.next_results_due(date(2026, 3, 31)) == date(2026, 8, 14)    # Jun qtr


class FakeTicker:
    calls = 0

    def __init__(self, sym):
        FakeTicker.calls += 1
        self.sym = sym
        cols = pd.to_datetime(list(quarterly())[:5])
        rows = {k: [quarterly()[d.strftime("%Y-%m-%d")].get(k) for d in cols]
                for k in ("Total Revenue", "Operating Income", "Net Income", "Diluted EPS")}
        self.quarterly_income_stmt = pd.DataFrame(rows, index=cols).T
        self.income_stmt = pd.DataFrame({pd.Timestamp("2026-03-31"): ANNUAL["2026-03-31"]})
        self.balance_sheet = pd.DataFrame({pd.Timestamp("2026-03-31"): BALANCE["2026-03-31"]})
        self.info = INFO


class BrokenTicker:
    def __init__(self, sym):
        raise ConnectionError("network down")


def test_fetch_cache_and_ttl(tmp_path):
    FakeTicker.calls = 0
    src = YFinanceFundamentals(["TEST"], cache_dir=tmp_path, ticker_factory=FakeTicker, pause=0)
    rows = src.metrics()
    assert rows[0]["ticker"] == "TEST" and rows[0]["data_source"] == "yfinance" and rows[0]["roce"] == 32.0
    src.metrics()
    assert FakeTicker.calls == 1                      # second call served from cache
    expired = YFinanceFundamentals(["TEST"], cache_dir=tmp_path, ticker_factory=FakeTicker, ttl_hours=0, pause=0)
    expired.metrics()
    assert FakeTicker.calls == 2


def test_stale_cache_used_and_flagged_when_network_fails(tmp_path):
    YFinanceFundamentals(["TEST"], cache_dir=tmp_path, ticker_factory=FakeTicker, pause=0).metrics()
    down = YFinanceFundamentals(["TEST"], cache_dir=tmp_path, ticker_factory=BrokenTicker, ttl_hours=0, pause=0)
    rows = down.metrics()
    assert rows[0]["stale"] is True and "TEST" in down.errors


def test_failure_without_cache_reports_error(tmp_path):
    src = YFinanceFundamentals(["NOPE", "M&M"], cache_dir=tmp_path, ticker_factory=BrokenTicker, pause=0)
    assert src.metrics() == [] and set(src.errors) == {"NOPE", "M&M"}
    assert src._cache_path("M&M").name == "M_AND_M.json"
