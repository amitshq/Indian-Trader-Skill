# india-trader

Personal NSE tooling for Indian equities (delivery trades): a shared Python core, Claude skills, a FastAPI backend and a Next.js dashboard.
Built from an analysis of `Jakeschincariol/trader-skill` (MIT; the screener, sizing, rebalance and approval-parser ideas are ported from it) and re-based on Indian rules.

**Personal research tool. Not investment advice. Paper trading by default. Free data sources are unofficial and can be delayed, stale or wrong; every skill says so and shows warnings instead of hiding them.**

## What is in it

| Area | Skill / module | Data |
|---|---|---|
| Market clock | `core/calendar_in.py`, `config/holidays.json` | Real NSE 2026 holiday list (fetched from NSE), Muhurat day flagged as special session |
| Results | `skills/in-fundamentals`, `skills/in-screener` | NSE exchange XBRL filings (authority) cross-checked with Yahoo; manual/PDF entry for quarters the structured data lacks |
| News | `skills/in-news` | NSE announcements + Google News RSS, tagged, new-only |
| Deals & flows | `skills/in-deals` | NSE bulk/block deals (latest session), FII/DII flows |
| Ownership | `skills/in-insider` | Promoter holding from SEBI shareholding patterns; insider (PIT) disclosures (see limits) |
| Sizing | `skills/in-budget` | Whole-share BUY proposals from weights + budget |
| Risk gate | `skills/in-risk`, `core/risk.py` | Your own limits in `config/risk.json` |
| Approval | `skills/in-broker`, `core/approval.py` | Strict one-order "yes" parser |
| Tax | `skills/in-tax`, `core/tax.py` | Lots, STCG/LTCG estimate (delivery equity only) |
| Rebalance | `skills/in-rebalance` | Drift table + sells-first proposals with a cost check |
| Brokers | `adapters/broker/paper.py`, `adapters/broker/upstox.py` | Paper (default). Upstox live adapter: **never run against the real API**, disabled by default |

## Safety model (the part to understand)

1. Nothing is sent anywhere on submit. Orders go: risk gate -> `PENDING` (or `BLOCKED`) -> **you approve each order** -> risk gate is re-checked at that moment -> fill (paper) or send (live).
2. `BLOCKED` orders can never be approved. Chat approvals go through `parse_yes`: "sure", "yes to all", a wrong stock/side/quantity are refused.
3. Live orders additionally need: `config/live.json` `live_enabled: true`, env `INDIA_TRADER_LIVE=I_UNDERSTAND_THIS_USES_REAL_MONEY`, no kill-switch file, order value under a small cap (default ₹10,000), a daily live order cap, and the risk gate re-run against the broker's real funds/holdings. Every attempt is written to `data/live_audit.jsonl`. Secrets come from env vars only and are never stored.
4. The UI banner shows PAPER or LIVE straight from the backend.

## Run

```bash
pip install -e .[dev,data]
python -m pytest -q                       # 106 tests, all offline
uvicorn api.main:app --reload             # http://localhost:8000/docs
cd ui && npm install && npm run dev       # http://localhost:3000
```

Useful environment variables: `QUOTES=yfinance` (delayed prices), `FUNDAMENTALS=verified|nse|yahoo|live` + `SYMBOLS=TCS,INFY` (default universe: `config/universe.json`), `FUNDAMENTALS_PATH=file` (your own JSON/CSV), `BROKER=upstox` (live mode, see below).
Without `QUOTES=yfinance` the API uses in-memory demo prices: set them with `PUT /api/dev/quotes`.

Skills (Claude Code): copy the `skills/in-*` folders into `~/.claude/skills/` or `<project>/.claude/skills/`; each has a `SKILL.md` and a small CLI. Try `python skills/in-screener/screen.py --symbols TCS INFY --rules config/rules.live.example.json`.

## Data you must know about

- **Results**: NSE's structured results dataset lagged badly for the symbols tested (Dec 2024 at Oct 2026) while its announcements feed showed newer filings. Stale stocks are flagged OUT OF DATE (with the PDF link) and fail the live rules. Fill gaps with `skills/in-fundamentals/add_result.py` (you or Claude read the PDF; entries are validated and always carry a review warning). The automatic PDF reader fails closed and rejected the three real PDFs it was tried on (scans, shifted columns, cover letters).
- **Yahoo** supplies ROCE/ROE/debt-equity; no promoter pledge anywhere. Banks need different rules than industrials.
- **Insider (PIT)** returned no rows for the windows tried; treat empty as unconfirmed.
- **Bulk/block deals**: latest session only.
- `config/charges.json` and `config/tax.json` are unverified estimates from memory: check them against your broker's charge sheet and a CA.

## Live trading with Upstox (read before enabling)

The adapter is written from Upstox's documentation and tested only against a fake transport. Before using it: read Upstox's current API docs and SEBI's retail-algo requirements (static IP whitelisting for API orders was being enforced in 2026), then try one tiny order on your own account. Set `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_REDIRECT_URI`, start the API with `BROKER=upstox`, open `/api/live/login-url`, and set `live_enabled` plus the env phrase deliberately. Tokens expire daily and are kept in memory only.

## Not built

F&O, intraday, circuit-limit / ASM / GSM checks, promoter pledge, live Upstox verification, order modification/cancel UI, websocket quotes.
