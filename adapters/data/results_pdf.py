"""Best-effort extraction of the quarterly results table from an exchange-filed results PDF.

PDFs are messy (scans, shifted columns, cover letters only), so this FAILS CLOSED: a statement is
accepted only if its period matches, its unit is known, and arithmetic identities hold on the
numbers read from labelled rows. Anything else raises PdfRejected and the caller falls back to
manual entry (adapters/data/manual_results.py). Needs the `pdftotext` binary (poppler).
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december"]
NUM = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


class PdfRejected(Exception):
    pass


def pdf_to_text(data: bytes, max_pages: int = 40) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise PdfRejected("pdftotext (poppler) is not installed")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.pdf"
        src.write_bytes(data)
        r = subprocess.run([exe, "-layout", "-l", str(max_pages), str(src), "-"], capture_output=True, timeout=120)
        if r.returncode != 0 or not r.stdout.strip():
            raise PdfRejected("pdf could not be read as text (damaged or scanned image)")
        return r.stdout.decode("utf-8", errors="replace")


def to_num(tok: str) -> Optional[float]:
    t = tok.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def first_number(s: str) -> Optional[float]:
    m = NUM.search(s)
    return to_num(m.group(0)) if m else None


def _period_present(text: str, period_end: str) -> bool:
    y, mo, d = period_end.split("-")
    month, day = _MONTH_NAMES[int(mo) - 1], int(d)
    t = re.sub(r"\s+", " ", text.lower())
    pat = (rf"(?:quarter|period|months?)\s+ended\s+(?:on\s+)?"
           rf"(?:{day}(?:st|nd|rd|th)?[,.\s]+{month[:3]}\w*[,.\s]+{y}|{month[:3]}\w*[,.\s]+{day}(?:st|nd|rd|th)?,?\s+{y})")
    return re.search(pat, t) is not None


def _unit_factor(block: str) -> float:
    """Multiplier to INR crore. Unknown unit -> reject."""
    b = block.lower()
    if re.search(r"crore", b):
        return 1.0
    if re.search(r"lakh|lac", b):
        return 0.01
    if re.search(r"million", b):
        return 0.1
    raise PdfRejected("cannot tell the unit (crore/lakh/million)")


ROWS = {
    "revenue": r"(?:total\s+)?(?:revenue\s+from\s+operations|net\s+sales|income\s+from\s+operations)\b",
    "other_income": r"other\s+income\b",
    "total_income": r"total\s+income\b",
    "total_expenses": r"total\s+expenses\b",
    "net_profit": (r"(?:net\s+)?profit(?:\s*/\s*\(?loss\)?)?\s+(?:for\s+the\s+(?:period|quarter))?.*attributable\s+to\s*(?:owners|equity\s+holders|shareholders)|"
                   r"net\s+profit(?:\s*/\s*\(?loss\)?)?\s+for\s+the\s+(?:period|quarter)|profit\s+for\s+the\s+(?:period|quarter)\b"),
    "eps": r"(?:basic\s+)?earnings?\s+per\s+(?:equity\s+)?share.*basic|basic\s+(?:earnings?\s+)?per\s+(?:equity\s+)?share",
}


def _rows(page: str) -> dict:
    out = {}
    for line in page.splitlines():
        body = re.sub(r"^\s*(?:\d+\.?|\(?[ivx]+\))\s+", "", line)  # drop row numbering
        for key, pat in ROWS.items():
            m = re.match(rf"\s*{pat}", body, re.I)
            if not m or key in out and out[key] is not None:
                continue
            tail = body[m.end():]
            # row-reference arithmetic printed in labels, e.g. "(1+2)", "(3-4)", "[(i)+(ii)]"
            tail = re.sub(r"[\(\[]\s*\(?(?:\d+|[ivx]+)\)?(?:\s*[+\-]\s*\(?(?:\d+|[ivx]+)\)?)+\s*[\)\]]", " ", tail, flags=re.I)
            tail = re.sub(r"\bnotes?\s*(?:no\.?)?\s*\d+", " ", tail, flags=re.I)  # "Note 3" references
            if key == "eps":  # label may contain "(Rs.)" etc; the figures are the decimals
                toks = re.findall(r"\(?-?\d[\d,]*\.\d+\)?", tail)
            else:
                toks = NUM.findall(tail)
            out[key] = to_num(toks[0]) if toks else None
            out[key + "_cols"] = len(toks)  # a row with fewer columns means a blank cell shifted the values
    return out


def extract_statement(text: str, period_end: str) -> dict:
    """-> {nature, unit_factor, revenue, other_income, total_income, net_profit, eps, checks:[...]} in INR crore.
    Raises PdfRejected with the reason when nothing trustworthy is found."""
    if not _period_present(text, period_end):
        raise PdfRejected(f"document does not say 'quarter/period ended {period_end}'")
    reasons, good = [], {}
    for page in text.split("\f"):
        if "revenue" not in page.lower() and "net sales" not in page.lower():
            continue
        head = "\n".join(page.splitlines()[:30]).lower()
        nature = ("Consolidated" if "consolidated" in head and ("statement" in head or "results" in head)
                  and head.find("consolidated") < (head.find("standalone") if "standalone" in head else 10 ** 9)
                  else "Non-Consolidated" if "standalone" in head else None)
        if nature is None:
            continue
        try:
            factor = _unit_factor("\n".join(page.splitlines()[:40]))
            r = _rows(page)
            for k in ("revenue", "other_income", "total_income", "net_profit", "eps"):
                if r.get(k) is None:
                    raise PdfRejected(f"{nature}: row '{k}' not found with a number on its own line")
            cols = {r[k + "_cols"] for k in ("revenue", "other_income", "total_income", "net_profit", "eps")}
            if len(cols) != 1:   # a blank first column would silently shift every value left
                raise PdfRejected(f"{nature}: rows have different numbers of columns {sorted(cols)}: misaligned table")
            rev, oi, ti = (r[k] * factor for k in ("revenue", "other_income", "total_income"))
            checks = []
            if abs(rev + oi - ti) > max(1.0, 0.001 * abs(ti)):
                raise PdfRejected(f"{nature}: revenue + other income != total income ({rev}+{oi} vs {ti})")
            checks.append("revenue + other income = total income")
            if r.get("total_expenses") is not None:
                pbt_row = re.search(r"profit\s+before\s+exceptional.*?tax[^\n]*?(\(?-?\d[\d,]*(?:\.\d+)?\)?)", page, re.I)
                if pbt_row:
                    pbt = to_num(pbt_row.group(1)) * factor
                    if abs(ti - r["total_expenses"] * factor - pbt) > max(1.0, 0.001 * abs(ti)):
                        raise PdfRejected(f"{nature}: total income - total expenses != profit before exceptional items")
                    checks.append("total income - total expenses = profit before exceptional items")
            np_ = r["net_profit"] * factor
            if abs(np_) > abs(ti) * 1.0:
                raise PdfRejected(f"{nature}: net profit larger than total income")
            good[nature] = {"nature": nature, "revenue": round(rev, 2), "other_income": round(oi, 2),
                            "total_income": round(ti, 2), "net_profit": round(np_, 2), "eps": r["eps"],
                            "unit_factor": factor, "checks": checks,
                            "audited": "Unaudited" if "unaudited" in head else ("Audited" if "audited" in head else None)}
        except PdfRejected as e:
            reasons.append(str(e))
    for nature in ("Consolidated", "Non-Consolidated"):
        if nature in good:
            return good[nature]
    raise PdfRejected("; ".join(reasons) or "no results statement found in the first pages")
