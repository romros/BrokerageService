"""
Lighter Price Feed Client (polling)

Provides tick stream for LiveMarketDataService by polling order book
at configurable interval. Converts order book mid price to (symbol, price, timestamp_ms)
with monotonic timestamps.

Configuration (no hardcoded values):
- tick_interval_ms: from config.get_lighter_tick_interval_ms() or constructor
- symbols: from config.get_lighter_symbols_from_env() or constructor

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Market data via order book
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from foundation.logging import get_logger

from .config import get_lighter_tick_interval_ms, get_lighter_symbols_from_env
from .market_data_client import ILighterMarketDataClient
from .mappers import map_order_book_orders_to_price_data, normalize_symbol
from .price_cache import PriceSnapshotCache

logger = get_logger(__name__)


def _default_time_provider() -> datetime:
    """Default time provider (UTC now)."""
    return datetime.now(timezone.utc)


class LighterPriceFeedClient:
    """
    Polling-based price feed for Lighter (tick stream).

    Polls get_order_book_orders() per symbol at tick_interval_ms,
    pushes (symbol, mid_price, timestamp_ms) to queue for LiveMarketDataService.
    Timestamps are monotonic (no regression).
    """

    def __init__(
        self,
        market_data_client: ILighterMarketDataClient,
        symbols: Optional[List[str]] = None,
        tick_interval_ms: Optional[int] = None,
        time_provider: Optional[Callable[[], datetime]] = None,
        price_cache: Optional[PriceSnapshotCache] = None,
    ):
        """
        Args:
            market_data_client: Lighter market data client (order book)
            symbols: Symbols to poll (default: from LIGHTER_SYMBOLS / SYMBOLS env)
            tick_interval_ms: Poll interval in ms (default: from LIGHTER_TICK_INTERVAL_MS env)
            time_provider: For timestamps (injectable for tests)
            price_cache: Shared cache to write prices (for GET /price, close path)
        """
        self._client = market_data_client
        self._price_cache = price_cache
        self._symbols = symbols or get_lighter_symbols_from_env()
        self._tick_interval_ms = tick_interval_ms if tick_interval_ms is not None else get_lighter_tick_interval_ms()
        self._time_provider = time_provider or _default_time_provider

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_ts_ms: Dict[str, int] = {}

        logger.info(
            f"LighterPriceFeedClient initialized: symbols={self._symbols}, "
            f"tick_interval_ms={self._tick_interval_ms}"
        )

    async def start(self) -> None:
        """Load market cache and start polling loop."""
        if self._running:
            logger.warning("LighterPriceFeedClient already running")
            return

        if hasattr(self._client, "_ensure_market_cache_loaded"):
            await self._client._ensure_market_cache_loaded()

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("LighterPriceFeedClient started")

    async def stop(self) -> None:
        """Stop polling loop."""
        if not self._running:
            return

        logger.info("Stopping LighterPriceFeedClient...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LighterPriceFeedClient stopped")

    async def _poll_loop(self) -> None:
        """Poll each symbol at interval and push ticks to queue."""
        interval_sec = self._tick_interval_ms / 1000.0

        while self._running:
            for symbol in self._symbols:
                if not self._running:
                    break
                try:
                    market_id = None
                    if hasattr(self._client, "resolve_symbol_to_market_id"):
                        market_id = self._client.resolve_symbol_to_market_id(symbol)
                    if market_id is None:
                        continue

                    order_book_orders = await self._client.get_order_book_orders(
                        market_id=market_id, limit=10
                    )
                    sym_normalized = normalize_symbol(symbol)
                    price_data = map_order_book_orders_to_price_data(
                        symbol=symbol,
                        order_book_orders=order_book_orders,
                        time_provider=self._time_provider,
                    )
                    if self._price_cache:
                        self._price_cache.set(sym_normalized, price_data)

                    now_ms = int(self._time_provider().timestamp() * 1000)
                    last = self._last_ts_ms.get(symbol, 0)
                    ts_ms = max(last + 1, now_ms)
                    self._last_ts_ms[symbol] = ts_ms
                    try:
                        self._queue.put_nowait((sym_normalized, price_data.mid, ts_ms))
                    except asyncio.QueueFull:
                        logger.warning("Lighter price feed queue full, dropping tick")

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"Lighter poll {symbol}: {e}")

            await asyncio.sleep(interval_sec)

    async def get_ticks(self) -> tuple[str, float, int]:
        """
        Get next tick (blocks until available).

        Returns:
            (symbol, price, timestamp_ms)
        """
        return await self._queue.get()
