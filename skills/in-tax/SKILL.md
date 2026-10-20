---
name: in-tax
description: Tax lots, realised gains and an estimate of short-term and long-term capital gains tax on Indian delivery equity trades, plus what-if sale simulation (FIFO/HIFO) and loss-harvest candidates. Use for tax questions about the paper or imported portfolio.
argument-hint: "lots | realized | estimate | simulate SYMBOL QTY PRICE | harvest"
---

# in-tax

```bash
python "${CLAUDE_SKILL_DIR}/lots.py" estimate
python "${CLAUDE_SKILL_DIR}/lots.py" simulate TCS 10 4200 --method HIFO
```

- Delivery equity only: long-term means held MORE than 12 months. Intraday and F&O are business income and are NOT covered.
- Rates and the LTCG exemption are in `config/tax.json` and are UNVERIFIED (as_of is shown). Always repeat that the figure is an estimate that excludes surcharge, cess, 31-Jan-2018 grandfathering and other accounts, and that a CA should confirm.
- India has no US-style wash-sale rule, but repeat buying right after booking a loss may be questioned: say "check with a CA". Never advise on avoiding tax.
