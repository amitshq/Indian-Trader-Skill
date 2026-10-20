#!/usr/bin/env python3
"""Record or auto-read a quarter from a results PDF that the structured data is missing.

    # try the strict automatic reader on the PDF announced to NSE (fails closed):
    python add_result.py auto SYMBOL 2026-06-30 https://nsearchives.nseindia.com/corporate/XYZ.pdf
    # record figures YOU read from the PDF (INR crore; eps in INR; year-ago column from the SAME filing):
    python add_result.py add SYMBOL 2026-09-30 --nature Consolidated --revenue 73188 --other-income 1337 \\
        --total-income 74525 --net-profit 13884 --eps 38.37 --pdf URL \\
        --prior-revenue 65799 --prior-net-profit 12075 --prior-eps 33.37
    python add_result.py list SYMBOL
Entries are validated (identities, units) and always shown with a "review against the filing" warning.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.data import manual_results as mr  # noqa: E402
from adapters.data.nse_results import NSEClient  # noqa: E402
from adapters.data import results_pdf as rp  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auto")
    a.add_argument("symbol"), a.add_argument("period_end"), a.add_argument("url")
    a.add_argument("--save", action="store_true", help="save the extraction as a manual entry if it passed")
    m = sub.add_parser("add")
    m.add_argument("symbol"), m.add_argument("period_end")
    m.add_argument("--nature", required=True, choices=["Consolidated", "Non-Consolidated"])
    m.add_argument("--revenue", type=float, required=True)
    m.add_argument("--other-income", type=float), m.add_argument("--total-income", type=float)
    m.add_argument("--net-profit", type=float, required=True)
    m.add_argument("--eps", type=float, required=True)
    m.add_argument("--pdf", required=True)
    m.add_argument("--entered-by", default="user")
    m.add_argument("--prior-revenue", type=float), m.add_argument("--prior-net-profit", type=float)
    m.add_argument("--prior-eps", type=float)
    ls = sub.add_parser("list")
    ls.add_argument("symbol")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            print(json.dumps(mr.load_entries(args.symbol), indent=1))
            return 0
        if args.cmd == "auto":
            data = NSEClient()._get(args.url).content
            res = rp.extract_statement(rp.pdf_to_text(data), args.period_end)
            print(json.dumps(res, indent=1))
            if args.save:
                e = mr.save_entry({"symbol": args.symbol, "period_end": args.period_end, "nature": res["nature"],
                                   "revenue": res["revenue"], "other_income": res["other_income"],
                                   "total_income": res["total_income"], "net_profit": res["net_profit"],
                                   "eps": res["eps"], "audited": res["audited"], "pdf_url": args.url,
                                   "entered_by": "auto-extractor (" + "; ".join(res["checks"]) + ")"})
                print("saved", e["symbol"], e["period_end"], "(no year-ago comparative: add it manually for growth rates)")
            return 0
        py = None
        if args.prior_revenue is not None:
            py = {"revenue": args.prior_revenue, "net_profit": args.prior_net_profit, "eps": args.prior_eps}
        e = mr.save_entry({"symbol": args.symbol, "period_end": args.period_end, "nature": args.nature,
                           "revenue": args.revenue, "other_income": args.other_income,
                           "total_income": args.total_income, "net_profit": args.net_profit, "eps": args.eps,
                           "pdf_url": args.pdf, "entered_by": args.entered_by, "prior_year": py})
        print("saved", e["symbol"], e["period_end"])
        return 0
    except (mr.EntryError, rp.PdfRejected) as ex:
        print(f"rejected: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
