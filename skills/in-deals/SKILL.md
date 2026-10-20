---
name: in-deals
description: NSE bulk and block deals (latest session) summarised per stock, and FII/DII daily cash-market flows. Use when the user asks who is buying or selling big, or about institutional flows.
argument-hint: "deals | flows"
---

# in-deals

```bash
python "${CLAUDE_SKILL_DIR}/deals.py" deals --min-cr 10
python "${CLAUDE_SKILL_DIR}/deals.py" flows
```

- Values are INR crore (qty x weighted average price). NSE publishes the latest session only; older history needs a saved snapshot.
- Say the date shown (`as on`). Buy and sell of similar size by funds/brokers is usually churn or an inter-fund transfer, not a signal.
- Never infer inside information or predict prices. Not advice.
