"""Offline tests for the NSE filings adapter and the cross-check (no network)."""
from datetime import date
from pathlib import Path

import pytest

from adapters.data import nse_results as nse
from adapters.data.crosscheck import CrossCheckedFundamentals, compare_quarters
from adapters.data.nse_results import NSEClient, NSEError, NSEResults, parse_xbrl, pick_filings
from core import fundamentals as fnd

FIX = Path(__file__).resolve().parent.parent / "fixtures"
ITC_XML = (FIX / "nse_itc_q3fy25.xml").read_text(encoding="utf-8")  # real public filing, Q3 FY25 consolidated


def test_parse_real_filing_matches_published_figures():
    p = parse_xbrl(ITC_XML)
    assert p["symbol"] == "ITC" and p["nature"] == "Consolidated" and p["audited"] == "Unaudited"
    assert (p["period_start"], p["period_end"], p["period_days"]) == ("2024-10-01", "2024-12-31", 91)
    assert p["revenue"] == 20349.96 and p["revenue_basis"] == "revenue_from_operations"
    assert p["net_profit"] == 4934.8 and p["net_profit_total"] == 5013.18   # owners vs incl. minority
    assert p["eps"] == 3.95
    assert p["operating_profit"] == 5945.92       # revenue - (expenses - finance costs), excludes other income


BANK = """<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:b="http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin">
<xbrli:context id="c1"><xbrli:entity/><xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="ytd"><xbrli:entity/><xbrli:period><xbrli:startDate>2024-04-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<b:NameOfBank contextRef="c1">Test Bank Limited</b:NameOfBank>
<b:DateOfStartOfReportingPeriod contextRef="c1">2024-10-01</b:DateOfStartOfReportingPeriod>
<b:DateOfEndOfReportingPeriod contextRef="c1">2024-12-31</b:DateOfEndOfReportingPeriod>
<b:NatureOfReportStandaloneConsolidated contextRef="c1">Standalone</b:NatureOfReportStandaloneConsolidated>
<b:Income contextRef="c1">1000000000</b:Income>
<b:Income contextRef="ytd">9000000000</b:Income>
<b:ProfitLossForThePeriod contextRef="c1">200000000</b:ProfitLossForThePeriod>
<b:BasicEarningsPerShareAfterExtraordinaryItems contextRef="c1">12.5</b:BasicEarningsPerShareAfterExtraordinaryItems>
</xbrli:xbrl>"""


def test_parse_bank_taxonomy_and_ignores_year_to_date():
    p = parse_xbrl(BANK)
    assert p["name"] == "Test Bank Limited" and p["revenue_basis"] == "total_income"
    assert p["revenue"] == 100.0 and p["net_profit"] == 20.0 and p["eps"] == 12.5   # quarter, not YTD
    assert p["operating_profit"] is None


def test_parse_rejects_filing_without_period():
    with pytest.raises(ValueError):
        parse_xbrl('<x xmlns:b="http://x"><b:Symbol contextRef="c">ABC</b:Symbol></x>')


def f(to, nature="Consolidated", seq=1, rel="Third Quarter", cum="Non-cumulative", xbrl="u"):
    return {"toDate": to, "consolidated": nature, "seqNumber": str(seq), "relatingTo": rel,
            "cumulative": cum, "xbrl": xbrl, "exchdisstime": "x"}


def test_pick_filings_prefers_consolidated_latest_refiling_and_skips_ytd():
    fl = [f("31-Dec-2024", "Non-Consolidated", 5), f("31-Dec-2024", "Consolidated", 3),
          f("31-Dec-2024", "Consolidated", 9),                        # re-filed later
          f("30-Sep-2024", "Consolidated", 2, cum="Cumulative"),      # year-to-date: ignored
          f("30-Jun-2024", "Non-Consolidated", 1, "First Quarter"),   # only standalone exists
          f("31-Mar-2024", "Consolidated", 0, "Annual"),              # not a quarter
          f("30-Sep-2023", xbrl=None)]                                # no XBRL link
    got = pick_filings(fl, 6)
    assert [(x["toDate"], x["consolidated"], x["seqNumber"]) for x in got] == [
        ("31-Dec-2024", "Consolidated", "9"), ("30-Jun-2024", "Non-Consolidated", "1")]
    assert len(pick_filings(fl, 1)) == 1


class Resp:
    def __init__(self, code, body="", js=None):
        self.status_code, self.text, self._js = code, body, js

    def json(self):
        if self._js is None:
            raise ValueError("not json")
        return self._js


