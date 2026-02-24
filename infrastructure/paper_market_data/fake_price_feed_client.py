"""
Fake price feed client — paper mode sense xarxa.

Emits ticks contínuament per integration tests.
Usa timestamps reals per candles cross minute boundaries.
"""

import asyncio
import time
from typing import List, Optional

from foundation.config.constants import DEFAULT_FAKE_TICK_INTERVAL_MS
from foundation.logging import get_logger

logger = get_logger(__name__)


class FakePriceFeedClient:
    """
    Fake price feed per paper mode (no network).

    Emits ticks per symbol every tick_interval_ms.
    Prices drift monotonically (base + small increment per tick).
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        tick_interval_ms: Optional[int] = None,
    ):
        self._symbols = symbols or ["XAUUSD", "EURUSD"]
        self._tick_interval_ms = (
            tick_interval_ms
            if tick_interval_ms is not None
            else DEFAULT_FAKE_TICK_INTERVAL_MS
        )
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._base_prices: dict[str, float] = {
            "XAUUSD": 2650.0,
            "EURUSD": 1.08,
            "ETH": 3500.0,
            "BTC": 98000.0,
        }

    async def start(self) -> None:
        if self._running:
            logger.warning("FakePriceFeedClient already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._emit_loop())
        logger.info(
            "FakePriceFeedClient started: symbols=%s interval_ms=%s",
            self._symbols,
            self._tick_interval_ms,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        logger.info("Stopping FakePriceFeedClient...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("FakePriceFeedClient stopped")

    async def _emit_loop(self) -> None:
        interval_sec = self._tick_interval_ms / 1000.0
        tick_count = 0
        while self._running:
            try:
                now_ms = int(time.time() * 1000)
                for symbol in self._symbols:
                    if not self._running:
                        break
                    base = self._base_prices.get(symbol, 1000.0)
                    price = base + (tick_count * 0.01)
                    try:
                        self._queue.put_nowait((symbol, price, now_ms))
                    except asyncio.QueueFull:
                        logger.debug("Fake price feed queue full, dropping tick")
                tick_count += 1
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Fake emit loop: %s", e)

    async def get_ticks(self) -> tuple[str, float, int]:
        return await self._queue.get()
