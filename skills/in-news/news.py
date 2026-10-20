#!/usr/bin/env python3
"""Headlines + NSE announcements for symbols, tagged, new items only (state in data/state/news.json).
    python news.py SYMBOL [SYMBOL ...] [--all] [--days 30] [--json]
Exit 0 = something new, 1 = nothing new, 2 = error.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from adapters.data import news  # noqa: E402
from adapters.data.nse_results import NSEClient  # noqa: E402

STATE = ROOT / "data" / "state" / "news.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--all", action="store_true", help="show already-seen items too (does not update state)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    client, out, errors = NSEClient(), [], []
    today = date.today()
    for s in a.symbols:
        items, errs = news.fetch_news(
            s.upper(), None, client, lambda u: httpx.get(u, timeout=20, follow_redirects=True).text,
            (today - timedelta(days=a.days)).strftime("%d-%m-%Y"), today.strftime("%d-%m-%Y"))
        errors += [f"{s}: {e}" for e in errs]
        if a.all:
            out += items
        else:
            fresh, seen = news.new_only(items, seen)
            out += fresh
    if not a.all:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(seen))
    out.sort(key=lambda i: datetime.fromisoformat(i["time"]).astimezone(timezone.utc) if i["time"] else datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    out.sort(key=lambda i: not i["important"])
    for e in errors:
        print("news:", e, file=sys.stderr)
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for i in out:
            flag = "!" if i["important"] else " "
            print(f"{flag} [{i['symbol']}] {i['kind']:<8} {i['time'] or '-':<26} {','.join(i['tags']) or '-':<14} {i['title'][:110]}")
            if i["url"]:
                print(f"      {i['url']}")
        print("\nHeadlines are leads, not facts: read the filing. Not advice; no predictions.")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