class Http:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_client_retries_then_succeeds_and_fails_cleanly(tmp_path):
    ok = Http(Resp(403), TimeoutError("slow"), Resp(200, js=[{"a": 1}]))
    c = NSEClient(http=ok, sleep=lambda s: None, cache_dir=tmp_path)
    assert c.filings("ITC") == [{"a": 1}] and ok.calls == 3
    dead = NSEClient(http=Http(Resp(403), Resp(403), Resp(403)), sleep=lambda s: None, cache_dir=tmp_path)
    with pytest.raises(NSEError, match="HTTP 403"):
        dead.filings("ITC")
    html = NSEClient(http=Http(Resp(200, "<html>blocked</html>")), sleep=lambda s: None, cache_dir=tmp_path)
    with pytest.raises(NSEError, match="not JSON"):
        html.filings("ITC")


class FakeNSE(NSEClient):
    def __init__(self, filings, xmls, cache_dir):
        super().__init__(http=object(), sleep=lambda s: None, cache_dir=cache_dir)
        self._filings, self._xmls, self.xbrl_fetches = filings, xmls, 0

    def filings(self, symbol, period="Quarterly"):
        if symbol not in self._filings:
            raise NSEError(f"{symbol}: HTTP 404")
        return self._filings[symbol]

    def announcements(self, symbol, from_date, to_date):
        return []

    def _get(self, url):
        if url not in self._xmls:       # e.g. shareholding endpoint: not stubbed in these tests
            raise NSEError(f"not stubbed: {url}")
        self.xbrl_fetches += 1
        return Resp(200, self._xmls[url])


def test_nse_results_end_to_end_with_cache_and_errors(tmp_path):
    cl = FakeNSE({"ITC": [f("31-Dec-2024", xbrl="http://x/ITC.xml")]}, {"http://x/ITC.xml": ITC_XML}, tmp_path)
    src = NSEResults(["ITC", "NOPE"], client=cl, cache_dir=tmp_path)
    rows = src.metrics()
    assert [r["ticker"] for r in rows] == ["ITC"] and "NOPE" in src.errors
    r = rows[0]
    assert r["latest_quarter"] == "Q3 FY25" and r["reporting_basis"] == "Consolidated"
    assert r["data_source"] == "nse-xbrl" and r["results_overdue"] == 1   # 2024 data viewed from today
    src2 = NSEResults(["ITC"], client=cl, cache_dir=tmp_path)
    src2.metrics()
    assert cl.xbrl_fetches == 1          # list + XBRL served from cache the second time


ANN = [
    {"an_dt": "31-Jul-2026 16:31:22", "desc": "Outcome of Board Meeting", "attchmntFile": "http://x/Jun26.pdf",
     "attchmntText": "ITC Limited has submitted to the Exchange, the financial results for the period ended Jun 30, 2026."},
    {"an_dt": "21-May-2026 15:22:20", "desc": "Outcome of Board Meeting", "attchmntFile": "http://x/Mar26.pdf",
     "attchmntText": "ITC Limited has submitted to the Exchange, the financial results for the period ended March 31, 2026."},
    {"an_dt": "21-May-2026 15:54:46", "desc": "Updates", "attchmntFile": "http://x/Mar26b.pdf",
     "attchmntText": "ITC Limited has informed the Exchange regarding 'Financial Results'."},   # no period: ignored
    {"an_dt": "15-Oct-2026 19:20:08", "desc": "ESOP", "attchmntFile": "http://x/e.pdf",
     "attchmntText": "Allotment of 1395500 Shares."},
    {"an_dt": "01-Aug-2026 10:00:00", "desc": "Outcome of Board Meeting", "attchmntFile": "http://x/odd.pdf",
     "attchmntText": "results for the period ended Aug 31, 2026"},                              # not a quarter end
]


def test_announced_results_parsed_newest_first():
    got = nse.announced_results(ANN)
    assert [(g["period_end"], g["url"]) for g in got] == [("2026-06-30", "http://x/Jun26.pdf"), ("2026-03-31", "http://x/Mar26.pdf")]


