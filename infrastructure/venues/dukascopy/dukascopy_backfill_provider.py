"""
Dukascopy Backfill Provider (P6)

Implements IBackfillProvider: fetch() + cache.
Contract: ts UTC start-of-minute, [start, end), ascending, is_closed=True, volume=0 si no hi ha.

T8.23: Fallback bi5 per dates pre-2007.
El feed JSON públic (dukascopy_python) retorna [] per EURUSD pre-2007.
Si el provider JSON retorna [] i el rang és pre-2007, s'activa el fallback bi5:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{Y}/{M_0idx}/{D}/BID_candles_min_1.bi5
Disponible des de 2003-05-05.

DUKASCOPY_BACKFILL_MODE (env var):
  - "ticks" (default): usa Bi5TicksBackfillProvider — reconstrueix M1 des de ticks bruts.
    Paritat exacta amb SQ. Recomanat per tot el rang de dades.
  - "m1": camí llegat (dukascopy_python + Bi5BackfillProvider pre-2007).
    close[t] ≈ open[t+1] (desfasat ~0.5pip). Per compatibilitat / migració.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import List

from domain.interfaces import IBackfillProvider
from domain.models import Candle
from foundation.logging import get_logger

from .dukascopy_client import DukascopyClient

logger = get_logger(__name__)

# Any fins al qual el feed JSON Dukascopy NO té dades M1 (límit confirmat T8.17)
_BI5_FALLBACK_MAX_YEAR = 2006

# Env var per seleccionar el mode de backfill
_BACKFILL_MODE_ENV     = "DUKASCOPY_BACKFILL_MODE"
_BACKFILL_MODE_TICKS   = "ticks"
_BACKFILL_MODE_M1      = "m1"
_BACKFILL_MODE_DEFAULT = _BACKFILL_MODE_TICKS


def _get_backfill_mode() -> str:
    mode = os.environ.get(_BACKFILL_MODE_ENV, _BACKFILL_MODE_DEFAULT).lower().strip()
    if mode not in (_BACKFILL_MODE_TICKS, _BACKFILL_MODE_M1):
        logger.warning(
            "DUKASCOPY_BACKFILL_MODE='%s' invàlid — usant default '%s'",
            mode, _BACKFILL_MODE_DEFAULT,
        )
        return _BACKFILL_MODE_DEFAULT
    return mode


class DukascopyBackfillProvider(IBackfillProvider):
    """
    Backfill provider via Dukascopy (fetch + cache).

    Mode ticks (default): delega a Bi5TicksBackfillProvider.
    Mode m1 (llegat): dukascopy_python + fallback bi5 M1 pre-2007.
    """

    def __init__(self, cache_root: str | None = None):
        self._cache_root = cache_root
        self._client = DukascopyClient(cache_root=cache_root)

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch historical OHLCV [start, end).

        Mode ticks: delega a Bi5TicksBackfillProvider (paritat SQ).
        Mode m1: camí llegat (dukascopy_python + bi5 pre-2007).
        """
        mode = _get_backfill_mode()

        if mode == _BACKFILL_MODE_TICKS:
            return await self._fetch_ohlcv_ticks(symbol, start, end)
        else:
            return await self._fetch_ohlcv_m1_legacy(symbol, start, end)

    async def _fetch_ohlcv_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """Mode ticks: delega a Bi5TicksBackfillProvider."""
        from .bi5_ticks_backfill_provider import Bi5TicksBackfillProvider
        provider = Bi5TicksBackfillProvider(datafiles_root=self._cache_root)
        return await provider.fetch_ohlcv(symbol, start, end)

    async def _fetch_ohlcv_m1_legacy(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Mode m1 llegat: dukascopy_python + fallback bi5 pre-2007.

        T8.23: si start.year <= 2006 i el feed JSON retorna [], usa bi5 fallback.
        """
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        start_ts = (start_ts // 60) * 60
        end_ts = (end_ts // 60) * 60
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        # A fully covered local cache is authoritative for this legacy path.
        # Avoid a needless network call: tests and offline backtests must remain
        # deterministic, and refreshing an already complete range only adds
        # latency/rate-limit risk.
        cached = self._client.fetch_candles(
            symbol, start_dt, end_dt, use_cache_only=True
        )
        expected_minutes = max(0, (end_ts - start_ts) // 60)
        cached_timestamps = {
            int(row["ts"]) for row in cached
            if start_ts <= int(row["ts"]) < end_ts
        }
        if expected_minutes and len(cached_timestamps) == expected_minutes:
            rows = cached
        else:
            rows = None

        def _fetch():
            return self._client.fetch_candles(symbol, start_dt, end_dt, use_cache_only=False)

        if rows is None:
            try:
                rows = await asyncio.to_thread(_fetch)
            except Exception as e:
                # Offline: intentar només cache
                if self._client.has_cache(symbol, start_dt, end_dt):
                    rows = self._client.fetch_candles(symbol, start_dt, end_dt, use_cache_only=True)
                else:
                    raise RuntimeError(
                        f"dukascopy cache missing + network unavailable: {e}"
                    ) from e

        # T8.23: fallback bi5 si rang pre-2007 i JSON retorna buit
        if not rows and start_dt.year <= _BI5_FALLBACK_MAX_YEAR:
            logger.info(
                "DukascopyBackfillProvider: JSON feed buit per %s %s-%s (pre-2007), provant bi5 fallback",
                symbol, start_dt.date(), end_dt.date(),
            )
            try:
                from .bi5_backfill_provider import Bi5BackfillProvider
                bi5 = Bi5BackfillProvider()
                return await bi5.fetch_ohlcv(symbol, start_dt, end_dt)
            except Exception as e:
                logger.warning("DukascopyBackfillProvider: bi5 fallback error %s: %s", symbol, e)
                return []

        candles: List[Candle] = []
        for r in sorted(rows, key=lambda x: x["ts"]):
            ts_dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
            candles.append(Candle(
                symbol=r["symbol"],
                timestamp=ts_dt,
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r.get("volume", 0) or 0,
                is_closed=True,
            ))
        return candles

    async def is_available(self) -> bool:
        """True si dukascopy-python instal·lat i instruments accessibles."""
        try:
            from .dukascopy_client import _get_instrument  # lazy: evita carregar dukascopy_client fins a is_available
            _get_instrument("EURUSD")
            _get_instrument("XAUUSD")
            return True
        except Exception as e:
            logger.debug("DukascopyBackfillProvider not available: %s", e)
            return False

    @property
    def provider_name(self) -> str:
        mode = _get_backfill_mode()
        if mode == _BACKFILL_MODE_TICKS:
            return "dukascopy_bi5_ticks"
        return "dukascopy"

    @property
    def max_range_minutes(self) -> int:
        return 10080  # 7 dies per request (Dukascopy pot limitar; chunk si cal)
