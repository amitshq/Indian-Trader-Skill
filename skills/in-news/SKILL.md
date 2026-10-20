---
name: in-news
description: New headlines and NSE corporate announcements for Indian stocks, tagged (results, dividend, deal, people, rating, legal, risk, insider) with exchange-filed events marked important. Use when the user asks what is new on a stock or for a watchlist.
argument-hint: "SYMBOL [SYMBOL ...]"
---

# in-news

```bash
python "${CLAUDE_SKILL_DIR}/news.py" ITC TCS [--all] [--days 30] [--json]
```

- Only items not shown before are listed (30-day memory); `--all` shows everything.
- `!` = exchange announcement classified as a material event (board outcome, results, director change, rating, acquisition, dividend...).
- Rules for your answer: filings beat headlines; a headline is a lead, so open the link before summarising; never predict price moves; state the time of each item; say plainly if a source failed (errors go to stderr).
- Personal research tool, not investment advice.
