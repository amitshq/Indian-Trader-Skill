"""Exchange-filing source: quarterly results from NSE's filing list + the XBRL file each company
files (the same document the exchange publishes). Gives consolidated/standalone, audited status,
filing time, and exact figures. Unofficial endpoint: NSE can throttle or change it, so every
network call retries, is rate limited, and XBRL files are cached forever (filings are immutable
unless re-filed under a new URL).

Not covered: balance-sheet ratios (ROCE, debt/equity), shareholding / promoter pledge.
"""
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

from core import fundamentals as fnd

from .fundamentals import FundamentalsSource

CRORE = 1e7
BASE = "https://www.nseindia.com"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "nse"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE + "/",
}


class NSEError(Exception):
    pass


class NSEClient:
    def __init__(self, http=None, min_interval: float = 0.4, retries: int = 3,
                 sleep: Callable[[float], None] = time.sleep, cache_dir: Path = CACHE_DIR):
        self._http, self.min_interval, self.retries, self.sleep = http, min_interval, retries, sleep
        self.cache_dir, self._last = Path(cache_dir), 0.0

    def _client(self):
        if self._http is None:
            import httpx
            self._http = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30)
        return self._http

    def _get(self, url: str):
        last = None
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self._client().get(url)
                if r.status_code == 200:
                    return r
                last = f"HTTP {r.status_code}"
            except Exception as e:  # timeouts, resets
                last = f"{type(e).__name__}: {e}"
            self.sleep(1.5 * (attempt + 1))
        raise NSEError(f"{url}: {last}")

    def filings(self, symbol: str, period: str = "Quarterly") -> List[dict]:
        url = (f"{BASE}/api/corporates-financial-results?index=equities"
               f"&symbol={quote(symbol, safe='')}&period={period}")
        try:
            data = self._get(url).json()
        except ValueError as e:
            raise NSEError(f"{symbol}: response was not JSON (blocked or changed endpoint?)") from e
        if not isinstance(data, list):
            raise NSEError(f"{symbol}: unexpected response shape {type(data).__name__}")
        return data

    def announcements(self, symbol: str, from_date: str, to_date: str) -> List[dict]:
        """Corporate announcements (dd-mm-yyyy dates). Fresher than the structured results dataset."""
        url = (f"{BASE}/api/corporate-announcements?index=equities&symbol={quote(symbol, safe='')}"
               f"&from_date={from_date}&to_date={to_date}")
        try:
            data = self._get(url).json()
        except ValueError as e:
            raise NSEError(f"{symbol}: announcements response was not JSON") from e
        return data if isinstance(data, list) else []

    def xbrl(self, url: str) -> str:
        path = self.cache_dir / re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1])
        if path.exists():
            return path.read_text(encoding="utf-8")
        text = self._get(url).text
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text


