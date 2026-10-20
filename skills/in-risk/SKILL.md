---
name: in-risk
description: Pre-trade risk gate for NSE orders: blocked list, order size limits, max position %, cash buffer, no short selling, price band, duplicates, daily order limit. Use before any order goes to the broker step.
argument-hint: "--orders orders.json"
---

# in-risk

```bash
python "${CLAUDE_SKILL_DIR}/check.py" --orders orders.json [--prices prices.json]
```

- Limits come from `config/risk.json`; each order is checked as if the earlier passing orders had filled.
- A PASS carries a fingerprint of the exact order. The broker step re-checks the gate at approval time, so a stale PASS cannot place an order.
- Report BLOCK reasons verbatim. Never suggest editing limits just to get an order through; if the user wants a limit changed, that is their decision.
- Equity delivery (CNC) only. Circuit-limit, ASM/GSM and F&O-ban checks are not implemented: say so if asked.
