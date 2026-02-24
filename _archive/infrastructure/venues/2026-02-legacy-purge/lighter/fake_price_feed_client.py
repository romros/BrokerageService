"""
Fake Lighter Price Feed Client (testing without network)

Emits ticks continuously at tick_interval_ms for integration tests.
Uses real timestamps so candles cross minute boundaries correctly.
Monotonic prices (slight drift) for stability.
Clean stop via task cancellation.

References:
- P2.0.1 WS preflight integration
- test_lighter_ticks_to_candles_flow.py (FakeLighterPriceFeedClient pattern)
"""

import asyncio
import time
from typing import List, Optional

from foundation.config.constants import DEFAULT_FAKE_TICK_INTERVAL_MS
from foundation.logging import get_logger

logger = get_logger(__name__)


class FakeLighterPriceFeedClient:
    """
    Fake price feed for deterministic tests (no network).

    Emits ticks per symbol every tick_interval_ms.
    Prices drift monotonically (base + small increment per tick).
    Allows clean stop via task cancellation.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        tick_interval_ms: Optional[int] = None,
    ):
        """
        Args:
            symbols: Symbols to emit (default: ["ETH", "BTC"])
            tick_interval_ms: Interval between ticks in ms (default: from constants)
        """
        self._symbols = symbols or ["ETH", "BTC"]
        self._tick_interval_ms = (
            tick_interval_ms
            if tick_interval_ms is not None
            else DEFAULT_FAKE_TICK_INTERVAL_MS
        )
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._base_prices: dict[str, float] = {
            "ETH": 3500.0,
            "BTC": 98000.0,
        }

    async def start(self) -> None:
        """Start tick emission loop."""
        if self._running:
            logger.warning("FakeLighterPriceFeedClient already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._emit_loop())
        logger.info(
            f"FakeLighterPriceFeedClient started: symbols={self._symbols}, "
            f"interval_ms={self._tick_interval_ms}"
        )

    async def stop(self) -> None:
        """Stop tick emission (cancel task)."""
        if not self._running:
            return
        logger.info("Stopping FakeLighterPriceFeedClient...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("FakeLighterPriceFeedClient stopped")

    async def _emit_loop(self) -> None:
        """Emit ticks every tick_interval_ms with real timestamps."""
        interval_sec = self._tick_interval_ms / 1000.0
        tick_count = 0

        while self._running:
            try:
                now_ms = int(time.time() * 1000)
                for symbol in self._symbols:
                    if not self._running:
                        break
                    base = self._base_prices.get(symbol, 1000.0)
                    # Monotonic drift: +0.01 per tick (stable, no jumps)
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
                logger.debug(f"Fake emit loop: {e}")

    async def get_ticks(self) -> tuple[str, float, int]:
        """
        Get next tick (blocks until available).

        Returns:
            (symbol, price, timestamp_ms)
        """
        return await self._queue.get()