# ------------------------------------------------------------------ XBRL parsing

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_xbrl(text: str) -> dict:
    """One results filing -> flat dict. Values for the reporting quarter only (not year-to-date),
    money in INR crore, EPS in INR. Raises ValueError if the file has no usable reporting period."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    contexts, facts = {}, {}
    for el in root.iter():
        name = _local(el.tag)
        if name == "context":
            start = end = None
            dims = False
            for sub in el.iter():
                n = _local(sub.tag)
                if n == "startDate":
                    start = sub.text
                elif n == "endDate":
                    end = sub.text
                elif n == "explicitMember" or n == "typedMember":
                    dims = True
            contexts[el.get("id")] = (start, end, dims)
        elif el.get("contextRef") is not None:
            facts.setdefault(name, {})[el.get("contextRef")] = (el.text or "").strip()

    def first(name):  # descriptive facts live in the main (first) context
        d = facts.get(name) or {}
        return next(iter(d.values()), None)

    pstart, pend = first("DateOfStartOfReportingPeriod"), first("DateOfEndOfReportingPeriod")
    if not pend:
        raise ValueError("no reporting period in filing")

    def quarter_len(s, e):
        return s and e and 80 <= (date.fromisoformat(e) - date.fromisoformat(s)).days <= 100

    if pstart:
        ctx = next((cid for cid, (s, e, dims) in contexts.items() if (s, e) == (pstart, pend) and not dims), None)
    else:  # some older filings omit the start date: use the plain 3-month context ending on pend
        ctx = next((cid for cid, (s, e, dims) in contexts.items() if e == pend and not dims and quarter_len(s, e)), None)
        pstart = contexts[ctx][0] if ctx else None
    if ctx is None:
        raise ValueError(f"no context for {pstart}..{pend}")

    def val(name) -> Optional[float]:
        return _num((facts.get(name) or {}).get(ctx))

    def firstval(*names) -> Optional[float]:
        return next((v for v in (val(n) for n in names) if v is not None), None)

    def cr(*names):
        v = firstval(*names)
        return None if v is None else round(v / CRORE, 2)

    revenue, income = cr("RevenueFromOperations"), cr("Income")
    expenses, fin = cr("Expenses"), cr("FinanceCosts")
    op = round(revenue - (expenses - (fin or 0)), 2) if None not in (revenue, expenses) else None
    days = (date.fromisoformat(pend) - date.fromisoformat(pstart)).days
    return {
        "symbol": first("Symbol"), "name": first("NameOfTheCompany") or first("NameOfBank"),
        "period_start": pstart, "period_end": pend, "period_days": days,
        "nature": first("NatureOfReportStandaloneConsolidated"),
        "audited": first("WhetherResultsAreAuditedOrUnaudited"),
        "revenue": revenue if revenue is not None else income,
        "revenue_basis": "revenue_from_operations" if revenue is not None else "total_income",
        "other_income": cr("OtherIncome"), "total_income": income,
        "operating_profit": op,
        "pre_provision_profit": cr("OperatingProfitBeforeProvisionAndContingencies"),  # banks
        "profit_before_tax": cr("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
        "net_profit_total": cr("ProfitLossForPeriod", "ProfitLossForThePeriod"),
        # profit to the parent's shareholders (matches EPS); bank taxonomy uses different tag names
        "net_profit": cr("ProfitOrLossAttributableToOwnersOfParent",
                         "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
                         "ProfitLossForPeriod", "ProfitLossForThePeriod"),
        "eps": firstval("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                        "BasicEarningsPerShareAfterExtraordinaryItems",
                        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                        "DilutedEarningsPerShareAfterExtraordinaryItems"),
    }


# ------------------------------------------------------------------ choosing filings

def _filed_key(f: dict):
    try:
        return int(f.get("seqNumber") or 0)
    except ValueError:
        return 0


def pick_filings(filings: List[dict], max_quarters: int = 6) -> List[dict]:
    """Newest `max_quarters` distinct quarter-ends; per quarter prefer Consolidated over Standalone
    and the latest re-filing. Ignores cumulative (YTD) and non-quarter rows."""
    best: Dict[str, dict] = {}
    for f in filings:
        if (f.get("cumulative") or "").lower().startswith("cumulative"):
            continue
        if not f.get("xbrl") or not (f.get("relatingTo") or "").endswith("Quarter"):
            continue
        end = datetime.strptime(f["toDate"], "%d-%b-%Y").date().isoformat()
        rank = (f.get("consolidated") == "Consolidated", _filed_key(f))
        if end not in best or rank > best[end][0]:
            best[end] = (rank, f)
    return [best[k][1] for k in sorted(best, reverse=True)[:max_quarters]]


def build_company(symbol: str, parsed: List[dict], filings_meta: List[dict]) -> dict:
    """parsed filings (parse_xbrl output, aligned with filings_meta) -> company dict."""
    quarters, natures, warnings = [], set(), []
    for p, meta in zip(parsed, filings_meta):
        if not 80 <= p["period_days"] <= 100:
            warnings.append(f"{p['period_end']}: filing covers {p['period_days']} days, not a quarter; skipped")
            continue
        natures.add(p["nature"])
        quarters.append({
            "period_end": p["period_end"], "revenue": p["revenue"], "operating_profit": p["operating_profit"],
            "net_profit": p["net_profit"], "eps": p["eps"], "nature": p["nature"], "audited": p["audited"],
            "revenue_basis": p["revenue_basis"], "filed": meta.get("exchdisstime"),
        })
    quarters.sort(key=lambda q: q["period_end"])
    if len(natures) > 1:
        warnings.append("mixed standalone/consolidated across quarters: growth rates may not be comparable")
    if any(q["revenue_basis"] == "total_income" for q in quarters):
        warnings.append("revenue is total income (no 'revenue from operations' tag, e.g. banks)")
    name = next((p["name"] for p in parsed if p.get("name")), None)
    return {"symbol": symbol.upper(), "name": name, "sector": None,
            "consolidated": (natures == {"Consolidated"}) if natures else None,
            "quarters": quarters, "annual": [], "ratios": {}, "warnings": warnings}


_PERIOD_RE = re.compile(r"(?:period|quarter|year|half year)\s+ended\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def announced_results(announcements: List[dict]) -> List[dict]:
    """Results the company has told the exchange about (newest first), read from announcement text
    like 'submitted ... the financial results for the period ended Jun 30, 2026'. Only quarter-end
    dates (Mar/Jun/Sep/Dec). Each: {period_end, announced_at, url}. The PDF is the source of truth."""
    out = {}
    for a in announcements:
        text = a.get("attchmntText") or ""
        if "financial result" not in text.lower() and "results" not in text.lower():
            continue
        m = _PERIOD_RE.search(text)
        if not m:
            continue
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon not in fnd.Q_END_MONTHS:
            continue
        try:
            end = date(int(m.group(3)), mon, int(m.group(2))).isoformat()
        except ValueError:
            continue
        cur = out.get(end)
        if cur is None or a.get("an_dt", "") < cur["announced_at"]:   # keep the earliest announcement
            out[end] = {"period_end": end, "announced_at": a.get("an_dt"), "url": a.get("attchmntFile")}
    return [out[k] for k in sorted(out, reverse=True)]


class NSEResults(FundamentalsSource):
    """Quarterly results from exchange filings. Cached 12h for the filing list; XBRL cached forever."""
    source = "NSE filings (XBRL)"

    def __init__(self, symbols: List[str], client: Optional[NSEClient] = None, max_quarters: int = 6,
                 cache_dir: Path = CACHE_DIR, ttl_hours: float = 12, manual_dir: Optional[Path] = None):
        self.manual_dir = manual_dir
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.client, self.max_quarters = client or NSEClient(cache_dir=cache_dir), max_quarters
        self.cache_dir, self.ttl = Path(cache_dir), ttl_hours * 3600
        self.errors: Dict[str, str] = {}

    def company(self, symbol: str) -> Optional[dict]:
        """Exchange filings plus any human-verified quarters entered from results PDFs."""
        from . import manual_results as mr
        comp = self._fetch_company(symbol)
        entries = mr.load_entries(symbol, self.manual_dir or mr.MANUAL_DIR)
        if comp is None and entries:  # no structured filings at all, but the user entered results
            comp = {"symbol": symbol.upper(), "name": None, "sector": None, "consolidated": None, "quarters": [],
                    "annual": [], "ratios": {}, "warnings": [], "meta": {"data_source": "manual-pdf"}}
            self.errors.pop(symbol, None)
        return mr.merge_into(comp, entries) if comp else None

    def _fetch_company(self, symbol: str) -> Optional[dict]:
        cp = self.cache_dir / ("company_" + re.sub(r"[^A-Za-z0-9]", "_", symbol) + ".json")
        if cp.exists():
            c = json.loads(cp.read_text(encoding="utf-8"))
            if time.time() - c["ts"] < self.ttl:
                return c["company"]
        try:
            picked = pick_filings(self.client.filings(symbol), self.max_quarters)
            if not picked:
                raise NSEError("no quarterly result filings listed")
            parsed, metas = [], []
            for f in picked:
                try:
                    parsed.append(parse_xbrl(self.client.xbrl(f["xbrl"])))
                    metas.append(f)
                except (ValueError, ET.ParseError) as e:
                    self.errors[f"{symbol}:{f['toDate']}"] = f"unparseable filing: {e}"
            if not parsed:
                raise NSEError("no filing could be parsed")
            comp = build_company(symbol, parsed, metas)
        except NSEError as e:
            self.errors[symbol] = str(e)
            return None
        try:  # which results has the exchange been told about? (the structured dataset can lag badly)
            today = date.today()
            frm = date(today.year - 1, today.month, 1).strftime("%d-%m-%Y")
            comp["announced"] = announced_results(self.client.announcements(symbol, frm, today.strftime("%d-%m-%Y")))[:4]
        except NSEError as e:
            self.errors[f"{symbol}:announcements"] = str(e)
        try:  # promoter holding from the latest SEBI shareholding-pattern filing
            from .nse_market import NSEMarket, promoter_signals
            comp["ratios"].update(promoter_signals(NSEMarket(self.client).shareholding(symbol)))
        except NSEError as e:
            self.errors[f"{symbol}:shareholding"] = str(e)
        comp["meta"] = {"data_source": "nse-xbrl", "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"ts": time.time(), "company": comp}), encoding="utf-8")
        return comp

    def metrics(self):
        return [fnd.metrics_for(c) for c in (self.company(s) for s in self.symbols) if c]
