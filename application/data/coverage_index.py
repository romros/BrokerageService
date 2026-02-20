"""
Coverage Index — Phase 18.

Mantén un index JSON per símbol amb l'estat de cada mes descarregat.

Layout:
  {root}/historical_parquet/_coverage/{symbol}_tf1m.json

Format:
  {
    "symbol": "EURUSD",
    "timeframe": "1m",
    "last_updated": "2026-02-20T21:00:00Z",
    "months": {
      "2020-01": {
        "status": "done",         # done | failed | empty
        "rows": 31653,
        "coverage_from": 1577836800,
        "coverage_to": 1580515140,
        "last_updated": "2026-02-20T21:00:00Z",
        "retries": 0
      },
      ...
    }
  }

Ús:
    idx = CoverageIndex(root_path="/datafiles", symbol="EURUSD")
    idx.mark_done(year=2020, month=1, rows=31653, coverage_from=..., coverage_to=...)
    summary = idx.summary()
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

COVERAGE_SUBDIR = "_coverage"
TIMEFRAME = "1m"

MonthStatus = Literal["done", "failed", "empty"]


class CoverageIndex:
    """
    Index de cobertura per un símbol/timeframe.

    Thread-safe per a ús seqüencial (un procés). No cal lock si
    s'usa des d'un únic runner async (event loop).
    """

    def __init__(self, root_path: str, symbol: str):
        self._symbol = symbol.upper()
        self._path = (
            Path(root_path)
            / "historical_parquet"
            / COVERAGE_SUBDIR
            / f"{self._symbol}_tf{TIMEFRAME}.json"
        )
        self._data: dict = self._load()

    # ---------------------------------------------------------------------------
    # Load / save
    # ---------------------------------------------------------------------------

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "symbol": self._symbol,
            "timeframe": TIMEFRAME,
            "last_updated": "",
            "months": {},
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data["last_updated"] = datetime.now(timezone.utc).isoformat()
        tmp = self._path.with_suffix(".tmp.json")
        try:
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=2)
            tmp.rename(self._path)
        except OSError:
            if tmp.exists():
                tmp.unlink()
            raise

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    @staticmethod
    def _key(year: int, month: int) -> str:
        return f"{year:04d}-{month:02d}"

    def mark_done(
        self,
        year: int,
        month: int,
        rows: int,
        coverage_from: int,
        coverage_to: int,
        retries: int = 0,
    ) -> None:
        """Marca un mes com a completat."""
        self._data["months"][self._key(year, month)] = {
            "status": "done",
            "rows": rows,
            "coverage_from": coverage_from,
            "coverage_to": coverage_to,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "retries": retries,
        }
        self._save()

    def mark_failed(self, year: int, month: int, retries: int = 0) -> None:
        """Marca un mes com a fallat."""
        key = self._key(year, month)
        existing = self._data["months"].get(key, {})
        self._data["months"][key] = {
            "status": "failed",
            "rows": existing.get("rows", 0),
            "coverage_from": existing.get("coverage_from", 0),
            "coverage_to": existing.get("coverage_to", 0),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "retries": retries,
        }
        self._save()

    def mark_empty(self, year: int, month: int) -> None:
        """Marca un mes com a buit (0 candles; possible mercat tancat/dades no disponibles)."""
        self._data["months"][self._key(year, month)] = {
            "status": "empty",
            "rows": 0,
            "coverage_from": 0,
            "coverage_to": 0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "retries": 0,
        }
        self._save()

    def get_month(self, year: int, month: int) -> Optional[dict]:
        """Retorna info del mes o None si no existeix."""
        return self._data["months"].get(self._key(year, month))

    def is_done(self, year: int, month: int) -> bool:
        """True si el mes té status=done."""
        entry = self.get_month(year, month)
        return entry is not None and entry["status"] == "done"

    def is_failed(self, year: int, month: int) -> bool:
        """True si el mes té status=failed."""
        entry = self.get_month(year, month)
        return entry is not None and entry["status"] == "failed"

    def summary(self) -> dict:
        """Resum: total, done, failed, empty, missing."""
        months = self._data["months"]
        done = sum(1 for v in months.values() if v["status"] == "done")
        failed = sum(1 for v in months.values() if v["status"] == "failed")
        empty = sum(1 for v in months.values() if v["status"] == "empty")
        total_rows = sum(v.get("rows", 0) for v in months.values())
        return {
            "symbol": self._symbol,
            "timeframe": TIMEFRAME,
            "months_total": len(months),
            "months_done": done,
            "months_failed": failed,
            "months_empty": empty,
            "total_rows": total_rows,
            "index_path": str(self._path),
        }

    def months_done(self) -> list[str]:
        """Llista de claus YYYY-MM amb status=done, ordenades."""
        return sorted(k for k, v in self._data["months"].items() if v["status"] == "done")

    def months_failed(self) -> list[str]:
        """Llista de claus YYYY-MM amb status=failed, ordenades."""
        return sorted(k for k, v in self._data["months"].items() if v["status"] == "failed")
