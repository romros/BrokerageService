"""
Historical Backfill Runner — Phase 15.

Descarrega candles 1m de Dukascopy i les emmagatzema en Parquet particionat per mes.

Idempotent: rerun no duplica particions existents (--skip-existing per defecte).
Rate-limit: sleep configurable entre peticions.

Ús CLI (via scripts/run_historical_backfill.sh):
    python3 application/tools/run_historical_backfill.py \\
        --symbol EURUSD --from 2003-01-01 --to 2003-12-31

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

DEFAULT_SLEEP_S = 1.0      # entre mesos
DEFAULT_DATAFILES_ROOT = "/datafiles"


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


async def run_historical_backfill(
    symbol: str,
    from_date: date,
    to_date: date,
    datafiles_root: str = DEFAULT_DATAFILES_ROOT,
    skip_existing: bool = True,
    sleep_s: float = DEFAULT_SLEEP_S,
    dukascopy_override: Optional[List[Candle]] = None,
    on_month_done: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """
    Backfill històric Dukascopy → Parquet, mes a mes.

    Args:
        symbol: Símbol (EURUSD, XAUUSD, ...)
        from_date: Data inici (inclusiva)
        to_date: Data fi (inclusiva, fins al final del mes)
        datafiles_root: Path arrel datafiles
        skip_existing: Si True, salta particions ja existents (idempotent)
        sleep_s: Pausa entre mesos (rate-limit)
        dukascopy_override: Llista Candle per 0-network testing (substitueix fetch real)
        on_month_done: callback(year, month, candles_written) per progrés

    Returns:
        dict amb resum: {symbol, months_total, months_written, months_skipped, candles_total}
    """
    sym = symbol.upper()
    store = ParquetCandleStore(root_path=datafiles_root)
    months = _months_in_range(from_date, to_date)

    months_written = 0
    months_skipped = 0
    candles_total = 0

    logger.info(
        "historical_backfill START symbol=%s from=%s to=%s months=%d skip_existing=%s",
        sym, from_date, to_date, len(months), skip_existing,
    )

    for i, (year, month) in enumerate(months):
        if skip_existing and store.has_month(sym, year, month):
            logger.debug("historical_backfill SKIP symbol=%s year=%d month=%02d (ja existeix)", sym, year, month)
            months_skipped += 1
            if on_month_done:
                on_month_done(year, month, 0)
            continue

        start, end = _month_start_end(year, month)

        if dukascopy_override is not None:
            # Mode test 0-network: filtrar candles pel mes
            candles = [
                c for c in dukascopy_override
                if start <= (c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=timezone.utc)) < end
            ]
        else:
            from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
            provider = DukascopyBackfillProvider(cache_root=datafiles_root)
            try:
                candles = await provider.fetch_ohlcv(sym, start, end)
            except Exception as e:
                logger.warning("historical_backfill FETCH ERROR symbol=%s year=%d month=%02d: %s", sym, year, month, e)
                candles = []

        try:
            store.write_month(sym, year, month, candles)
        except Exception as e:
            logger.error("historical_backfill WRITE ERROR symbol=%s year=%d month=%02d: %s", sym, year, month, e)
            raise

        months_written += 1
        candles_total += len(candles)
        logger.info(
            "historical_backfill MONTH symbol=%s year=%d month=%02d candles=%d",
            sym, year, month, len(candles),
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
        "candles_total": candles_total,
    }
    logger.info("historical_backfill DONE %s", result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Historical backfill Dukascopy→Parquet (Phase 15)")
    parser.add_argument("--symbol", required=True, help="Símbol (EURUSD, XAUUSD, ...)")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi (YYYY-MM-DD)")
    parser.add_argument("--datafiles-root", default=DEFAULT_DATAFILES_ROOT, help="Path datafiles")
    parser.add_argument("--no-skip-existing", action="store_true", help="Sobreescriu particions existents")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S, help="Pausa entre mesos (rate-limit)")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    def _progress(year, month, n):
        print(f"  {year}-{month:02d}: {n} candles")

    result = asyncio.run(run_historical_backfill(
        symbol=args.symbol,
        from_date=from_date,
        to_date=to_date,
        datafiles_root=args.datafiles_root,
        skip_existing=not args.no_skip_existing,
        sleep_s=args.sleep,
        on_month_done=_progress,
    ))

    print(f"\nHistorical backfill completat:")
    print(f"  symbol={result['symbol']} from={result['from_date']} to={result['to_date']}")
    print(f"  mesos={result['months_total']} escrits={result['months_written']} saltats={result['months_skipped']}")
    print(f"  candles_total={result['candles_total']}")


if __name__ == "__main__":
    main()
