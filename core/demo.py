"""End-to-end paper-trading rehearsal with DUMMY money against real market data.

Purpose: find out, step by step, whether every skill works on the Indian market right now, and say
honestly which steps worked, which only warned, and which failed. Nothing here touches a live broker.
The approval step is SIMULATED (the demo plays the user) and is labelled that way everywhere.

All dependencies are injected so the orchestration is unit-tested offline.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from . import calendar_in, charges, risk, sizing, tax
from .models import Order

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"


@dataclass
class Step:
    name: str
    status: str
    summary: str
    lines: List[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


class _Skipped(Exception):
    pass


def _fmt_money(v) -> str:
    return f"Rs {v:,.2f}"


def run_demo(*, quotes, store, broker_factory: Callable[[Dict[str, float]], object], symbols: List[str], capital: float,
             market_state: Callable[[], dict], screen: Callable[[List[str]], List[dict]],
             intel: Optional[Dict[str, Callable[[], object]]] = None,
             now: Callable[[], datetime] = lambda: datetime.now(calendar_in.IST),
             hold_minutes: float = 0, sleep: Callable[[float], None] = lambda s: None,
             stale_after_min: float = 20.0, risk_cfg: Optional[risk.RiskConfig] = None) -> dict:
    steps: List[Step] = []
    t0 = now()
    cfg = risk_cfg or risk.RiskConfig.load()

    # 1. what is the exchange doing? (our own calendar vs what NSE itself reports)
    ours = calendar_in.market_status(t0)
    try:
        ex = market_state()
        agree = (ex["state"] or "").lower() == "open" if ours["status"] == "open" else (ex["state"] or "").lower() != "open"
        steps.append(Step("Exchange status", OK if agree else WARN,
                          f"NSE says {ex['state']} ({ex['message']}); our calendar says {ours['status']}",
                          [f"NSE last trade date {ex['trade_date']}, NIFTY 50 {ex['nifty']} ({ex['nifty_change_pct']}%)",
                           f"Next open per our calendar: {ours['next_open']}"]
                          + ([] if agree else ["The two disagree: trust NSE for 'is it open right now', check config/holidays.json."]),
                          {"nse": ex, "ours": ours}))
        is_open = (ex["state"] or "").lower() == "open"
    except Exception as e:
        steps.append(Step("Exchange status", WARN, f"could not read NSE market status ({e}); using our calendar: {ours['status']}"))
        is_open = ours["status"] == "open"

    # 2. quotes and how old they are
    detail = quotes.detail(symbols)
    missing = [s for s in symbols if s not in detail]
    lines, stale = [], []
    for s in symbols:
        d = detail.get(s)
        if not d:
            lines.append(f"{s:<12} no price")
            continue
        age = None
        if d.get("as_of"):
            age = (t0 - datetime.fromisoformat(d["as_of"]).astimezone(calendar_in.IST)).total_seconds() / 60
        move = f"{(d['price'] / d['prev_close'] - 1) * 100:+.2f}% vs prev close" if d.get("prev_close") else "no prev close"
        lines.append(f"{s:<12} {_fmt_money(d['price']):>14}  {move:<24} as of {d.get('as_of') or 'unknown'}"
                     + (f"  ({age:,.0f} min old)" if age is not None else ""))
        if age is None or age > stale_after_min:
            stale.append(s)
    if not detail:
        steps.append(Step("Quotes", FAIL, "no prices at all: cannot continue", lines))
        return _finish(steps, store, None, capital, t0, now(), aborted=True)
    status = OK
    msg = f"{len(detail)}/{len(symbols)} symbols priced"
    if missing:
        status, msg = WARN, msg + f"; missing: {', '.join(missing)}"
    if stale:
        status = WARN
        msg += (f"; {len(stale)} price(s) older than {stale_after_min:g} min"
                + ("" if is_open else " - the market is closed, so these are LAST-CLOSE prices (a rehearsal, not a live fill)"))
    steps.append(Step("Quotes", status, msg, lines, {"detail": detail}))
    symbols = [s for s in symbols if s in detail]
    prices = {s: detail[s]["price"] for s in symbols}

    # 3. fundamentals screen
    try:
        rows = screen(symbols)
        if rows is None:
            steps.append(Step("Screen (fundamentals)", SKIP, "skipped: not requested for this run (it reads NSE filings and can take minutes)"))
            raise _Skipped
        passed = [r for r in rows if r["passed"]]
        sl = [f"PASS {r['ticker']} score {r.get('score')}" for r in passed] + \
             [f"FAIL {r['ticker']}: " + "; ".join(r["fails"][:3]) for r in rows if not r["passed"]]
        steps.append(Step("Screen (fundamentals)", OK if passed else WARN,
                          f"{len(passed)} of {len(rows)} pass the rules",
                          sl + ([] if passed else ["Nothing passed. With stale or missing results data that is the CORRECT outcome: the screen fails closed."]),
                          {"passed": [r["ticker"] for r in passed]}))
        screened = [r["ticker"] for r in passed]
    except _Skipped:
        screened = []
    except Exception as e:
        steps.append(Step("Screen (fundamentals)", FAIL, f"screen crashed: {type(e).__name__}: {e}"))
        screened = []

    # 4. basket
    if screened:
        basket, basis = screened, "stocks that passed the screen"
    else:
        basket, basis = symbols, "ALL demo symbols (no stock passed the screen): arbitrary equal weights, only to exercise the pipeline"
    weights = {s: 1.0 for s in basket}
    steps.append(Step("Basket", OK if screened else WARN, f"{len(basket)} stocks from {basis}" if screened or steps[-1].status != SKIP
                      else f"{len(basket)} demo stocks (screen skipped): arbitrary equal weights, only to exercise the pipeline", [", ".join(basket)]))

    # 5. sizing with the risk gate's own position cap
    cap = max(1.0, cfg.max_position_pct - 2)
    # With few stocks the per-stock cap cannot reach 100%: invest only what the cap allows and keep the rest in cash
    # (a 2-stock basket under a 20% cap invests at most ~36%), instead of breaking the risk limit.
    frac = min(1.0, len(weights) * cap / 100.0)
    budget = capital * frac
    try:
        sized = sizing.size_buys(weights, prices, budget, cash_buffer_pct=max(cfg.cash_buffer_pct, 5.0) if frac >= 1.0 else 0.0,
                                 max_position_pct=min(100.0, cap / frac) if frac < 1.0 else cap, min_order_value=cfg.min_order_value)
        sized["leftover"] = round(capital - sized["invested"], 2)
        steps.append(Step("Sizing", OK, f"{len(sized['orders'])} whole-share orders, invests {_fmt_money(sized['invested'])} of {_fmt_money(capital)}"
                          + (f" (only {frac:.0%}: {len(weights)} stock(s) x {cap:g}% position cap)" if frac < 1.0 else ""),
                          [f"{o['side']} {o['qty']:>4} {o['symbol']:<12} @ {o['price']:>10,.2f} = {_fmt_money(o['value'])}  (target {o['weight_target']:.0%}, actual {o['weight_actual']:.0%})"
                           for o in sized["orders"]] + [f"skipped {s}: {w}" for s, w in sized["skipped"]]
                          + [f"leftover cash {_fmt_money(sized['leftover'])}"], {"sized": sized}))
    except sizing.SizingError as e:
        steps.append(Step("Sizing", FAIL, str(e)))
        return _finish(steps, store, None, capital, t0, now(), aborted=True)

    # 6. queue through the risk gate
    broker = broker_factory(prices)
    queued = [broker.submit(Order(o["symbol"], "BUY", o["qty"])) for o in sized["orders"]]
    blocked = [o for o in queued if o.status == "BLOCKED"]
    steps.append(Step("Risk gate + queue", WARN if blocked else OK,
                      f"{len(queued) - len(blocked)} queued, {len(blocked)} blocked by the gate",
                      [f"#{o.id} BUY {o.qty} {o.symbol}: {o.status} {o.reason}".strip() for o in queued]
                      + (["market is closed: the gate WARNS (paper orders fill at the last price; a live order would wait or go AMO)"] if not is_open else [])))

    # 7. simulated approval
    filled = []
    for o in [q for q in queued if q.status == "PENDING"]:
        r = broker.approve(o.id)
        filled.append(r)
    steps.append(Step("Approval (SIMULATED)", OK if filled and all(f.status == "FILLED" for f in filled) else WARN,
                      f"{sum(f.status == 'FILLED' for f in filled)}/{len(filled)} orders filled - the demo played the user and said yes to each order; "
                      "in real use YOU approve every order, one at a time",
                      [f"#{f.id} {f.side} {f.qty} {f.symbol}: {f.status} @ {f.fill_price}" for f in filled]))

    # 8. mark to market (optionally after waiting)
    entry = {p["symbol"]: p["avg_price"] for p in store.positions()}
    if hold_minutes > 0:
        sleep(hold_minutes * 60)
    after = quotes.detail(list(entry))
    if hasattr(broker.quotes, "prices"):     # later fills use the refreshed prices
        broker.quotes.prices.update({s: d["price"] for s, d in after.items()})
    lines, total = [], 0.0
    for s, avg in entry.items():
        px = (after.get(s) or detail.get(s))["price"]
        qty = next(p["qty"] for p in store.positions() if p["symbol"] == s)
        pnl = (px - avg) * qty
        total += pnl
        lines.append(f"{s:<12} {qty:>4} sh  bought {avg:>10,.2f}  now {px:>10,.2f}  P&L {pnl:>+10,.2f}  (as of {(after.get(s) or {}).get('as_of') or 'unchanged'})")
    steps.append(Step("Mark to market", OK if hold_minutes > 0 and after else WARN,
                      f"unrealised P&L {_fmt_money(total)}" + ("" if hold_minutes > 0 else " (no waiting: right after filling, so this is only the price noise and charges)"),
                      lines))

    # 9. sell one position to exercise lots, charges and the tax engine
    if entry:
        sym = next(iter(entry))
        pos = store.get_position(sym)
        q = max(1, pos["qty"] // 2)
        s_order = broker.submit(Order(sym, "SELL", q))
        if s_order.status == "PENDING":
            s_order = broker.approve(s_order.id)
        est = tax.estimate_tax(store.list_realized(), tax.fy_of(t0.date()))
        steps.append(Step("Sell + tax lots (SIMULATED approval)", OK if s_order.status == "FILLED" else WARN,
                          f"SELL {q} {sym}: {s_order.status} {s_order.reason}".strip(),
                          [f"realised: {r['qty']} sh {r['term']} net {_fmt_money(r['net_pnl'])} (buy {r['buy_date']} @ {r['buy_price']:,.2f} -> sell @ {r['sell_price']:,.2f})"
                           for r in store.list_realized()]
                          + [f"estimated tax this FY {_fmt_money(est['estimated_tax'])} (rates UNVERIFIED, same-day trades are STCG)"]))

    # 10. market intelligence, each best-effort
    for name, fn in (intel or {}).items():
        try:
            res = fn()
            steps.append(Step(name, OK, res[0] if isinstance(res, tuple) else str(res), (res[1] if isinstance(res, tuple) else [])))
        except Exception as e:
            steps.append(Step(name, WARN, f"unavailable: {type(e).__name__}: {e}"))

    return _finish(steps, store, broker, capital, t0, now())


def _finish(steps, store, broker, capital, t0, t1, aborted=False) -> dict:
    cash = store.get_cash()
    pos = store.positions()
    orders = store.list_orders()
    fees = 0.0
    for o in orders:
        if o.status == "FILLED" and o.fill_price:
            fees += charges.estimate(o.side, o.qty, o.fill_price)["total"]
    return {"started": t0.isoformat(timespec="seconds"), "finished": t1.isoformat(timespec="seconds"), "capital": capital,
            "cash_left": cash, "positions": pos, "orders": [o.to_dict() for o in orders], "estimated_charges_paid": round(fees, 2),
            "steps": steps, "aborted": aborted,
            "counts": {k: sum(s.status == k for s in steps) for k in (OK, WARN, FAIL, SKIP)}}


def render(report: dict) -> str:
    c = report["counts"]
    out = [f"# Paper-trading rehearsal (DUMMY money {_fmt_money(report['capital'])})",
           f"Started {report['started']}, finished {report['finished']}.",
           f"**Result: {c[OK]} OK, {c[WARN]} warnings, {c[FAIL]} failures**" + (" - run aborted early" if report["aborted"] else ""), ""]
    for i, s in enumerate(report["steps"], 1):
        out.append(f"## {i}. {s.name}: {s.status}")
        out.append(s.summary)
        out += [f"    {ln}" for ln in s.lines]
        out.append("")
    out.append(f"Cash left {_fmt_money(report['cash_left'])}; estimated charges paid {_fmt_money(report['estimated_charges_paid'])}.")
    out.append("Prices come from an unofficial delayed feed; nothing here was sent to a broker. Not investment advice.")
    return "\n".join(out)
