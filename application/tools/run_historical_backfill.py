"""
Historical Backfill Runner — Phase 15/18.

Descarrega candles 1m de Dukascopy i les emmagatzema en Parquet particionat per mes.

Phase 18 — ops robustos:
- Coverage index actualitzat per mes (status: done/failed/empty)
- Retries/backoff per errors transitoris de fetch
- Flags: --dry-run, --stop-after N, --retries N, --backoff-base, --retry-failed
- Resume per defecte (salta mesos ja en coverage index com a done)

Idempotent: rerun no duplica particions existents.
Rate-limit: sleep configurable entre peticions.

Ús CLI:
    python3 application/tools/run_historical_backfill.py \\
        --symbol EURUSD --from 2003-01-01 --to 2003-12-31

    # Backfill llarg: 2 mesos de prova primer
    python3 application/tools/run_historical_backfill.py \\
        --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --stop-after 2

    # Reprendre (salta mesos done, reintenta failed)
    python3 application/tools/run_historical_backfill.py \\
        --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --retry-failed

Ús programàtic (per tests 0-network):
    result = await run_historical_backfill(
        symbol="EURUSD",
        from_date=date(2003, 1, 1),
        to_date=date(2003, 1, 31),
        datafiles_root="/tmp/test",
        dukascopy_override=fake_candles,
    )
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from domain.models import Candle
from foundation.logging import get_logger
from infrastructure.storage.parquet_store import ParquetCandleStore

logger = get_logger(__name__)

DEFAULT_SLEEP_S = 1.0
DEFAULT_DATAFILES_ROOT = "/datafiles"
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0
DEFAULT_BACKOFF_MAX = 30.0


# ---------------------------------------------------------------------------
# Helpers temporals
# ---------------------------------------------------------------------------

def _months_in_range(from_date: date, to_date: date) -> list[tuple[int, int]]:
    """Retorna llista de (year, month) que cobreix el rang [from_date, to_date]."""
    months = []
    y, m = from_date.year, from_date.month
    while (y, m) <= (to_date.year, to_date.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _month_start_end(year: int, month: int) -> tuple[datetime, datetime]:
    """Retorna (start, end) UTC per un mes (end = primer dia del mes següent)."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Retries/backoff
# ---------------------------------------------------------------------------

