---
name: in-rebalance
description: Show how far an Indian equity portfolio has drifted from target weights and propose whole-share trades (sells first) only for stocks outside a band, skipping trades too small to be worth the fees. Use when the user asks to rebalance.
argument-hint: "--targets '{\"TCS\":40,\"ITC\":60}' [--band 5]"
---

# in-rebalance

```bash
python "${CLAUDE_SKILL_DIR}/rebalance.py" --targets '{"TCS":40,"ITC":30,"INFY":30}' --band 5 --min-trade 5000
```

- Only names outside the band are traded; each proposal shows estimated charges. Sells realise tax: run `in-tax simulate` first and tell the user.
- Holdings not in the target list are left alone unless `--sell-untracked`.
- `--queue` submits to the PAPER approval queue after the risk gate. Nothing fills until the user approves each order (see in-broker).
- Say which prices were used (file or delayed Yahoo). Proposals, not advice.
