"""Instrument master: one row per tradable symbol, mapped across exchange / ISIN / broker token."""
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Instrument:
    exchange: str
    symbol: str
    name: str = ""
    isin: str = ""
    series: str = "EQ"
    tick_size: float = 0.05
    lot_size: int = 1
    broker_token: str = ""  # e.g. Upstox instrument_key


class InstrumentMaster:
    def __init__(self, instruments=()):
        self._by_key = {(i.exchange, i.symbol): i for i in instruments}

    def get(self, symbol: str, exchange: str = "NSE") -> Optional[Instrument]:
        return self._by_key.get((exchange, symbol))

    def __len__(self):
        return len(self._by_key)

    @classmethod
    def from_csv(cls, path: Path) -> "InstrumentMaster":
        """CSV columns: exchange,symbol,name,isin,series,tick_size,lot_size,broker_token."""
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(Instrument(
                    exchange=r["exchange"], symbol=r["symbol"], name=r.get("name", ""),
                    isin=r.get("isin", ""), series=r.get("series") or "EQ",
                    tick_size=float(r.get("tick_size") or 0.05),
                    lot_size=int(r.get("lot_size") or 1),
                    broker_token=r.get("broker_token", ""),
                ))
        return cls(rows)
