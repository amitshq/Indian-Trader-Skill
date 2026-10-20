"""Fundamentals sources. Phase 2 reads local JSON/CSV; live fetchers (NSE/BSE results XBRL,
screener.in exports, broker APIs) plug in behind the same FundamentalsSource interface."""
import csv
import json
from pathlib import Path
from typing import List

from core import fundamentals as fnd
from core.screener import to_number


class FundamentalsSource:
    source = "base"

    def metrics(self) -> List[dict]:
        raise NotImplementedError


class JsonFundamentals(FundamentalsSource):
    """A file or folder of company JSON (format in core/fundamentals.py). Accepts one company
    object, a list, or {"companies": [...]}."""

    def __init__(self, path):
        self.path = Path(path)
        self.source = f"json:{self.path.name}"

    def _files(self):
        return sorted(self.path.glob("*.json")) if self.path.is_dir() else [self.path]

    def companies(self) -> list:
        out = []
        for f in self._files():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "companies" in data:
                data = data["companies"]
            out.extend(data if isinstance(data, list) else [data])
        return out

    def metrics(self):
        return [fnd.metrics_for(c) for c in self.companies()]


class CsvMetrics(FundamentalsSource):
    """A ready-made metrics table (e.g. a screener.in export). Needs a symbol/ticker column;
    all other columns become metrics. Numbers may carry commas, % and the rupee sign."""

    def __init__(self, path):
        self.path = Path(path)
        self.source = f"csv:{self.path.name}"

    def metrics(self):
        rows = []
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                row = {(k or "").strip(): to_number(v) for k, v in r.items()}
                t = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
                if not t:
                    raise ValueError("a row has no ticker/symbol")
                row["ticker"] = t
                rows.append(row)
        return rows
