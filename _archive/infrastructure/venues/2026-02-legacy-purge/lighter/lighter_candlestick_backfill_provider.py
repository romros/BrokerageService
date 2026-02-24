"""
Lighter Candlestick Backfill Provider (P4.0)

Implements IBackfillProvider using Lighter Candlestick API.
Contract: [start, end), UTC start-of-minute, only closed candles.
"""

import os
from datetime import datetime, timezone
from typing import List

from domain.interfaces import IBackfillProvider
from domain.models import Candle
from foundation.logging import get_logger

from .lighter_candlestick_client import LighterCandlestickClient

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://mainnet.zklighter.elliot.ai"


class LighterCandlestickBackfillProvider(IBackfillProvider):
    """
    Backfill provider via Lighter Candlestick API.
    """

    def __init__(
        self,
        base_url: str | None = None,
        market_id_map: dict | None = None,
    ):
        self._base_url = (base_url or os.getenv("LIGHTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = LighterCandlestickClient(
            base_url=self._base_url,
            market_id_map=market_id_map or {},
        )
        logger.info(
            "LighterCandlestickBackfillProvider initialized: base_url=%s",
            self._base_url,
        )

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

        rows = await self._client.fetch_candles(symbol, start_ts, end_ts)

        candles: List[Candle] = []
        for r in rows:
            ts_dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
            candles.append(Candle(
                symbol=r["symbol"],
                timestamp=ts_dt,
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                is_closed=True,
            ))
        return candles

    async def is_available(self) -> bool:
        """Check if Lighter Candlestick API is reachable."""
        try:
            await self._client._ensure_market_ids()
            return bool(self._client._market_id_map)
        except Exception as e:
            logger.warning("LighterCandlestickBackfillProvider not available: %s", e)
            return False

    @property
    def provider_name(self) -> str:
        return "lighter"

    @property
    def max_range_minutes(self) -> int:
        return 500