def test_stale_structured_data_flagged_when_exchange_announced_newer_results(tmp_path):
    class Cl(FakeNSE):
        def announcements(self, symbol, a, b):
            return ANN
    cl = Cl({"ITC": [f("31-Dec-2024", xbrl="http://x/ITC.xml")]}, {"http://x/ITC.xml": ITC_XML}, tmp_path)
    r = NSEResults(["ITC"], client=cl, cache_dir=tmp_path).metrics()[0]
    assert r["announced_newer_than_data"] == 1 and r["announced_period_end"] == "2026-06-30"
    assert "OUT OF DATE" in r["data_warnings"] and "http://x/Jun26.pdf" in r["data_warnings"]
    # up-to-date data: the same announcements older than the data -> no flag
    c = fnd.metrics_for({"symbol": "T", "quarters": [q("2026-06-30", 1.0, 1.0, 1.0)],
                         "announced": [{"period_end": "2026-06-30", "announced_at": "x", "url": "u"}]})
    assert c["announced_newer_than_data"] == 0


def q(end, rev, np_, eps):
    return {"period_end": end, "revenue": rev, "net_profit": np_, "eps": eps}


def test_compare_quarters_flags_only_material_differences():
    n = [q("2025-06-30", 1000.0, 100.0, 5.0), q("2025-09-30", 1100.0, 110.0, 5.5)]
    y = [q("2025-06-30", 1010.0, 100.0, 5.0),        # +1%: within 2% tolerance
         q("2025-09-30", 880.0, 110.0, 5.5),         # -20% revenue
         q("2025-12-31", 1.0, 1.0, 1.0)]             # not in NSE data: not compared
    compared, msgs = compare_quarters(n, y)
    assert compared == 2 and len(msgs) == 1 and "revenue" in msgs[0] and "-20.0%" in msgs[0]


class Stub:
    """Stands in for NSEResults / YFinanceFundamentals."""
    def __init__(self, companies, symbols=("T",)):
        self.companies, self.symbols, self.errors = companies, list(symbols), {}

    def company(self, s):
        return self.companies.get(s)


def nse_co():
    return {"symbol": "T", "name": "T", "quarters": [q("2025-03-31", 1000.0, 100.0, 5.0), q("2025-06-30", 1100.0, 110.0, 5.5)],
            "annual": [], "ratios": {}, "warnings": [], "meta": {}}


def yahoo_co(extra=()):
    return {"symbol": "T", "sector": "Tech", "quarters": [q("2025-03-31", 1000.0, 100.0, 5.0), q("2025-06-30", 700.0, 110.0, 5.5), *extra],
            "annual": [], "ratios": {"roce": 30.0, "debt_to_equity": 0.1}, "warnings": [], "meta": {}}


def test_crosscheck_reports_mismatch_takes_ratios_from_yahoo_ignores_newer_by_default():
    cc = CrossCheckedFundamentals(Stub({"T": nse_co()}), Stub({"T": yahoo_co([q("2025-09-30", 1200.0, 120.0, 6.0)])}))
    m = cc.metrics()[0]
    assert m["crosscheck_mismatches"] == 1 and "revenue: NSE 1100.0 vs Yahoo 700.0" in m["data_warnings"]
    assert m["roce"] == 30.0 and "come from Yahoo" in m["data_warnings"]
    assert m["latest_quarter"] == "Q1 FY26"                       # NSE's newest, not Yahoo's Sep quarter
    assert "newer quarter(s) 2025-09-30 not found in NSE data (ignored)" in m["data_warnings"]
    assert m["data_source"] == "nse-xbrl+yahoo"


def test_crosscheck_fill_newer_is_flagged_unverified():
    cc = CrossCheckedFundamentals(Stub({"T": nse_co()}), Stub({"T": yahoo_co([q("2025-09-30", 1200.0, 120.0, 6.0)])}),
                                  fill_newer=True)
    m = cc.metrics()[0]
    assert m["latest_quarter"] == "Q2 FY26" and m["latest_is_unverified"] == 1
    assert "UNVERIFIED" in m["data_warnings"]


def test_crosscheck_without_overlap_or_yahoo_or_nse():
    no_overlap = {**yahoo_co(), "quarters": [q("2026-03-31", 5.0, 5.0, 1.0)]}
    m = CrossCheckedFundamentals(Stub({"T": nse_co()}), Stub({"T": no_overlap})).metrics()[0]
    assert "nothing verified" in m["data_warnings"]
    m2 = CrossCheckedFundamentals(Stub({"T": nse_co()}), Stub({})).metrics()[0]
    assert "Yahoo unavailable" in m2["data_warnings"] and m2.get("roce") is None
    strict = CrossCheckedFundamentals(Stub({}), Stub({"T": yahoo_co()}))
    assert strict.metrics() == [] and "T" in strict.errors
    loose = CrossCheckedFundamentals(Stub({}), Stub({"T": yahoo_co()}), allow_yahoo_only=True)
    assert "unverified" in loose.metrics()[0]["data_warnings"]
