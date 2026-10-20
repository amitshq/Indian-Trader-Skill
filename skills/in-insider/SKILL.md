---
name: in-insider
description: Promoter holding and its change between shareholding-pattern filings, plus insider (SEBI PIT) trade disclosures for Indian stocks. Use when the user asks about promoter buying/selling, promoter stake, or insider trades.
argument-hint: "promoter SYMBOL | trades [SYMBOL]"
---

# in-insider

```bash
python "${CLAUDE_SKILL_DIR}/insider.py" promoter TCS ITC
python "${CLAUDE_SKILL_DIR}/insider.py" trades RELIANCE --days 60
```

- Promoter % comes from the quarterly SEBI shareholding-pattern filing on NSE (`as_of` shows the quarter). 0% means no promoter group, not missing data.
- `trades` lists PIT disclosures. In testing the NSE endpoint returned no rows for the windows tried (Oct 2026), so treat an empty result as unconfirmed, not as "no insider trades".
- Disclosures are filed days after the trade; say so. Never claim inside information. Pledge data is not available from this source.
