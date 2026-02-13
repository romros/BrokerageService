"""
LiveMarketDataService - Process live price feed ticks

Consumes ticks from GTradePriceFeedWSClient and:
1. Updates latest price cache (per symbol)
2. Broadcasts throttled ticker updates via WebSocket
3. Feeds ticks to CandleBuilder (per symbol)
4. Persists completed candles to storage
5. Broadcasts completed candles via WebSocket

Features:
- Multi-symbol support (XAUUSD, EURUSD)
- Ticker broadcast throttling (default 200ms)
- Per-symbol CandleBuilder instances
- Automatic gap validation on storage
- WebSocket integration (optional)

Configuration:
- ENABLE_LIVE_FEED: Enable/disable live feed (default: 0)
- LIVE_TICKER_BROADCAST_MS: Ticker throttle interval (default: 200ms)
- GTRADE_PRICE_WS_URL: WebSocket URL
"""


import asyncio
import time
from datetime import datetime
from typing import Dict, Optional

from domain.interfaces import ICandleStore, IPriceFeedClient
from domain.models import Tick, Candle
from foundation.config.constants import (
    CANONICAL_TIMEZONE,
    DEFAULT_TICKER_BROADCAST_MS,
    MOCK_TICK_VOLUME,
)
from foundation.lifecycle import IService
from foundation.logging import get_logger
from infrastructure.builders.candle_builder import CandleBuilder

# Avoid circular import for WebSocketHub
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.ws.hub import WebSocketHub

logger = get_logger(__name__)


