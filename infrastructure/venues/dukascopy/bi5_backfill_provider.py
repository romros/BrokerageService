"""
infrastructure/venues/dukascopy/bi5_backfill_provider.py — T8.23

Bi5BackfillProvider: descàrrega M1 via el feed binari natiu Dukascopy (.bi5).

Descoberta T8.23: SQ DataSourceDukascopy usa:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/BID_candles_min_1.bi5

Disponible des de 2003-05-05 per EURUSD, GBPUSD, USDJPY, etc.
El feed JSON públic (/datafeed/EURUSD?...) retorna [] per dates pre-2007.
Aquest provider és el fallback per cobrir el gap pre-2007.

Ús:
    provider = Bi5BackfillProvider()
    candles = await provider.fetch_ohlcv("EURUSD", start_dt, end_dt)

Integració amb SyncManager:
    El sync_manager usarà Bi5BackfillProvider com a fallback quan
    DukascopyBackfillProvider retorna [] i l'any és <= 2006.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from domain.interfaces import IBackfillProvider
from domain.models import Candle

from application.data.dukascopy_bi5 import fetch_m1_range

logger = logging.getLogger(__name__)

# Any màxim per usar bi5 com a font primària (pre-2007 el feed JSON és buit)
BI5_MAX_YEAR_PRIMARY = 2006


class Bi5BackfillProvider(IBackfillProvider):
    """
    Backfill provider via feed binari Dukascopy (.bi5).

    Usa directament https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{Y}/{M_0idx}/{D}/BID_candles_min_1.bi5
    sense dependre de dukascopy_python.

    Rate limit: 0.1s entre requests de dies (configurable).
    """

    def __init__(self, rate_limit_s: float = 0.1):
        self._rate_limit_s = rate_limit_s

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch historical OHLCV [start, end) via bi5.

        Args:
            symbol: p.ex. 'EURUSD'
            start: datetime UTC (inclusiu)
            end: datetime UTC (exclusiu)

        Returns:
            Llista de Candle objects amb is_closed=True, ts UTC start-of-minute.
        """
        from_date = start.strftime("%Y-%m-%d")
        to_date = end.strftime("%Y-%m-%d")
        # Si el dia de fi és exactament mig-nit, no hi incloem el dia end
        # (fetch_m1_range és [from, to) per dies)

        def _fetch_sync():
            return fetch_m1_range(
                symbol,
                from_date,
                to_date,
                rate_limit_s=self._rate_limit_s,
            )

        try:
            raw_candles = await asyncio.to_thread(_fetch_sync)
        except RuntimeError as e:
            raise RuntimeError(f"Bi5BackfillProvider fetch error {symbol} [{from_date},{to_date}): {e}") from e

        if not raw_candles:
            logger.debug("Bi5BackfillProvider: 0 candles per %s [%s, %s)", symbol, from_date, to_date)
            return []

        # Filtra rang exacte [start_ts, end_ts)
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())

        candles: List[Candle] = []
        for r in raw_candles:
            ts = r["ts_utc"]
            if ts < start_ts or ts >= end_ts:
                continue
            ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            o, h, l, c = r["open"], r["high"], r["low"], r["close"]
            # Correcció invariant OHLC: Dukascopy bi5 pot tenir open/close fora del rang h/l
            # per arrodoniment de coma flotant (els preus estan codificats com enters ×10^5)
            h = max(o, h, c)
            l = min(o, l, c)
            candles.append(Candle(
                symbol=symbol.upper(),
                timestamp=ts_dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=r.get("vol", 0) or 0,
                is_closed=True,
            ))

        logger.info(
            "Bi5BackfillProvider: %d candles per %s [%s, %s)",
            len(candles), symbol, from_date, to_date,
        )
        return candles

    async def is_available(self) -> bool:
        """Sempre disponible (accés directe HTTPS, sense deps addicionals)."""
        return True

    @property
    def provider_name(self) -> str:
        return "dukascopy_bi5"

    @property
    def max_range_minutes(self) -> int:
        return 10080  # 7 dies per request
