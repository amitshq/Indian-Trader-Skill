---
name: in-screener
description: Screen and rank NSE/BSE stocks against your own rules (ROCE, debt/equity, promoter pledge, growth). Shows the number and threshold behind every pass or fail. Use when the user wants a shortlist, a filter, or "which stocks match X".
argument-hint: "[rules file] [metrics file]"
---

# in-screener

Run the deterministic screener; do not compute or rank by hand.

```bash
python "${CLAUDE_SKILL_DIR}/screen.py" --data <metrics.json|csv> --rules <rules.json> [--prices prices.json]
```

- Rules format: see `config/rules.example.json` (ops: `> >= < <= == != between in "not in"`; `missing`: `fail` or `skip`).
- Metrics come from `in-fundamentals` (JSON of reported results) or a CSV export with a `symbol` column.
- With `--prices`, adds `pe` and `earnings_yield` from `eps_ttm`.

Live data: `--symbols RELIANCE TCS ... --rules config/rules.live.example.json` fetches reported results from Yahoo via yfinance (cached 24h in `data/cache/fundamentals/`). Limits to state in your answer:
- Unofficial source; verify key numbers against the NSE/BSE filing before acting.
- No promoter pledge, no true promoter holding (only Yahoo's `insider_holding`), no standalone/consolidated flag.
- Banks/NBFCs: ROCE and debt/equity are not meaningful and are often missing, so they fail rules on those metrics. Do not screen them with industrial rules.
- Each company's latest quarter can differ (shown as `latest_quarter`); TTM is skipped when a quarter is missing.

Source modes (`--source`): `verified` (default) = NSE exchange filings (XBRL) as the authority, cross-checked against Yahoo, ratios from Yahoo; `nse` = filings only; `yahoo` = Yahoo only. Read `data_warnings` aloud: they say when figures are out of date (`announced_newer_than_data`), when sources disagree (`crosscheck_mismatches`), or when a quarter is unverified.
- As of Oct 2026 NSE's structured results dataset lagged by ~21 months for the symbols tested (stops at Dec 2024), while the announcements feed showed newer filings. Never present stale-flagged numbers as current; link the PDF from the warning.

Rules for your answer:
- State the data source and its date. The default file is SYNTHETIC SAMPLE data; say so if it is in use.
- Report the reasons the CLI prints; never invent a pass or fail.
- A screen is a filter, not a recommendation. No return predictions, no "buy" calls. Personal tool, not SEBI-registered advice.
- Nothing here places orders. Sizing and orders go through the risk and broker steps with explicit user approval.
