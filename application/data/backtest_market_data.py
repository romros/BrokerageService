"""
BacktestMarketDataProvider — provider OHLCV registry-aware per mode backtest.

Phase 10: Resolució de font de dades per backtesting usant ostium_compat_registry.
- allowed_for_backtest=true → Ostium local (CSVCandleStore del realtime_datalayer)
- altrament → Dukascopy (fallback)

Contracte de retorn: (body_dict, headers_dict) on headers_dict conté X-Data-* coherents.
Completament offline (0-network si Dukascopy té cache o Ostium té dades locals).

Layout candles Ostium: {datafiles_root}/realtime_datalayer/candles/{SYMBOL}/{TZ}/{YYYY}/{MM}.csv
(equivalent a CSVCandleStore(root_path=datafiles_root/realtime_datalayer, broker="candles"))
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

from domain.models import Candle
from foundation.config.constants import (
    OSTIUM_BROKER_SUBDIR,
    OSTIUM_CANONICAL_TZ,
    OSTIUM_PARQUET_SUBDIR,
    REALTIME_DATALAYER_SUBDIR,
)
from foundation.logging import get_logger

logger = get_logger(__name__)


def _read_ostium_parquet(
    symbol: str,
    start: datetime,
    end: datetime,
    datafiles_root: str,
) -> List[Candle]:
    """
    Llegeix candles Ostium des del Parquet rollover (TASCA 2).

    Path: {datafiles_root}/historical_parquet_ostium_v1/{SYMBOL}/tf=1m/year=.../month=.../data.parquet
    """
    import pyarrow.parquet as pq  # lazy import to reduce startup cost (AGENTS §6.1)

    base = Path(datafiles_root) / OSTIUM_PARQUET_SUBDIR / symbol.upper() / "tf=1m"
    if not base.exists():
        return []

    candles: List[Candle] = []
    for parquet_path in base.rglob("data.parquet"):
        try:
            table = pq.read_table(str(parquet_path))
            for i in range(table.num_rows):
                ts = table.column("ts")[i].as_py()
                ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if start <= ts_dt < end:
                    candles.append(
                        Candle(
                            symbol=symbol,
                            timestamp=ts_dt,
                            open=table.column("open")[i].as_py(),
                            high=table.column("high")[i].as_py(),
                            low=table.column("low")[i].as_py(),
                            close=table.column("close")[i].as_py(),
                            volume=table.column("volume")[i].as_py(),
                            is_closed=True,
                        )
                    )
        except Exception as e:
            logger.warning("ostium_parquet read %s: %s", parquet_path, e)
    return sorted(candles, key=lambda c: c.timestamp)


def resolve_backtest_data_source(
    symbol: str,
    registry_path: str | Path | None = None,
) -> str:
    """
    Retorna 'ostium' si allowed_for_backtest=true al registry, 'dukascopy' altrament.

    Fallback determinista a 'dukascopy' si registry absent o error de parse.
    """
    try:
        from application.data.ostium_compat_registry import load_ostium_registry
        data = load_ostium_registry(registry_path=registry_path)
        entry = data.get(symbol.upper())
        if isinstance(entry, dict) and entry.get("allowed_for_backtest") is True:
            return "ostium"
    except Exception as e:
        logger.warning("backtest_market_data: registry read error for %s: %s — fallback dukascopy", symbol, e)
    return "dukascopy"


def _read_ostium_candles(
    symbol: str,
    start: datetime,
    end: datetime,
    datafiles_root: str,
) -> List[Candle]:
    """
    Llegeix candles Ostium: Parquet (rollover durable) + CSV (realtime).
    Merge: CSV guanya en overlap (TASCA 2).
    """
    parquet_candles = _read_ostium_parquet(symbol, start, end, datafiles_root)

    from infrastructure.storage.csv_store import CSVCandleStore

    ostium_root = str(Path(datafiles_root) / REALTIME_DATALAYER_SUBDIR)
    store = CSVCandleStore(
        root_path=ostium_root,
        broker=OSTIUM_BROKER_SUBDIR,
        canonical_tz=OSTIUM_CANONICAL_TZ,
    )
    try:
        result = store.read_range(symbol, start, end, validate_gaps=False)
        csv_candles = result.candles
    except Exception as e:
        logger.warning("backtest_market_data: ostium csv read error symbol=%s: %s", symbol, e)
        csv_candles = []

    # Merge: per ts, CSV guanya (realtime més recent)
    by_ts = {int(c.timestamp.timestamp()): c for c in parquet_candles}
    for c in csv_candles:
        by_ts[int(c.timestamp.timestamp())] = c
    return sorted(by_ts.values(), key=lambda c: c.timestamp)


def _candles_to_body(symbol: str, candles: List[Candle]) -> dict[str, Any]:
    """Converteix llista Candle a body dict (format estàndard OHLCV)."""
    return {
        "symbol": symbol,
        "timeframe": "1m",
        "count": len(candles),
        "candles": [
            {
                "ts": int(c.timestamp.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }


def _compute_xdata_headers(
    candles: List[Candle],
    source: str,
    start: datetime,
    end: datetime,
) -> dict[str, str]:
    """
    Calcula headers X-Data-* coherents per a una llista de candles.

    coverage_from/to = timestamps reals de la finestra demanada.
    missing_minutes = minuts esperats - candles obtingudes.
    max_gap_s = gap màxim entre candles consecutives (0 si <=1 candle).
    """
    expected_minutes = max(0, int((end - start).total_seconds() // 60))

    if candles:
        coverage_from_ts = int(candles[0].timestamp.timestamp())
        coverage_to_ts = int(candles[-1].timestamp.timestamp()) + 60  # fi de l'última candle
        actual_minutes = len(candles)
        missing_minutes = max(0, expected_minutes - actual_minutes)

        # Gap màxim entre candles consecutives
        max_gap_s = 0
        if len(candles) > 1:
            for i in range(1, len(candles)):
                gap = int((candles[i].timestamp - candles[i - 1].timestamp).total_seconds())
                if gap > max_gap_s:
                    max_gap_s = gap
            # Un gap de 60s és normal (1m); gap > 60s = candle missing
            max_gap_s = max(0, max_gap_s - 60)
    else:
        coverage_from_ts = int(start.timestamp())
        coverage_to_ts = int(end.timestamp())
        missing_minutes = expected_minutes
        max_gap_s = 0

    return {
        "X-Data-Source": source,
        "X-Data-Coverage-From": str(coverage_from_ts),
        "X-Data-Coverage-To": str(coverage_to_ts),
        "X-Data-Missing-Minutes": str(missing_minutes),
        "X-Data-Max-Gap-S": str(max_gap_s),
    }


async def get_ohlcv_backtest(
    symbol: str,
    start: datetime,
    end: datetime,
    datafiles_root: str,
    registry_path: str | Path | None = None,
    dukascopy_override: Optional[List[Candle]] = None,
    source: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Retorna (body_dict, headers_dict) per backtest, resolent la font via registry o paràmetre.

    - source="ostium" → Ostium local (0-network)
    - source="dukascopy" → Dukascopy (pot requerir xarxa o cache)
    - source=None → comportament llegat: registry-aware (allowed_for_backtest → ostium, altrament dukascopy)

    dukascopy_override: per testing 0-network, substitueix fetch real Dukascopy.

    NEVER throws: si hi ha error de lectura, retorna candles buides + headers coherents.
    """
    if source is not None:
        source_name = source.lower().strip()
    else:
        source_name = resolve_backtest_data_source(symbol, registry_path=registry_path)

    if source_name == "ostium":
        candles = _read_ostium_candles(symbol, start, end, datafiles_root)
        xdata_source = "ostium_local"
        if not candles:
            logger.warning(
                "backtest_market_data: ostium source selected but 0 candles symbol=%s — no fallback",
                symbol,
            )
    else:
        if dukascopy_override is not None:
            candles = dukascopy_override
        else:
            from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
            provider = DukascopyBackfillProvider(cache_root=datafiles_root)
            try:
                candles = await provider.fetch_ohlcv(symbol, start, end)
            except Exception as e:
                logger.warning("backtest_market_data: dukascopy fetch error symbol=%s: %s", symbol, e)
                candles = []
        xdata_source = "dukascopy"

    body = _candles_to_body(symbol, candles)
    headers = _compute_xdata_headers(candles, xdata_source, start, end)

    logger.info(
        "backtest_market_data symbol=%s source=%s candles=%d missing=%s",
        symbol, xdata_source, len(candles), headers["X-Data-Missing-Minutes"],
    )

    return body, headers
