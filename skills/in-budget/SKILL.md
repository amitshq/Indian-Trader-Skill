---
name: in-budget
description: Turn target weights and a rupee budget into whole-share BUY proposals for NSE stocks (cash buffer, per-stock cap, minimum order, leftover cash). Use after a screener shortlist or when the user says "invest 5 lakh across X, Y, Z".
argument-hint: "--budget 500000 --weights '{\"TCS\":40,\"ITC\":60}'"
---

# in-budget

```bash
python "${CLAUDE_SKILL_DIR}/size.py" --budget 500000 --weights '{"TCS":40,"ITC":30,"INFY":30}' --max-position 35
python "${CLAUDE_SKILL_DIR}/size.py" --budget 500000 --targets shortlist_weights.json --queue
```

- India has no fractional shares: quantities are whole numbers, leftover cash stays in cash.
- Prices: `--prices file.json`, else delayed unofficial Yahoo quotes (say so; they are not tradable prices).
- `--queue` only submits to the PAPER approval queue after the risk gate. It never fills anything and never touches a live broker.
- Rules for your answer: present the table and the leftover cash; say these are proposals; do not recommend the stocks themselves; equal weights are a placeholder, not a view.
