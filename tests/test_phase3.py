import json
from datetime import datetime, timedelta, timezone

import pytest

from adapters.data import news
from adapters.data.nse_market import NSEMarket, _d, normalize_pit, promoter_signals, summarize_deals
from adapters.data.nse_results import NSEClient


class Resp:
    def __init__(self, js):
        self._js, self.status_code = js, 200

    def json(self):
        return self._js


class FakeClient(NSEClient):
    def __init__(self, routes):
        super().__init__(http=object(), sleep=lambda s: None)
        self.routes, self.urls = routes, []

    def _get(self, url):
        self.urls.append(url)
        for frag, js in self.routes.items():
            if frag in url:
                return Resp(js)
        raise AssertionError("unexpected url " + url)


def test_date_parsing():
    assert _d("19-Oct-2026") == "2026-10-19" and _d("30-SEP-2026") == "2026-09-30"
    assert _d("15-Oct-2026 19:20:08") == "2026-10-15" and _d("19-10-2026") == "2026-10-19"
    assert _d(None) is None and _d("garbage") is None


HOL = {"CM": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
              {"tradingDate": "15-Feb-2026", "weekDay": "Sunday", "description": "Mahashivratri"},
              {"tradingDate": "08-Nov-2026", "weekDay": "Sunday", "description": "Diwali Laxmi Pujan*"}], "FO": []}


def test_holidays_config_written_from_nse(tmp_path):
    m = NSEMarket(FakeClient({"holiday-master": HOL}))
    doc = m.write_holidays_config(tmp_path / "h.json")
    assert doc["holidays"] == ["2026-01-26"]                       # only weekday closures
    assert doc["on_weekend"] == ["2026-02-15", "2026-11-08"] and doc["special_sessions"] == ["2026-11-08"]
    from core import calendar_in
    assert calendar_in.load_holidays(tmp_path / "h.json") == {datetime(2026, 1, 26).date()}
    with pytest.raises(Exception, match="no holidays"):
        NSEMarket(FakeClient({"holiday-master": {"CM": []}})).write_holidays_config(tmp_path / "x.json")


DEALS = {"as_on_date": "19-Oct-2026",
         "BULK_DEALS_DATA": [
             {"buySell": "BUY", "clientName": "A FUND", "date": "19-Oct-2026", "name": "Kross Ltd", "qty": "1000000", "symbol": "KROSS", "watp": "300"},
             {"buySell": "SELL", "clientName": "B LLP", "date": "19-Oct-2026", "name": "Kross Ltd", "qty": "400000", "symbol": "KROSS", "watp": "310"},
             {"buySell": "SELL", "clientName": "C", "date": "19-Oct-2026", "name": "Tiny Ltd", "qty": "100", "symbol": "TINY", "watp": "10"}],
         "BLOCK_DEALS_DATA": [{"buySell": "BUY", "clientName": "BOFA", "date": "15-Oct-2026", "name": "Eternal", "qty": "5337584", "symbol": "ETERNAL", "watp": "316"}],
         "SHORT_DEALS_DATA": []}


def test_large_deals_and_summary():
    d = NSEMarket(FakeClient({"largedeal": DEALS})).large_deals()
    assert d["as_on"] == "2026-10-19" and len(d["bulk"]) == 3 and d["block"][0]["qty"] == 5337584
    s = summarize_deals(d, min_value_cr=1.0)
    assert [r["symbol"] for r in s] == ["ETERNAL", "KROSS"]            # TINY filtered out
    k = next(r for r in s if r["symbol"] == "KROSS")
    assert k["buy_cr"] == 30.0 and k["sell_cr"] == 12.4 and k["net_cr"] == 17.6


def test_fii_dii_and_shareholding():
    fd = NSEMarket(FakeClient({"fiidii": [{"buyValue": "14,781.31", "category": "DII", "date": "19-Oct-2026", "netValue": "3201.19", "sellValue": "11580.12"}]})).fii_dii()
    assert fd[0]["buy"] == 14781.31 and fd[0]["date"] == "2026-10-19"
    shp = NSEMarket(FakeClient({"share-holdings": [
        {"date": "30-JUN-2026", "pr_and_prgrp": "50.1", "public_val": "49.9", "employeeTrusts": "0", "broadcastDate": "10-JUL-2026 10:00:00"},
        {"date": "30-SEP-2026", "pr_and_prgrp": "49.0", "public_val": "51.0", "employeeTrusts": "0", "broadcastDate": "13-OCT-2026 17:01:44"}]})).shareholding("ITC")
    assert shp[0]["as_of"] == "2026-09-30"                              # newest first
    assert promoter_signals(shp) == {"promoter_holding": 49.0, "promoter_holding_as_of": "2026-09-30", "promoter_holding_change": -1.1}
    assert promoter_signals([]) == {}