class LiveMarketDataService(IService):
    """
    Live market data service

    Consumes ticks from gTrade price feed and:
    - Broadcasts ticker updates (throttled)
    - Builds candles via CandleBuilder
    - Persists candles to storage
    - Broadcasts candles via WebSocket
    """

    def __init__(
        self,
        price_feed_client: IPriceFeedClient,
        candle_store: ICandleStore,
        symbols: list[str],
        tz = None,
        ticker_broadcast_ms: int = DEFAULT_TICKER_BROADCAST_MS,
        hub: Optional["WebSocketHub"] = None,
    ):
        """
        Initialize live market data service

        Args:
            price_feed_client: Tick feed (gTrade WS or Lighter polling)
            candle_store: Storage for completed candles
            symbols: List of symbols to track (e.g., ["XAUUSD", "EURUSD"] or ["ETH", "BTC"])
            tz: Timezone for candles (default: America/New_York)
            ticker_broadcast_ms: Ticker broadcast throttle interval (default: 200ms)
            hub: WebSocket hub for broadcasting (optional)
        """
        self.price_feed_client = price_feed_client
        self.candle_store = candle_store
        self.symbols = symbols
        self.tz = tz or CANONICAL_TIMEZONE
        self.ticker_broadcast_ms = ticker_broadcast_ms
        self.hub = hub

        # Per-symbol state
        self._candle_builders: Dict[str, CandleBuilder] = {}
        self._latest_price: Dict[str, float] = {}
        self._last_ticker_broadcast: Dict[str, int] = {}  # symbol -> timestamp_ms

        # Service state
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Initialize candle builders for each symbol
        for symbol in symbols:
            self._candle_builders[symbol] = CandleBuilder(symbol=symbol, tz=self.tz)
            self._last_ticker_broadcast[symbol] = 0

        logger.info(
            f"LiveMarketDataService initialized: symbols={symbols}, "
            f"ticker_broadcast_ms={ticker_broadcast_ms}, tz={self.tz}"
        )

    async def start(self):
        """Start service"""
        if self._running:
            logger.warning("LiveMarketDataService already running")
            return

        logger.info("Starting LiveMarketDataService...")
        self._running = True

        # Start price feed client
        await self.price_feed_client.start()

        # Start tick processing loop
        self._task = asyncio.create_task(self._process_ticks_loop())

        logger.info("✓ LiveMarketDataService started")

    async def stop(self):
        """Stop service"""
        if not self._running:
            return

        logger.info("Stopping LiveMarketDataService...")
        self._running = False

        # Stop tick processing loop
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Stop price feed client
        await self.price_feed_client.stop()

        logger.info("✓ LiveMarketDataService stopped")

    async def _process_ticks_loop(self):
        """Main loop: consume ticks from price feed"""
        logger.info("Tick processing loop started")

        while self._running:
            try:
                # Get next tick from price feed (blocking)
                symbol, price, timestamp_ms = await self.price_feed_client.get_ticks()

                # Process tick
                await self._process_tick(symbol, price, timestamp_ms)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing tick: {e}")
                await asyncio.sleep(1)  # Backoff on error

        logger.info("Tick processing loop stopped")

    async def _process_tick(self, symbol: str, price: float, timestamp_ms: int):
        """
        Process a single tick

        Args:
            symbol: Symbol name (e.g., "XAUUSD")
            price: Price value
            timestamp_ms: Tick timestamp in milliseconds
        """
        # Update latest price cache
        self._latest_price[symbol] = price

        # Broadcast ticker update (throttled)
        await self._broadcast_ticker(symbol, price, timestamp_ms)

        # Feed to candle builder
        timestamp_sec = timestamp_ms / 1000.0
        tick = Tick(
            symbol=symbol,
            price=price,
            timestamp=datetime.fromtimestamp(timestamp_sec, tz=self.tz),
            volume=MOCK_TICK_VOLUME  # gTrade doesn't provide tick volume
        )

        builder = self._candle_builders.get(symbol)
        if builder is None:
            logger.warning(f"No candle builder for symbol {symbol}")
            return

        # Process tick in builder
        completed_candle = builder.on_tick(tick)

        # If candle completed, persist and broadcast
        if completed_candle is not None:
            await self._handle_completed_candle(symbol, completed_candle)

    async def _broadcast_ticker(self, symbol: str, price: float, timestamp_ms: int):
        """
        Broadcast ticker update (throttled)

        Args:
            symbol: Symbol name
            price: Price value
            timestamp_ms: Timestamp in milliseconds
        """
        if self.hub is None:
            return  # No WebSocket hub configured

        # Check throttle
        last_broadcast = self._last_ticker_broadcast.get(symbol, 0)
        elapsed_ms = timestamp_ms - last_broadcast

        if elapsed_ms < self.ticker_broadcast_ms:
            return  # Throttle (too soon)

        # Update last broadcast timestamp
        self._last_ticker_broadcast[symbol] = timestamp_ms

        # Broadcast ticker message
        try:
            from infrastructure.ws.models import create_ticker_message

            timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=self.tz)

            # Note: seq will be assigned by hub.broadcast()
            message = create_ticker_message(
                seq=0,  # Placeholder, hub will assign
                symbol=symbol,
                price=price,
                timestamp=timestamp_dt
            )

            # Broadcast to ticker:SYMBOL channel
            await self.hub.broadcast(f"ticker:{symbol}", message)

        except Exception as e:
            logger.error(f"Error broadcasting ticker: {e}")

    async def _handle_completed_candle(self, symbol: str, candle: Candle):
        """
        Handle completed candle

        Args:
            symbol: Symbol name
            candle: Completed candle
        """
        logger.info(
            f"Candle completed: {symbol} @ {candle.timestamp} - "
            f"O={candle.open:.5f} H={candle.high:.5f} L={candle.low:.5f} C={candle.close:.5f}"
        )

        # Persist to storage
        try:
            self.candle_store.append(candle)
            logger.debug(f"Candle persisted: {symbol} @ {candle.timestamp}")
        except Exception as e:
            logger.error(f"Error persisting candle: {e}")

        # Broadcast via WebSocket
        await self._broadcast_candle(symbol, candle)

    async def _broadcast_candle(self, symbol: str, candle: Candle):
        """
        Broadcast completed candle via WebSocket

        Args:
            symbol: Symbol name
            candle: Completed candle
        """
        if self.hub is None:
            return  # No WebSocket hub configured

        try:
            from infrastructure.ws.models import create_candle_message

            # Convert candle to dict
            candle_data = {
                "timestamp": candle.timestamp.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }

            # Note: seq will be assigned by hub.broadcast()
            message = create_candle_message(
                seq=0,  # Placeholder, hub will assign
                symbol=symbol,
                timeframe="1m",
                candle_data=candle_data,
                timestamp=datetime.now(tz=self.tz)
            )

            # Broadcast to candle:SYMBOL:1m channel
            await self.hub.broadcast(f"candle:{symbol}:1m", message)

        except Exception as e:
            logger.error(f"Error broadcasting candle: {e}")

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get latest cached price for symbol

        Args:
            symbol: Symbol name

        Returns:
            Latest price or None if not available
        """
        return self._latest_price.get(symbol)

    def get_all_latest_prices(self) -> Dict[str, float]:
        """Get all latest prices (snapshot)"""
        return dict(self._latest_price)

    async def health_check(self) -> bool:
        """
        Check if service is healthy

        Returns:
            True if service is operational, False otherwise
        """
        return self._running

    @property
    def is_running(self) -> bool:
        """Check if service is currently running"""
        return self._running