async def _fetch_with_retries(
    provider,
    sym: str,
    start: datetime,
    end: datetime,
    retries: int,
    backoff_base: float,
    backoff_max: float,
    year: int,
    month: int,
) -> tuple[list, int]:
    """
    Fetch amb retry/backoff exponencial.

    Retorna (candles, retries_used).
    Si tots els reintents fallen, retorna ([], retries).
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            candles = await provider.fetch_ohlcv(sym, start, end)
            return candles, attempt
        except Exception as e:
            last_exc = e
            if attempt < retries:
                wait = min(backoff_base * (2 ** attempt), backoff_max)
                logger.warning(
                    "backfill FETCH ERROR symbol=%s %d-%02d attempt=%d/%d wait=%.1fs: %s",
                    sym, year, month, attempt + 1, retries, wait, e,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "backfill FETCH FAILED symbol=%s %d-%02d all %d retries exhausted: %s",
                    sym, year, month, retries, last_exc,
                )
    return [], retries


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

async def run_historical_backfill(
    symbol: str,
    from_date: date,
    to_date: date,
    datafiles_root: str = DEFAULT_DATAFILES_ROOT,
    skip_existing: bool = True,
    sleep_s: float = DEFAULT_SLEEP_S,
    dukascopy_override: Optional[List[Candle]] = None,
    on_month_done: Optional[Callable[[int, int, int], None]] = None,
    # Phase 18
    dry_run: bool = False,
    stop_after: Optional[int] = None,
    retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    backoff_max: float = DEFAULT_BACKOFF_MAX,
    retry_failed: bool = False,
    update_coverage: bool = True,
) -> dict:
    """
    Backfill històric Dukascopy → Parquet, mes a mes.

    Args:
        symbol: Símbol (EURUSD, XAUUSD, ...)
        from_date: Data inici (inclusiva)
        to_date: Data fi (inclusiva, fins al final del mes)
        datafiles_root: Path arrel datafiles
        skip_existing: Si True, salta particions ja existents (Parquet present)
        sleep_s: Pausa entre mesos (rate-limit)
        dukascopy_override: Llista Candle per 0-network testing
        on_month_done: callback(year, month, candles_written) per progrés
        dry_run: Si True, no escriu res (mostra pla)
        stop_after: Para després de N mesos escrits (0 = sense límit)
        retries: Màxim reintents per mes
        backoff_base: Base del backoff exponencial (segons)
        backoff_max: Màxim wait entre reintents (segons)
        retry_failed: Si True, reintenta mesos marcats com failed al coverage
        update_coverage: Actualitza coverage index (default True)

    Returns:
        dict: {symbol, months_total, months_written, months_skipped,
               months_failed, months_stopped, candles_total}
    """
    from application.data.coverage_index import CoverageIndex

    sym = symbol.upper()
    store = ParquetCandleStore(root_path=datafiles_root)
    months = _months_in_range(from_date, to_date)
    coverage = CoverageIndex(root_path=datafiles_root, symbol=sym) if update_coverage else None

    months_written = 0
    months_skipped = 0
    months_failed = 0
    months_stopped = 0
    candles_total = 0

    logger.info(
        "historical_backfill START symbol=%s from=%s to=%s months=%d dry_run=%s stop_after=%s",
        sym, from_date, to_date, len(months), dry_run, stop_after,
    )

    for i, (year, month) in enumerate(months):
        # Guard stop_after
        if stop_after is not None and stop_after > 0 and months_written >= stop_after:
            months_stopped = len(months) - i
            logger.info("historical_backfill STOPPED after %d months written", months_written)
            break

        month_key = f"{year:04d}-{month:02d}"

        # Resume logic: skip si done (només quan skip_existing=True)
        if coverage is not None and skip_existing:
            if coverage.is_done(year, month):
                logger.debug("historical_backfill SKIP %s (coverage=done)", month_key)
                months_skipped += 1
                if on_month_done:
                    on_month_done(year, month, 0)
                continue
            if coverage.is_failed(year, month) and not retry_failed:
                logger.debug("historical_backfill SKIP %s (coverage=failed, --retry-failed not set)", month_key)
                months_skipped += 1
                continue

        # Skip Parquet existent (si coverage no n'és conscient)
        if skip_existing and store.has_month(sym, year, month):
            if coverage is not None and not coverage.is_done(year, month):
                # Parquet existeix però no registrat: sincronitzar coverage
                candles_existing = store.read_month(sym, year, month)
                if candles_existing:
                    ts_list = [int(c.timestamp.timestamp()) for c in candles_existing]
                    coverage.mark_done(year, month, rows=len(ts_list),
                                       coverage_from=ts_list[0], coverage_to=ts_list[-1])
            logger.debug("historical_backfill SKIP %s (parquet exists)", month_key)
            months_skipped += 1
            if on_month_done:
                on_month_done(year, month, 0)
            continue

        # Dry-run: mostrar pla sense executar
        if dry_run:
            logger.info("historical_backfill DRY-RUN %s (would fetch+write)", month_key)
            print(f"  [dry-run] {month_key}: would fetch+write")
            months_written += 1  # comptem per dry-run stop_after
            continue

        start_dt, end_dt = _month_start_end(year, month)
        t0 = time.monotonic()

        if dukascopy_override is not None:
            candles = [
                c for c in dukascopy_override
                if start_dt <= (c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=timezone.utc)) < end_dt
            ]
            retries_used = 0
        else:
            from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
            provider = DukascopyBackfillProvider(cache_root=datafiles_root)
            candles, retries_used = await _fetch_with_retries(
                provider, sym, start_dt, end_dt,
                retries=retries,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
                year=year, month=month,
            )

        elapsed = time.monotonic() - t0

        if not candles and dukascopy_override is None and retries_used >= retries:
            # Tots els reintents han fallat
            months_failed += 1
            if coverage is not None:
                coverage.mark_failed(year, month, retries=retries_used)
            logger.warning(
                "historical_backfill MONTH_FAILED symbol=%s %s retries=%d elapsed=%.1fs",
                sym, month_key, retries_used, elapsed,
            )
            if on_month_done:
                on_month_done(year, month, 0)
            # Continua amb el mes següent (no para el job sencer)
            if sleep_s > 0 and i < len(months) - 1 and dukascopy_override is None:
                time.sleep(sleep_s)
            continue

        try:
            store.write_month(sym, year, month, candles)
        except Exception as e:
            logger.error("historical_backfill WRITE ERROR symbol=%s %s: %s", sym, month_key, e)
            months_failed += 1
            if coverage is not None:
                coverage.mark_failed(year, month, retries=retries_used)
            raise

        months_written += 1
        candles_total += len(candles)

        # Actualitzar coverage
        if coverage is not None:
            if candles:
                ts_list = [int(c.timestamp.timestamp()) for c in candles]
                coverage.mark_done(year, month, rows=len(ts_list),
                                   coverage_from=ts_list[0], coverage_to=ts_list[-1],
                                   retries=retries_used)
            else:
                coverage.mark_empty(year, month)

        logger.info(
            "historical_backfill MONTH symbol=%s %s candles=%d retries=%d elapsed=%.1fs",
            sym, month_key, len(candles), retries_used, elapsed,
        )
        if on_month_done:
            on_month_done(year, month, len(candles))

        # Rate-limit: sleep entre mesos (no al darrer)
        if sleep_s > 0 and i < len(months) - 1 and dukascopy_override is None:
            time.sleep(sleep_s)

    result = {
        "symbol": sym,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "months_total": len(months),
        "months_written": months_written,
        "months_skipped": months_skipped,
        "months_failed": months_failed,
        "months_stopped": months_stopped,
        "candles_total": candles_total,
        "dry_run": dry_run,
    }
    if coverage is not None:
        result["coverage_index"] = str(coverage._path)

    logger.info("historical_backfill DONE %s", result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Historical backfill Dukascopy→Parquet (Phase 15/18)"
    )
    parser.add_argument("--symbol", required=True, help="Símbol (EURUSD, XAUUSD, ...)")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi (YYYY-MM-DD)")
    parser.add_argument("--datafiles-root", default=DEFAULT_DATAFILES_ROOT, help="Path datafiles")
    parser.add_argument("--no-skip-existing", action="store_true", help="Sobreescriu particions existents")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S, help="Pausa entre mesos (rate-limit)")
    # Phase 18
    parser.add_argument("--dry-run", action="store_true", help="Mostra pla sense escriure res")
    parser.add_argument("--stop-after", type=int, default=None, metavar="N",
                        help="Para després de N mesos escrits (útil per iterar segur)")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                        help=f"Màxim reintents per mes (default {DEFAULT_RETRIES})")
    parser.add_argument("--backoff-base", type=float, default=DEFAULT_BACKOFF_BASE,
                        help=f"Base backoff exponencial en s (default {DEFAULT_BACKOFF_BASE})")
    parser.add_argument("--backoff-max", type=float, default=DEFAULT_BACKOFF_MAX,
                        help=f"Màxim wait entre reintents en s (default {DEFAULT_BACKOFF_MAX})")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Reintenta mesos marcats com failed al coverage index")
    parser.add_argument("--no-coverage", action="store_true",
                        help="No actualitzis el coverage index")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    def _progress(year, month, n):
        status = f"{n} candles" if n > 0 else "skipped/empty"
        print(f"  {year}-{month:02d}: {status}")

    result = asyncio.run(run_historical_backfill(
        symbol=args.symbol,
        from_date=from_date,
        to_date=to_date,
        datafiles_root=args.datafiles_root,
        skip_existing=not args.no_skip_existing,
        sleep_s=args.sleep,
        on_month_done=_progress,
        dry_run=args.dry_run,
        stop_after=args.stop_after,
        retries=args.retries,
        backoff_base=args.backoff_base,
        backoff_max=args.backoff_max,
        retry_failed=args.retry_failed,
        update_coverage=not args.no_coverage,
    ))

    print(f"\nHistorical backfill {'(dry-run) ' if result['dry_run'] else ''}completat:")
    print(f"  symbol={result['symbol']} from={result['from_date']} to={result['to_date']}")
    print(f"  mesos={result['months_total']} escrits={result['months_written']} "
          f"saltats={result['months_skipped']} fallats={result['months_failed']} "
          f"aturats={result['months_stopped']}")
    print(f"  candles_total={result['candles_total']}")
    if result.get("coverage_index"):
        print(f"  coverage_index={result['coverage_index']}")


if __name__ == "__main__":
    main()
