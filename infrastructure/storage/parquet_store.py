"""
ParquetCandleStore — storage històric OHLCV en format Parquet particionat.

Phase 15: Parquet storage per backtests de llarg termini (2003→avui).

Layout:
  {root}/historical_parquet/{symbol}/tf=1m/year={YYYY}/month={MM}/data.parquet

Cada fitxer = 1 mes. Escriptura idempotent (overwrite).
Validació: timestamps monotònics, delta=60s, no duplicats.

Dependència: pyarrow (ja disponible via pandas en entorns típics).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from domain.models import Candle
from foundation.logging import get_logger

logger = get_logger(__name__)

PARQUET_SUBDIR = "historical_parquet"
TIMEFRAME = "1m"


class ParquetCandleStore:
    """
    Storage Parquet particionat per mes.

    Ús:
        store = ParquetCandleStore(root_path="/datafiles")
        store.write_month("EURUSD", 2003, 1, candles)
        candles = store.read_month("EURUSD", 2003, 1)
    """

    def __init__(self, root_path: str):
        self._root = Path(root_path) / PARQUET_SUBDIR

    def _partition_path(self, symbol: str, year: int, month: int) -> Path:
        return (
            self._root
            / symbol.upper()
            / f"tf={TIMEFRAME}"
            / f"year={year:04d}"
            / f"month={month:02d}"
            / "data.parquet"
        )

    def write_month(
        self,
        symbol: str,
        year: int,
        month: int,
        candles: List[Candle],
        *,
        validate: bool = True,
    ) -> Path:
        """
        Escriu (o sobreescriu) la partició mensual. Idempotent.

        Retorna el path del fitxer escrit.
        Llança ValueError si validate=True i les dades no passen la validació.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        if validate and candles:
            _validate_candles(candles)

        out_path = self._partition_path(symbol, year, month)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Escriptura atòmica: temp → rename
        tmp_path = out_path.with_suffix(".tmp.parquet")
        try:
            table = _candles_to_arrow(candles)
            pq.write_table(table, str(tmp_path), compression="snappy")
            tmp_path.rename(out_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        logger.info(
            "parquet_store WRITE symbol=%s year=%d month=%02d candles=%d path=%s",
            symbol, year, month, len(candles), out_path,
        )
        return out_path

    def read_month(
        self,
        symbol: str,
        year: int,
        month: int,
    ) -> List[Candle]:
        """
        Llegeix una partició mensual. Retorna [] si no existeix.
        """
        import pyarrow.parquet as pq

        path = self._partition_path(symbol, year, month)
        if not path.exists():
            return []
        table = pq.read_table(str(path))
        return _arrow_to_candles(table, symbol)

    def read_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Llegeix candles per rang de temps combinant particions mensuals.

        Filtra per start <= ts < end.
        """
        result: List[Candle] = []
        # Itera pels mesos que cobreix el rang
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            month_candles = self.read_month(symbol, y, m)
            for c in month_candles:
                ts = c.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if start <= ts < end:
                    result.append(c)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return result

    def has_month(self, symbol: str, year: int, month: int) -> bool:
        """True si existeix la partició mensual."""
        return self._partition_path(symbol, year, month).exists()

    def coverage(self, symbol: str) -> list[dict]:
        """
        Retorna llista de {year, month, candles_count} per particions existents.
        """
        result = []
        base = self._root / symbol.upper() / f"tf={TIMEFRAME}"
        if not base.exists():
            return result
        for year_dir in sorted(base.iterdir()):
            if not year_dir.name.startswith("year="):
                continue
            year = int(year_dir.name.split("=")[1])
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.name.startswith("month="):
                    continue
                month = int(month_dir.name.split("=")[1])
                data_file = month_dir / "data.parquet"
                if data_file.exists():
                    candles = self.read_month(symbol, year, month)
                    result.append({"year": year, "month": month, "candles_count": len(candles)})
        return result


# ---------------------------------------------------------------------------
# Conversió Candle ↔ Arrow
# ---------------------------------------------------------------------------

def _candles_to_arrow(candles: List[Candle]):
    import pyarrow as pa

    ts_list = [int(c.timestamp.timestamp()) for c in candles]
    return pa.table({
        "ts": pa.array(ts_list, type=pa.int64()),
        "open": pa.array([c.open for c in candles], type=pa.float64()),
        "high": pa.array([c.high for c in candles], type=pa.float64()),
        "low": pa.array([c.low for c in candles], type=pa.float64()),
        "close": pa.array([c.close for c in candles], type=pa.float64()),
        "volume": pa.array([c.volume for c in candles], type=pa.float64()),
    })


def _arrow_to_candles(table, symbol: str) -> List[Candle]:
    ts_col = table.column("ts").to_pylist()
    open_col = table.column("open").to_pylist()
    high_col = table.column("high").to_pylist()
    low_col = table.column("low").to_pylist()
    close_col = table.column("close").to_pylist()
    vol_col = table.column("volume").to_pylist()
    candles = []
    for ts, o, h, l, c, v in zip(ts_col, open_col, high_col, low_col, close_col, vol_col):
        candles.append(Candle(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
            open=o, high=h, low=l, close=c, volume=v,
            is_closed=True,
        ))
    return candles


# ---------------------------------------------------------------------------
# Validació
# ---------------------------------------------------------------------------

def _validate_candles(candles: List[Candle]) -> None:
    """
    Valida monotonia, delta=60s i absència de duplicats.
    Llança ValueError si hi ha problemes.
    """
    if not candles:
        return
    ts_list = [int(c.timestamp.timestamp()) for c in candles]

    # Duplicats
    seen = set()
    for ts in ts_list:
        if ts in seen:
            raise ValueError(f"parquet_store: candle duplicada ts={ts}")
        seen.add(ts)

    # Monotonia i delta
    for i in range(1, len(ts_list)):
        delta = ts_list[i] - ts_list[i - 1]
        if delta <= 0:
            raise ValueError(
                f"parquet_store: timestamps no monotònics: {ts_list[i-1]} → {ts_list[i]}"
            )
        if delta != 60:
            # Gap (no és error fatal — registrem warning)
            logger.debug(
                "parquet_store: gap detectat ts=%d→%d delta=%ds", ts_list[i-1], ts_list[i], delta
            )