def test_insider_rows_normalised_and_url_built():
    c = FakeClient({"corporates-pit": {"data": [{"symbol": "ABC", "company": "ABC Ltd", "acqName": "R Shah", "personCategory": "Promoters",
                                                  "secAcq": "5000", "secVal": "250000", "tdpTransactionType": "Buy", "acqfromDt": "10-Oct-2026",
                                                  "acqtoDt": "10-Oct-2026", "intimDt": "14-Oct-2026", "afterAcqSharesPer": "51.2"}]}})
    rows = NSEMarket(c).insider_trades("ABC", "01-10-2026", "20-10-2026")
    assert rows[0]["person"] == "R Shah" and rows[0]["qty"] == 5000.0 and rows[0]["intimated"] == "2026-10-14"
    assert "symbol=ABC" in c.urls[0] and "from_date=01-10-2026" in c.urls[0]
    assert normalize_pit({})["qty"] is None                              # missing keys tolerated


def test_tagging():
    assert "results" in news.tag("ITC Q1 FY27 earnings beat estimates")
    assert {"legal", "risk"} <= set(news.tag("SEBI order imposes penalty over alleged fraud"))
    assert "dividend" in news.tag("Record date fixed for interim dividend")
    assert news.tag("Company opens new showroom") == []


ANN = [{"seq_id": "9", "desc": "Outcome of Board Meeting", "attchmntText": "ITC submitted the financial results for the period ended Jun 30, 2026.",
        "attchmntFile": "http://x/r.pdf", "an_dt": "31-Jul-2026 16:31:22"},
       {"seq_id": "8", "desc": "Trading Window", "attchmntText": "Closure of trading window", "attchmntFile": None, "an_dt": "01-Jul-2026 10:00:00"}]

RSS = """<rss><channel>
<item><title>ITC shares rise after results</title><link>http://n/1</link><guid>g1</guid><pubDate>Fri, 31 Jul 2026 12:00:00 GMT</pubDate><source>Mint</source></item>
<item><title></title><link>http://n/2</link></item>
<item><title>SEBI penalty on firm</title><link>http://n/3</link><pubDate>not a date</pubDate></item></channel></rss>"""


def test_announcements_and_rss_items():
    a = news.from_announcements(ANN, "itc")
    assert a[0]["important"] and "results" in a[0]["tags"] and a[0]["id"] == "nse:9"
    assert not a[1]["important"] and a[1]["kind"] == "filing"
    assert a[0]["time"] == "2026-07-31T16:31:22+05:30" and a[0]["time"] > a[1]["time"]
    r = news.from_rss(RSS, "itc")
    assert [x["title"] for x in r] == ["ITC shares rise after results", "SEBI penalty on firm"]   # empty title skipped
    assert r[0]["time"] == "2026-07-31T12:00:00+00:00" and r[1]["time"] is None and r[0]["kind"] == "headline"
    assert not any(x["important"] for x in r)                    # headlines are leads, never flagged important


def test_new_only_dedupes_and_prunes():
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    items = [{"id": "a"}, {"id": "b"}]
    fresh, seen = news.new_only(items, {}, now=now)
    assert [i["id"] for i in fresh] == ["a", "b"]
    fresh2, seen2 = news.new_only(items + [{"id": "c"}], seen, now=now)
    assert [i["id"] for i in fresh2] == ["c"]
    old = {"a": (now - timedelta(days=31)).isoformat()}
    fresh3, seen3 = news.new_only([{"id": "a"}], old, now=now)
    assert [i["id"] for i in fresh3] == ["a"]                    # expired memory -> shown again


def test_fetch_news_survives_one_source_failing():
    class C:
        def announcements(self, *a):
            return ANN

    def boom(url):
        raise OSError("offline")
    items, errors = news.fetch_news("ITC", "ITC Limited", C(), boom, "01-07-2026", "20-10-2026")
    assert len(items) == 2 and errors == ["headlines: offline"]
    items2, errors2 = news.fetch_news("ITC", None, C(), lambda u: RSS, "a", "b")
    assert len(items2) == 4 and errors2 == []
