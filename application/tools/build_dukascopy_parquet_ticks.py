"""
build_dukascopy_parquet_ticks.py — BS.T9.13

Builder CLI: construeix Parquet v2 (ticks→M1, paritat SQ) des del provider de ticks.

Flow:
  Bi5TicksBackfillProvider (xarxa primera vegada, cache local després)
    → List[Candle] M1 per mes
    → Parquet atòmic a {DUKASCOPY_PARQUET_TICKS_ROOT}

Layout v2:
  {root}/historical_parquet_ticks_v1/{SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet

Guardrails:
  - No-delete: mai toca historical_parquet legacy
  - Atomic: .tmp.parquet → rename per mes
  - Skip si ja existeix (--force per sobreescriure)
  - Cache ticks local: {DATAFILES_ROOT}/dukascopy_ticks_cache/ (reutilitzable)

Ús:
  python3 application/tools/build_dukascopy_parquet_ticks.py \\
      --symbol EURUSD \\
      --from 2025-03-01 --to 2025-04-01 \\
      --out-root /datafiles/historical_parquet_ticks_v1 \\
      --raw-root /datafiles \\
      --timeframe 1m

  # Dry-run (no escriu parquet)
  python3 application/tools/build_dukascopy_parquet_ticks.py \\
      --symbol EURUSD --from 2025-03-01 --to 2025-04-01 \\
      --dry-run

  # Force overwrite
  python3 application/tools/build_dukascopy_parquet_ticks.py \\
      --symbol EURUSD --from 2025-03-01 --to 2025-04-01 \\
      --force

Artifacts:
  --artifacts-dir: si donat, escriu month_report.json, coverage.json i reopen_window.csv
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from foundation.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARQUET_TICKS_SUBDIR = "historical_parquet_ticks_v1"
TIMEFRAME = "1m"

# Env var per activar v2 al query layer (llegit per DuckDBQueryService ampliada)
ENV_PARQUET_ACTIVE = "DUKASCOPY_PARQUET_ACTIVE"
ENV_PARQUET_TICKS_ROOT = "DUKASCOPY_PARQUET_TICKS_ROOT"


# ---------------------------------------------------------------------------
# ParquetTicksStore — escriptura v2 atòmica
# ---------------------------------------------------------------------------

class ParquetTicksStore:
    """
    Store Parquet v2 (ticks→M1). Root separat del legacy.

    Layout: {root}/{SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet
    """

    def __init__(self, root_path: str):
        self._root = Path(root_path)

    def _partition_path(self, symbol: str, year: int, month: int) -> Path:
        return (
            self._root
            / symbol.upper()
            / f"tf={TIMEFRAME}"
            / f"year={year:04d}"
            / f"month={month:02d}"
            / "data.parquet"
        )

    def has_month(self, symbol: str, year: int, month: int) -> bool:
        """True si existeix la partició I té dades (num_rows > 0)."""
        import pyarrow.parquet as pq
        path = self._partition_path(symbol, year, month)
        if not path.exists():
            return False
        try:
            meta = pq.read_metadata(str(path))
            return meta.num_rows > 0
        except Exception:
            return False

    def write_month(
        self,
        symbol: str,
        year: int,
        month: int,
        candles: List[Candle],
    ) -> Optional[Path]:
        """
        Escriu la partició mensual v2 de forma atòmica (.tmp → rename).
        Retorna el path escrit, o None si candles=[].
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not candles:
            logger.debug("ParquetTicksStore SKIP_EMPTY symbol=%s %d/%02d", symbol, year, month)
            return None

        out_path = self._partition_path(symbol, year, month)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = out_path.with_suffix(".tmp.parquet")
        try:
            ts_list = [int(c.timestamp.timestamp()) for c in candles]
            table = pa.table({
                "ts":     pa.array(ts_list,                          type=pa.int64()),
                "open":   pa.array([c.open   for c in candles],     type=pa.float64()),
                "high":   pa.array([c.high   for c in candles],     type=pa.float64()),
                "low":    pa.array([c.low    for c in candles],     type=pa.float64()),
                "close":  pa.array([c.close  for c in candles],     type=pa.float64()),
                "volume": pa.array([c.volume for c in candles],     type=pa.float64()),
            })
            pq.write_table(table, str(tmp_path), compression="snappy")
            tmp_path.rename(out_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        logger.info(
            "ParquetTicksStore WRITE symbol=%s %d/%02d candles=%d path=%s",
            symbol, year, month, len(candles), out_path,
        )
        return out_path

    def coverage(self, symbol: str) -> list[dict]:
        """Llista particions existents amb comptatge."""
        import pyarrow.parquet as pq
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
                    try:
                        meta = pq.read_metadata(str(data_file))
                        result.append({"year": year, "month": month, "candles_count": meta.num_rows})
                    except Exception:
                        result.append({"year": year, "month": month, "candles_count": -1})
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _months_in_range(from_date: str, to_date: str) -> List[Tuple[int, int]]:
    """Retorna llista de (year, month) entre from_date i to_date (exclusiu mes final)."""
    d_from = datetime.strptime(from_date, "%Y-%m-%d")
    d_to   = datetime.strptime(to_date,   "%Y-%m-%d")
    months = []
    y, m = d_from.year, d_from.month
    while (y, m) < (d_to.year, d_to.month) or (y == d_to.year and m == d_to.month and d_to.day > 1):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
        # Parar si hem superat el mes inicial de d_to (d_to és exclusiu)
        if (y, m) > (d_to.year, d_to.month):
            break
        if y == d_to.year and m == d_to.month and d_to.day == 1:
            break
    return months


def _month_range_utc(year: int, month: int) -> Tuple[datetime, datetime]:
    """Retorna (start, end) UTC per un mes complet."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 0, tzinfo=timezone.utc) + timedelta(minutes=1)
    return start, end


def _compute_gaps(candles: List[Candle]) -> List[dict]:
    """Retorna llista de gaps > 60s entre candles consecutives."""
    gaps = []
    for i in range(1, len(candles)):
        delta = int((candles[i].timestamp - candles[i - 1].timestamp).total_seconds())
        if delta > 60:
            gaps.append({
                "from_ts": int(candles[i - 1].timestamp.timestamp()),
                "to_ts":   int(candles[i].timestamp.timestamp()),
                "gap_s":   delta,
                "gap_min": delta // 60,
            })
    return gaps


def _month_report(
    symbol: str,
    year: int,
    month: int,
    candles: List[Candle],
    written_path: Optional[Path],
) -> dict:
    """Genera el report d'un mes."""
    gaps = _compute_gaps(candles) if candles else []
    return {
        "symbol":     symbol,
        "year":       year,
        "month":      month,
        "candles":    len(candles),
        "first_ts":   int(candles[0].timestamp.timestamp())  if candles else None,
        "last_ts":    int(candles[-1].timestamp.timestamp()) if candles else None,
        "gap_count":  len(gaps),
        "gap_total_min": sum(g["gap_min"] for g in gaps),
        "gaps":       gaps[:20],  # primeres 20 per brevitat
        "written":    str(written_path) if written_path else None,
    }


def _reopen_window_sample(candles: List[Candle]) -> List[dict]:
    """
    Extreu una finestra de reobertura de diumenge (21:55–22:10 UTC).
    Cerca el primer diumenge del lot amb candles en aquella finestra.
    """
    import calendar as cal
    sample = []
    for c in candles:
        ts = c.timestamp
        if ts.weekday() == 6:  # diumenge (0=dilluns, 6=diumenge)
            h, mi = ts.hour, ts.minute
            if (h == 21 and mi >= 55) or (h == 22 and mi <= 10):
                sample.append({
                    "ts":    int(ts.timestamp()),
                    "ts_iso": ts.isoformat(),
                    "open":  c.open,
                    "high":  c.high,
                    "low":   c.low,
                    "close": c.close,
                })
        if len(sample) >= 20:
            break
    return sample


# ---------------------------------------------------------------------------
# Builder principal
# ---------------------------------------------------------------------------

async def build_months(
    symbol: str,
    months: List[Tuple[int, int]],
    store: ParquetTicksStore,
    datafiles_root: str,
    dry_run: bool = False,
    force: bool = False,
    rate_limit_s: float = 0.05,
) -> List[dict]:
    """
    Construeix Parquet v2 per una llista de mesos.
    Retorna llista de month_reports.
    """
    from infrastructure.venues.dukascopy.bi5_ticks_backfill_provider import Bi5TicksBackfillProvider

    provider = Bi5TicksBackfillProvider(
        datafiles_root=datafiles_root,
        rate_limit_s=rate_limit_s,
    )

    reports = []
    for year, month in months:
        sym = symbol.upper()

        # Skip si ja existeix (i no --force)
        if not force and store.has_month(sym, year, month):
            logger.info("SKIP (ja existeix) %s %d/%02d", sym, year, month)
            reports.append({
                "symbol": sym, "year": year, "month": month,
                "status": "skipped", "candles": None,
            })
            continue

        start, end = _month_range_utc(year, month)
        logger.info("BUILD %s %d/%02d [%s → %s]...", sym, year, month, start.date(), end.date())

        try:
            candles = await provider.fetch_ohlcv(sym, start, end)
        except Exception as e:
            logger.error("ERROR fetch %s %d/%02d: %s", sym, year, month, e)
            reports.append({
                "symbol": sym, "year": year, "month": month,
                "status": "error", "error": str(e), "candles": 0,
            })
            continue

        written = None
        if not dry_run and candles:
            written = store.write_month(sym, year, month, candles)

        report = _month_report(sym, year, month, candles, written)
        report["status"] = "dry_run" if dry_run else ("written" if written else "empty")
        reports.append(report)

        logger.info(
            "  → %d candles, %d gaps, status=%s",
            len(candles), report["gap_count"], report["status"],
        )

    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    import os
    parser = argparse.ArgumentParser(
        description="Builder Parquet v2 Dukascopy ticks→M1 (BS.T9.13)",
    )
    parser.add_argument("--symbol",    default="EURUSD", help="Símbol (default: EURUSD)")
    parser.add_argument("--from",      dest="from_date", required=True,
                        help="Data inici YYYY-MM-DD (inclusiu)")
    parser.add_argument("--to",        dest="to_date",   required=True,
                        help="Data fi YYYY-MM-DD (exclusiu — primer dia mes fora)")
    parser.add_argument("--out-root",  default=None,
                        help=f"Root Parquet v2 (default: $DATAFILES_ROOT/{PARQUET_TICKS_SUBDIR})")
    parser.add_argument("--raw-root",  default=None,
                        help="DATAFILES_ROOT per al cache ticks (default: env DATAFILES_ROOT o /datafiles)")
    parser.add_argument("--timeframe", default="1m", help="Timeframe (default: 1m)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="No escriu parquet; mostra el que faria")
    parser.add_argument("--force",     action="store_true",
                        help="Sobreescriu particions ja existents")
    parser.add_argument("--artifacts-dir", default=None,
                        help="Dir per guardar month_report.json, coverage.json, reopen_window.csv")
    parser.add_argument("--rate-limit-s", type=float, default=0.05,
                        help="Pausa entre requests HTTP (default: 0.05s = 20 req/s)")
    return parser.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    import os

    datafiles_root = args.raw_root or os.getenv("DATAFILES_ROOT", "/datafiles")
    out_root = args.out_root or os.path.join(
        os.getenv("DATAFILES_ROOT", "/datafiles"),
        PARQUET_TICKS_SUBDIR,
    )

    store = ParquetTicksStore(root_path=out_root)

    months = _months_in_range(args.from_date, args.to_date)
    if not months:
        print(f"ERROR: cap mes en el rang {args.from_date} → {args.to_date}")
        return 1

    print(f"[T9.13] Builder Parquet v2 ticks→M1")
    print(f"  symbol:       {args.symbol.upper()}")
    print(f"  rang:         {args.from_date} → {args.to_date}")
    print(f"  mesos:        {len(months)} ({months[0]} → {months[-1]})")
    print(f"  out_root:     {out_root}")
    print(f"  datafiles:    {datafiles_root}")
    print(f"  dry_run:      {args.dry_run}")
    print(f"  force:        {args.force}")
    if args.artifacts_dir:
        print(f"  artifacts:    {args.artifacts_dir}")
    print()

    reports = await build_months(
        symbol=args.symbol,
        months=months,
        store=store,
        datafiles_root=datafiles_root,
        dry_run=args.dry_run,
        force=args.force,
        rate_limit_s=args.rate_limit_s,
    )

    # Resum final
    written  = sum(1 for r in reports if r.get("status") == "written")
    skipped  = sum(1 for r in reports if r.get("status") == "skipped")
    empty    = sum(1 for r in reports if r.get("status") == "empty")
    errors   = sum(1 for r in reports if r.get("status") == "error")
    dry_rns  = sum(1 for r in reports if r.get("status") == "dry_run")
    total_candles = sum(r.get("candles") or 0 for r in reports)

    print(f"\n=== RESUM ===")
    print(f"  escrit:   {written}")
    print(f"  saltats:  {skipped}")
    print(f"  buits:    {empty}")
    print(f"  errors:   {errors}")
    if args.dry_run:
        print(f"  dry_run:  {dry_rns}")
    print(f"  candles totals: {total_candles:,}")

    # Coverage actual
    cov = store.coverage(args.symbol.upper())
    total_cov_candles = sum(e["candles_count"] for e in cov)
    print(f"\n=== COVERAGE v2 ({args.symbol.upper()}) ===")
    print(f"  particions: {len(cov)}")
    print(f"  candles:    {total_cov_candles:,}")

    # Artifacts
    if args.artifacts_dir:
        artifacts_dir = Path(args.artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # month_report.json
        month_report_path = artifacts_dir / "pilot_build_month_report.json"
        with open(month_report_path, "w") as f:
            json.dump(reports, f, indent=2)
        print(f"\nArtifact: {month_report_path}")

        # coverage.json
        coverage_path = artifacts_dir / "pilot_coverage.json"
        with open(coverage_path, "w") as f:
            json.dump({
                "symbol": args.symbol.upper(),
                "out_root": out_root,
                "total_partitions": len(cov),
                "total_candles": total_cov_candles,
                "partitions": cov,
            }, f, indent=2)
        print(f"Artifact: {coverage_path}")

        # reopen_window.csv — busquem finestra diumenge 21:55–22:10 UTC
        reopen_rows = []
        for r in reports:
            if r.get("status") not in ("written", "dry_run"):
                continue
            # Hem de llegir les candles del mes per trobar la finestra
            # (ja les teníem però no les guardem; llegim del parquet si existeix)
            if not args.dry_run:
                import pyarrow.parquet as pq
                sym = args.symbol.upper()
                part_path = store._partition_path(sym, r["year"], r["month"])
                if part_path.exists():
                    try:
                        table = pq.read_table(str(part_path))
                        ts_col    = table.column("ts").to_pylist()
                        open_col  = table.column("open").to_pylist()
                        high_col  = table.column("high").to_pylist()
                        low_col   = table.column("low").to_pylist()
                        close_col = table.column("close").to_pylist()
                        from domain.models import Candle
                        candles = [
                            Candle(
                                symbol=sym,
                                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                                open=o, high=h, low=l, close=c, volume=0.0,
                                is_closed=True,
                            )
                            for ts, o, h, l, c in zip(ts_col, open_col, high_col, low_col, close_col)
                        ]
                        reopen_rows.extend(_reopen_window_sample(candles))
                    except Exception as e:
                        logger.warning("reopen sample error %d/%02d: %s", r["year"], r["month"], e)

        reopen_path = artifacts_dir / "pilot_reopen_window.csv"
        import csv
        with open(reopen_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ts", "ts_iso", "open", "high", "low", "close"])
            writer.writeheader()
            writer.writerows(reopen_rows[:50])
        print(f"Artifact: {reopen_path} ({len(reopen_rows)} files)")

        # run.log summary
        run_log_path = artifacts_dir / "run.log"
        with open(run_log_path, "a") as f:
            from datetime import datetime as dt
            f.write(f"\n--- {dt.utcnow().isoformat()}Z ---\n")
            f.write(f"symbol={args.symbol.upper()} rang={args.from_date}→{args.to_date}\n")
            f.write(f"escrit={written} saltats={skipped} errors={errors} candles={total_candles}\n")
            f.write(f"out_root={out_root}\n")
        print(f"Artifact: {run_log_path}")

    return 0 if errors == 0 else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
