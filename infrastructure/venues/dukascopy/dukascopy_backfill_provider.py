"""
Dukascopy Backfill Provider (P6)

Implements IBackfillProvider: fetch() + cache.
Contract: ts UTC start-of-minute, [start, end), ascending, is_closed=True, volume=0 si no hi ha.
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


class DukascopyBackfillProvider(IBackfillProvider):
    """
    Backfill provider via Dukascopy (fetch + cache).
    """

    def __init__(self, cache_root: str | None = None):
        self._client = DukascopyClient(cache_root=cache_root)

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch historical OHLCV [start, end).
        Returns Candle objects with is_closed=True, ts UTC start-of-minute.
        """
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        start_ts = (start_ts // 60) * 60
        end_ts = (end_ts // 60) * 60
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        def _fetch():
            return self._client.fetch_candles(symbol, start_dt, end_dt, use_cache_only=False)

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
        return "dukascopy"

    @property
    def max_range_minutes(self) -> int:
        return 10080  # 7 dies per request (Dukascopy pot limitar; chunk si cal)
