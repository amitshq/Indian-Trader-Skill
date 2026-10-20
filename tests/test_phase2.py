import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.data.fundamentals import CsvMetrics, JsonFundamentals
from adapters.data.quotes import StaticQuotes
from api.main import create_app
from core import fundamentals as fnd
from core import screener
from core.store import Store

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "fixtures" / "sample_fundamentals.json"


def by_ticker():
    return {m["ticker"]: m for m in JsonFundamentals(SAMPLE).metrics()}


def test_fiscal_labels():
    assert fnd.fiscal_label("2025-12-31") == "Q3 FY26"
    assert fnd.fiscal_label("2026-03-31") == "Q4 FY26"
    assert fnd.fiscal_label("2025-06-30") == "Q1 FY26"
    with pytest.raises(ValueError):
        fnd.fiscal_label("2025-11-30")


def test_growth_margin_ttm():
    a = by_ticker()["ALPHAIND"]
    assert a["latest_quarter"] == "Q3 FY26"
    assert a["revenue_growth_yoy"] == 25.0       # 1250 vs 1000
    assert a["profit_growth_yoy"] == 37.5        # 165 vs 120
    assert a["operating_margin"] == 21.2         # 265/1250
    assert a["eps_ttm"] == 29.25                 # 6.5+7+7.5+8.25
    assert a["roce"] == 22.0


def test_derived_q4_flagged():
    b = by_ticker()["BETAFIN"]
    assert b["latest_is_derived"] is True and b["latest_quarter"] == "Q4 FY26"
    assert b["revenue_growth_yoy"] is None       # no prior-year quarter: never guessed
    assert b["eps_ttm"] is None or isinstance(b["eps_ttm"], float)
    # derived Q4: 3200-(800+820+790)=790
    q = fnd.with_derived_q4(json.loads(SAMPLE.read_text())["companies"][1]["quarters"],
                            json.loads(SAMPLE.read_text())["companies"][1]["annual"])[-1]
    assert q["revenue"] == 790 and q["derived"] is True


def test_screen_pass_fail_reasons_and_rank():
    rows = list(by_ticker().values())
    spec = json.loads((ROOT / "config" / "rules.example.json").read_text())
    res = {r["ticker"]: r for r in screener.screen(rows, spec)}
    assert res["ALPHAIND"]["passed"] and res["GAMMAFMCG"]["passed"]
    assert not res["BETAFIN"]["passed"]
    assert any("promoter_pledge 22" in f for f in res["BETAFIN"]["fails"])
    assert any("roce is missing" in f for f in res["BETAFIN"]["fails"])
    order = [r["ticker"] for r in screener.screen(rows, spec) if r["passed"]]
    assert order == ["ALPHAIND", "GAMMAFMCG"]  # profit growth (37.5% vs 14.3%) weighted 3x


def test_missing_skip_and_ops():
    rows = [{"ticker": "X", "roce": None, "sector": "FMCG"}, {"ticker": "Y", "roce": 20, "sector": "IT"}]
    skip = screener.screen(rows, {"rules": [{"metric": "roce", "op": ">", "value": 10}], "missing": "skip"})
    assert all(r["passed"] for r in skip)
    inn = screener.screen(rows, {"rules": [{"metric": "sector", "op": "in", "value": ["fmcg"]}]})
    assert [r["ticker"] for r in inn if r["passed"]] == ["X"]
    with pytest.raises(screener.ScreenError):
        screener.screen(rows, {"rules": [{"metric": "roce", "op": "~", "value": 1}]})


def test_add_prices_pe():
    rows = [{"ticker": "A", "eps_ttm": 10.0}, {"ticker": "B", "eps_ttm": -2.0}]
    screener.add_prices(rows, {"A": 200.0, "B": 50.0})
    assert rows[0]["pe"] == 20.0 and rows[0]["earnings_yield"] == 5.0
    assert "pe" not in rows[1] and rows[1]["earnings_yield"] == -4.0


def test_csv_source(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("symbol,roce,market_cap\nTCS,48.5%,\"1,400,000\"\n", encoding="utf-8")
    row = CsvMetrics(p).metrics()[0]
    assert row["ticker"] == "TCS" and row["roce"] == 48.5 and row["market_cap"] == 1400000


def test_api_screen_and_sample_flag():
    c = TestClient(create_app(Store(":memory:"), StaticQuotes({"ALPHAIND": 585.0})))
    f = c.get("/api/fundamentals").json()
    assert f["sample_data"] is True
    assert next(x for x in f["companies"] if x["ticker"] == "ALPHAIND")["pe"] == 20.0
    spec = c.get("/api/screen/example-rules").json()
    r = c.post("/api/screen", json={"spec": spec}).json()
    assert [p["ticker"] for p in r["passed"]][0] == "ALPHAIND" and r["sample_data"] is True
    bad = c.post("/api/screen", json={"spec": {"rules": [{"metric": "roce", "op": "??", "value": 1}]}})
    assert bad.status_code == 422
