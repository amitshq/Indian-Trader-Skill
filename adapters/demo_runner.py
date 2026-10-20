"""Wires core.demo to the real data adapters. Used by scripts/demo_session.py and the API's /api/demo/run."""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

from core import calendar_in, demo, screener
from core.store import Store

from .broker.paper import PaperBroker
from .data.crosscheck import CrossCheckedFundamentals
from .data.nse_market import NSEMarket, promoter_signals, summarize_deals
from .data.nse_results import NSEResults
from .data.quotes import StaticQuotes, YFinanceQuotes
from .data.yf_fundamentals import YFinanceFundamentals

ROOT = Path(__file__).resolve().parents[1]


def run(capital: float = 100000.0, symbols: Optional[List[str]] = None, hold_minutes: float = 0,
        include_screen: bool = False, quotes=None, market=None, sleep: Callable[[float], None] = time.sleep,
        store_path: Optional[Path] = None) -> dict:
    """-> {report (demo dict), text (markdown), db, file}. Dummy money, paper broker, real market data."""
    uni = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))["symbols"]
    symbols = [s.upper() for s in (symbols or uni[:6])]
    stamp = datetime.now(calendar_in.IST).strftime("%Y-%m-%d_%H%M%S")
    db = store_path or ROOT / "data" / "demo" / f"demo_{stamp}.db"
    store = Store(db, starting_cash=capital)
    market = market or NSEMarket()
    quotes = quotes or YFinanceQuotes()

    def screen(syms):
        if not include_screen:
            return None
        src = CrossCheckedFundamentals(NSEResults(syms), YFinanceFundamentals(syms))
        rules = json.loads((ROOT / "config" / "rules.live.example.json").read_text(encoding="utf-8"))
        return screener.screen(src.metrics(), rules)

    def deals():
        d = market.large_deals()
        top = summarize_deals(d, 50)[:5]
        return (f"{len(d['bulk'])} bulk + {len(d['block'])} block deal rows as on {d['as_on']}",
                [f"{r['symbol']}: buy {r['buy_cr']} cr, sell {r['sell_cr']} cr" for r in top])

    def flows():
        f = market.fii_dii()
        return (f"{f[0]['date']}", [f"{r['category']}: buy {r['buy']:,.0f} sell {r['sell']:,.0f} net {r['net']:+,.0f} cr" for r in f])

    def promoters():
        return ("promoter holding (latest SEBI filing)", [f"{s}: {promoter_signals(market.shareholding(s)) or 'n/a'}" for s in symbols[:3]])

    def news():
        import httpx
        from .data import news as nw
        today = datetime.now().date()
        items, errs = nw.fetch_news(symbols[0], None, market.client, lambda u: httpx.get(u, timeout=20, follow_redirects=True).text,
                                    (today - timedelta(days=7)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y"))
        items.sort(key=lambda i: i["time"] or "", reverse=True)
        return (f"{len(items)} items for {symbols[0]} in 7 days" + (f" ({'; '.join(errs)})" if errs else ""),
                [f"{'!' if i['important'] else ' '} {i['title'][:100]}" for i in items[:4]])

    report = demo.run_demo(
        quotes=quotes, store=store, broker_factory=lambda prices: PaperBroker(store, StaticQuotes(prices)),
        symbols=symbols, capital=capital, market_state=market.market_state, screen=screen,
        intel={"Bulk/block deals": deals, "FII/DII flows": flows, "Promoter holding": promoters, "News": news},
        hold_minutes=hold_minutes, sleep=sleep)
    text = demo.render(report)
    out = ROOT / "data" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"demo_{stamp}.md"
    f.write_text(text, encoding="utf-8")
    return {"report": report, "text": text, "db": str(db), "file": str(f)}


def report_to_json(report: dict) -> dict:
    d = {k: v for k, v in report.items() if k != "steps"}
    d["steps"] = [{"name": s.name, "status": s.status, "summary": s.summary, "lines": s.lines} for s in report["steps"]]
    return d
