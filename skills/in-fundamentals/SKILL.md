---
name: in-fundamentals
description: Summarise reported quarterly and annual results of NSE/BSE companies into metrics (YoY growth, margins, TTM EPS, ROCE, debt/equity, promoter holding and pledge). Use when the user asks how a company is doing on its numbers or wants metrics for the screener.
argument-hint: "<results.json> [SYMBOL ...]"
---

# in-fundamentals

```bash
python "${CLAUDE_SKILL_DIR}/facts.py" <results.json> [SYMBOL ...] [--json] [--out metrics.json]
```

- Indian fiscal year is Apr-Mar: "Q3 FY26" = quarter ended 31 Dec 2025.
- YoY compares the same quarter a year earlier. TTM needs four consecutive quarters.
- If Q4 is missing but the annual figure and Q1-Q3 are present, Q4 is derived (annual minus Q1-Q3) and flagged as derived.
- Standalone vs consolidated: say which one the data is. Banks/NBFCs have different line items (no operating profit): leave blank, never guess.
- Missing numbers stay blank. The CLI never fills gaps.

Your answer must state the data source and period, flag derived figures, and avoid predictions or buy/sell calls (education/tooling only).

Phase 2 reads local JSON/CSV. Live fetchers (NSE/BSE results, screener.in export, broker API) are a later adapter behind `FundamentalsSource`.
