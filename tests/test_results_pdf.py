import pytest

from adapters.data import manual_results as mr
from adapters.data import results_pdf as rp
from adapters.data.nse_results import NSEResults

GOOD = """
Registered office
\f
Statement of Unaudited Consolidated Financial Results for the quarter ended 30th June, 2026
(Rs. in crore)
Particulars                          3 months ended    Preceding    Year ago
1  Revenue from operations              1,000.00        950.00       900.00
2  Other income                            50.00         40.00        30.00
3  Total income (1+2)                   1,050.00        990.00       930.00
4  Total expenses                         800.00        760.00       700.00
   Profit before exceptional items and tax   250.00      230.00       230.00
   Net profit for the period attributable to owners   180.00    170.00   160.00
   Earnings per share (Basic) (Rs.)       9.50           9.00         8.50
"""


def test_extract_good_statement():
    r = rp.extract_statement(GOOD, "2026-06-30")
    assert (r["nature"], r["revenue"], r["other_income"], r["total_income"], r["net_profit"], r["eps"]) == \
        ("Consolidated", 1000.0, 50.0, 1050.0, 180.0, 9.5)
    assert len(r["checks"]) == 2 and r["audited"] == "Unaudited"


def test_lakh_unit_converted_to_crore():
    t = GOOD.replace("(Rs. in crore)", "(Rs. in lakhs)")
    r = rp.extract_statement(t, "2026-06-30")
    assert r["revenue"] == 10.0 and r["net_profit"] == 1.8


@pytest.mark.parametrize("mutate,why", [
    (lambda t: t.replace("1,050.00        990.00", "1,060.00        990.00"), "total income"),   # identity broken
    (lambda t: t.replace("(Rs. in crore)", "(figures as stated)"), "unit"),
    (lambda t: t.replace("quarter ended 30th June, 2026", "quarter ended 31st March, 2026"), "does not say"),
    (lambda t: t.replace("Earnings per share (Basic) (Rs.)       9.50", "Earnings per share (Basic) (Rs.)"), "misaligned"),  # blank first cell must not shift to the prior quarter
    (lambda t: t.replace("4  Total expenses                         800.00", "4  Total expenses                         100.00"), "total expenses"),
])
def test_rejects_when_untrustworthy(mutate, why):
    with pytest.raises(rp.PdfRejected, match="(?i)" + why):
        rp.extract_statement(mutate(GOOD), "2026-06-30")


def test_rejects_cover_letter_only():
    with pytest.raises(rp.PdfRejected):
        rp.extract_statement("Dear Sirs, results for the quarter ended 30th June, 2026 are enclosed.", "2026-06-30")


def test_number_parsing_indian_grouping_and_negatives():
    assert rp.first_number("  1,45,463   1,29,236") == 145463.0
    assert rp.first_number("(1,110.12)  (14.27)") == -1110.12
    assert rp.first_number("-") is None


BASE = {"symbol": "tcs", "period_end": "2026-09-30", "nature": "Consolidated", "revenue": 73188.0,
        "other_income": 1337.0, "total_income": 74525.0, "net_profit": 13884.0, "eps": 38.37,
        "pdf_url": "http://x/p.pdf", "prior_year": {"revenue": 65799.0, "net_profit": 12075.0, "eps": 33.37}}


def test_manual_entry_validation():
    assert mr.validate_entry(BASE)["symbol"] == "TCS"
    for bad, msg in [({"period_end": "2026-09-29"}, "quarter end"), ({"nature": "x"}, "nature"),
                     ({"total_income": 80000.0}, "does not equal"), ({"net_profit": 99999999.0}, "larger than"),
                     ({"pdf_url": ""}, "missing pdf_url"), ({"prior_year": {"revenue": 1}}, "prior_year"),
                     ({"revenue": "73188"}, "number")]:
        with pytest.raises(mr.EntryError, match=msg):
            mr.validate_entry({**BASE, **bad})


def test_manual_entry_merges_with_comparative_and_gives_growth(tmp_path):
    mr.save_entry(BASE, tmp_path)
    mr.save_entry({**BASE, "revenue": 73189.0, "total_income": 74526.0}, tmp_path)   # re-save replaces, not duplicates
    assert len(mr.load_entries("TCS", tmp_path)) == 1

    class Offline(NSEResults):
        def _fetch_company(self, symbol):
            return None
    src = NSEResults(["TCS"], manual_dir=tmp_path, cache_dir=tmp_path)
    src._fetch_company = lambda s: None            # no structured filings at all
    m = src.metrics()[0]
    assert m["latest_quarter"] == "Q2 FY27" and m["latest_from_pdf"] == 1
    assert m["revenue_growth_yoy"] == pytest.approx((73189 - 65799) / 65799 * 100, abs=0.01)
    assert "not machine-verified" in m["data_warnings"]


def test_manual_entry_never_overwrites_exchange_quarter():
    comp = {"quarters": [{"period_end": "2026-09-30", "revenue": 1.0, "net_profit": 1.0, "eps": 1.0}], "warnings": []}
    out = mr.merge_into(comp, [mr.validate_entry(BASE)])
    assert [q["revenue"] for q in out["quarters"] if q["period_end"] == "2026-09-30"] == [1.0]
