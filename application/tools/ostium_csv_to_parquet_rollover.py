"""
Ostium CSV → Parquet rollover — TASCA 2: retenció durable.

Llegeix candles Ostium del CSV (realtime_datalayer) i les persisteix a Parquet
per garantir que cap dada live es perdi. Format idèntic a Parquet v2 (Dukascopy).

Layout: {out_root}/{SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet

Ús:
    python3 -m application.tools.ostium_csv_to_parquet_rollover \\
        --from 2026-03-16 --to 2026-03-17 --symbol EURUSD

    # Cron diari (ahir)
    python3 -m application.tools.ostium_csv_to_parquet_rollover \\
        --from $(date -u -d yesterday +%Y-%m-%d) \\
        --to $(date -u +%Y-%m-%d) \\
        --symbol EURUSD
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from domain.models import Candle
from foundation.config.constants import (
    OSTIUM_BROKER_SUBDIR,
    OSTIUM_CANONICAL_TZ,
    OSTIUM_PARQUET_SUBDIR,
    REALTIME_DATALAYER_SUBDIR,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

TIMEFRAME = "1m"


def _read_csv_candles(
    symbol: str,
    start: datetime,
    end: datetime,
    datafiles_root: str,
) -> List[Candle]:
    """Llegeix candles del CSV store Ostium."""
    from infrastructure.storage.csv_store import CSVCandleStore

    ostium_root = str(Path(datafiles_root) / REALTIME_DATALAYER_SUBDIR)
    store = CSVCandleStore(
        root_path=ostium_root,
        broker=OSTIUM_BROKER_SUBDIR,
        canonical_tz=OSTIUM_CANONICAL_TZ,
    )
    result = store.read_range(symbol, start, end, validate_gaps=False)
    return result.candles


def _read_existing_parquet(
    symbol: str,
    year: int,
    month: int,
    out_root: Path,
) -> List[Candle]:
    """Llegeix candles existents d'una partició Parquet (si existeix)."""
    import pyarrow.parquet as pq  # lazy import to reduce startup cost (AGENTS §6.1)

    path = (
        out_root
        / symbol.upper()
        / f"tf={TIMEFRAME}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "data.parquet"
    )
    if not path.exists():
        return []
    try:
        table = pq.read_table(str(path))
        candles = []
        for i in range(table.num_rows):
            ts = table.column("ts")[i].as_py()
            candles.append(
                Candle(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=table.column("open")[i].as_py(),
                    high=table.column("high")[i].as_py(),
                    low=table.column("low")[i].as_py(),
                    close=table.column("close")[i].as_py(),
                    volume=table.column("volume")[i].as_py(),
                    is_closed=True,
                )
            )
        return candles
    except Exception as e:
        logger.warning("read_existing_parquet %s %d/%02d: %s", symbol, year, month, e)
        return []


def _write_month(
    symbol: str,
    year: int,
    month: int,
    candles: List[Candle],
    out_root: Path,
) -> int:
    """Escriu partició mensual (merge amb existent si cal). Retorna candles escrites."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not candles:
        return 0

    out_path = (
        out_root
        / symbol.upper()
        / f"tf={TIMEFRAME}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "data.parquet"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Merge amb existent (dedup per ts, preferència a candles noves)
    existing = _read_existing_parquet(symbol, year, month, out_root)
    by_ts = {int(c.timestamp.timestamp()): c for c in existing}
    for c in candles:
        by_ts[int(c.timestamp.timestamp())] = c
    merged = sorted(by_ts.values(), key=lambda c: c.timestamp)

    tmp_path = out_path.with_suffix(".tmp.parquet")
    try:
        ts_list = [int(c.timestamp.timestamp()) for c in merged]
        table = pa.table({
            "ts": pa.array(ts_list, type=pa.int64()),
            "open": pa.array([c.open for c in merged], type=pa.float64()),
            "high": pa.array([c.high for c in merged], type=pa.float64()),
            "low": pa.array([c.low for c in merged], type=pa.float64()),
            "close": pa.array([c.close for c in merged], type=pa.float64()),
            "volume": pa.array([c.volume for c in merged], type=pa.float64()),
        })
        pq.write_table(table, str(tmp_path), compression="snappy")
        tmp_path.rename(out_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    logger.info(
        "ostium_rollover WRITE symbol=%s %d/%02d candles=%d path=%s",
        symbol, year, month, len(merged), out_path,
    )
    return len(merged)


def run_rollover(
    from_date: str,
    to_date: str,
    symbol: str,
    datafiles_root: str,
    out_root: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Executa rollover CSV → Parquet per un rang de dates.

    Returns:
        {"symbol": str, "from": str, "to": str, "months_written": int, "candles_written": int, "dry_run": bool}
    """
    start = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if start >= end:
        return {"symbol": symbol, "from": from_date, "to": to_date, "months_written": 0, "candles_written": 0, "dry_run": dry_run}

    if out_root is None:
        out_root = str(Path(datafiles_root) / OSTIUM_PARQUET_SUBDIR)
    out_path = Path(out_root)

    candles = _read_csv_candles(symbol, start, end, datafiles_root)
    if not candles:
        logger.info("ostium_rollover symbol=%s range=%s..%s: 0 candles (skip)", symbol, from_date, to_date)
        return {"symbol": symbol, "from": from_date, "to": to_date, "months_written": 0, "candles_written": 0, "dry_run": dry_run}

    # Agrupar per mes
    by_month: dict[tuple[int, int], list[Candle]] = {}
    for c in candles:
        key = (c.timestamp.year, c.timestamp.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(c)

    total_written = 0
    if not dry_run:
        for (year, month), month_candles in sorted(by_month.items()):
            n = _write_month(symbol, year, month, month_candles, out_path)
            total_written += n
    else:
        for (year, month), month_candles in sorted(by_month.items()):
            total_written += len(month_candles)
        logger.info("ostium_rollover DRY-RUN symbol=%s months=%d candles=%d", symbol, len(by_month), total_written)

    return {
        "symbol": symbol,
        "from": from_date,
        "to": to_date,
        "months_written": len(by_month),
        "candles_written": total_written,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ostium CSV → Parquet rollover (retenció durable)")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi (YYYY-MM-DD, exclusiva)")
    parser.add_argument("--symbol", default="EURUSD", help="Símbol (default: EURUSD)")
    parser.add_argument("--datafiles-root", default="/datafiles", help="Arrel datafiles")
    parser.add_argument("--out-root", default=None, help="Arrel Parquet Ostium (default: datafiles/historical_parquet_ostium_v1)")
    parser.add_argument("--dry-run", action="store_true", help="No escriure, només mostrar")
    args = parser.parse_args()

    import os
    datafiles_root = os.getenv("DATAFILES_ROOT", args.datafiles_root)

    result = run_rollover(
        from_date=args.from_date,
        to_date=args.to_date,
        symbol=args.symbol,
        datafiles_root=datafiles_root,
        out_root=args.out_root,
        dry_run=args.dry_run,
    )
    print(f"ostium_rollover: {result}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
