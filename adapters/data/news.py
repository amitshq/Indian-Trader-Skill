"""Headlines + exchange announcements for a stock, tagged, de-duplicated, never predictive.

Sources: NSE corporate announcements (primary: filings beat headlines) and Google News RSS
(leads only). Tags come from keyword rules; 'important' marks SEBI LODR Reg. 30 style events.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

TAGS = [
    ("results", r"financial results|quarterly results|\bq[1-4]\b.*(results|earnings)|\bearnings\b|profit (rises|falls|jumps|drops|declines)"),
    ("dividend", r"dividend|record date|bonus|stock split|buyback|buy-back"),
    ("deal", r"acquisition|acquire|merger|demerger|takeover|stake|open offer|joint venture|\bipo\b|qip|rights issue|preferential"),
    ("people", r"resign|appoint|cessation|ceo|managing director|\bcfo\b|auditor|director\(s\)"),
    ("rating", r"credit rating|rating (upgrade|downgrade)|crisil|icra|care ratings|moody|fitch"),
    ("legal", r"sebi order|penalty|fine|show cause|\bcourt\b|\bnclt\b|lawsuit|tribunal|raid|\bed\b|\bcbi\b|investigation|litigation"),
    ("risk", r"fraud|default|insolvency|pledge|invocation|downgrade|going concern|forensic|delist|suspend|\basm\b|\bgsm\b"),
    ("insider", r"insider|trading window|pit regulations|sast|disclosure under regulation 29|regulation 7"),
]
# announcement subjects that the exchange classifies for us (LODR Reg. 30)
IMPORTANT_DESC = re.compile(r"outcome of board meeting|financial results|change in director|cessation|resignation|"
                            r"acquisition|credit rating|dividend|record date|fraud|default|arrangement|"
                            r"insolvency|litigation|action\(s\) initiated|sale or disposal|delisting", re.I)


def tag(text: str) -> List[str]:
    t = text.lower()
    return [name for name, pat in TAGS if re.search(pat, t)]


def _iso(ts: Optional[str]) -> Optional[str]:
    """NSE '31-Jul-2026 16:31:22' (IST) -> '2026-07-31T16:31:22+05:30' so items sort chronologically."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts.strip(), fmt).replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def from_announcements(rows: List[dict], symbol: str) -> List[dict]:
    out = []
    for r in rows:
        text = f"{r.get('desc', '')} - {r.get('attchmntText') or ''}".strip(" -")
        out.append({"id": f"nse:{r.get('seq_id') or r.get('dt')}", "symbol": symbol.upper(), "source": "NSE announcement",
                    "kind": "filing", "title": text[:240], "url": r.get("attchmntFile"),
                    "time": _iso(r.get("an_dt") or r.get("sort_date")), "tags": tag(text),
                    "important": bool(IMPORTANT_DESC.search(r.get("desc") or ""))})
    return out


def from_rss(xml_text: str, symbol: str, limit: int = 15) -> List[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        try:
            when = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat(timespec="seconds") if pub else None
        except (TypeError, ValueError):
            when = None
        src = item.findtext("source") or ""
        out.append({"id": "rss:" + (item.findtext("guid") or item.findtext("link") or title)[:200], "symbol": symbol.upper(),
                    "source": src or "Google News", "kind": "headline", "title": title, "url": item.findtext("link"),
                    "time": when, "tags": tag(title), "important": False})
        if len(out) >= limit:
            break
    return out


def rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"


def new_only(items: List[dict], seen: Dict[str, str], keep_days: int = 30, now: Optional[datetime] = None):
    """-> (fresh items, updated seen map). `seen` maps id -> ISO time first seen; pruned after keep_days."""
    now = now or datetime.now(timezone.utc)
    kept = {k: v for k, v in seen.items() if (now - datetime.fromisoformat(v)).days < keep_days}
    fresh = []
    for it in items:
        if it["id"] in kept:
            continue
        kept[it["id"]] = now.isoformat(timespec="seconds")
        fresh.append(it)
    return fresh, kept


def fetch_news(symbol: str, company_name: Optional[str], client, http_get: Callable[[str], str],
               from_date: str, to_date: str) -> List[dict]:
    """Announcements (via NSEClient) + headlines (via http_get(url)->text). Either source may fail alone."""
    items, errors = [], []
    try:
        items += from_announcements(client.announcements(symbol, from_date, to_date), symbol)
    except Exception as e:
        errors.append(f"announcements: {e}")
    try:
        q = f'"{company_name}" OR {symbol} share NSE' if company_name else f"{symbol} share NSE"
        items += from_rss(http_get(rss_url(q)), symbol)
    except Exception as e:
        errors.append(f"headlines: {e}")
    return items, errors
