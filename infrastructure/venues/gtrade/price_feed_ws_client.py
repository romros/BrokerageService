"""
gTrade Price Feed WebSocket Client

Connects to gTrade's price feed WebSocket and parses price updates.

Protocol:
- Price updates: [pairId, price, pairId, price, ...]
- Ping messages: [timestamp_ms]

Features:
- Automatic reconnection with exponential backoff
- Parse price updates to (symbol, price, timestamp_ms)
- Async queue for tick consumption
- Thread-safe latest_price cache
"""


from datetime import datetime
from typing import Optional, Dict, Tuple
import asyncio
import json
import time


try:
    # Dep opcional: websockets no sempre instal·lat (tests poden mockejar)
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    # Allow import without websockets for testing
    websockets = None
    ConnectionClosed = Exception

from foundation.logging import get_logger
from .config import (
    DEFAULT_GTRADE_PRICE_WS_URL,
    GTRADE_PAIR_ID_TO_SYMBOL,
    DEFAULT_RECONNECT_DELAY_SECONDS,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
)

logger = get_logger(__name__)


class GTradePriceFeedWSClient:
    """
    WebSocket client for gTrade price feed

    Connects to gTrade backend, receives price updates,
    and exposes them via async queue for consumption.
    """

    def __init__(
        self,
        ws_url: str = DEFAULT_GTRADE_PRICE_WS_URL,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY_SECONDS,
        max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS,
    ):
        """
        Initialize gTrade price feed client

        Args:
            ws_url: WebSocket URL
            reconnect_delay: Delay between reconnection attempts (seconds)
            max_reconnect_attempts: Maximum reconnection attempts (0 = infinite)
        """
        if websockets is None:
            raise ImportError("websockets package required for GTradePriceFeedWSClient")

        self.ws_url = ws_url
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # State
        self._ws = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Tick queue (consumed by LiveMarketDataService)
        self._tick_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Latest price cache (symbol -> price)
        self._latest_price: Dict[str, float] = {}
        self._lock = asyncio.Lock()

        logger.info(
            f"GTradePriceFeedWSClient initialized: url={ws_url}, "
            f"reconnect_delay={reconnect_delay}s"
        )

    async def start(self):
        """Start WebSocket client (non-blocking)"""
        if self._running:
            logger.warning("GTradePriceFeedWSClient already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        logger.info("GTradePriceFeedWSClient started")

    async def stop(self):
        """Stop WebSocket client"""
        if not self._running:
            return

        logger.info("Stopping GTradePriceFeedWSClient...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()

        logger.info("GTradePriceFeedWSClient stopped")

    async def _run_forever(self):
        """Main loop with reconnection logic"""
        attempt = 0

        while self._running:
            try:
                await self._connect_and_listen()
                attempt = 0  # Reset on successful connection
            except asyncio.CancelledError:
                break
            except Exception as e:
                attempt += 1
                logger.error(f"Connection error (attempt {attempt}): {e}")

                if 0 < self.max_reconnect_attempts <= attempt:
                    logger.error("Max reconnection attempts reached, stopping")
                    break

                # Exponential backoff (cap at 60s)
                delay = min(self.reconnect_delay * (2 ** (attempt - 1)), 60.0)
                logger.info(f"Reconnecting in {delay:.1f}s...")
                await asyncio.sleep(delay)

    async def _connect_and_listen(self):
        """Connect to WebSocket and listen for messages"""
        logger.info(f"Connecting to {self.ws_url}...")

        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            logger.info("✓ Connected to gTrade price feed")

            while self._running:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    logger.warning("No message received for 30s (connection alive?)")
                    # Send ping to check connection
                    try:
                        await ws.ping()
                    except Exception:
                        raise ConnectionError("Connection lost (ping failed)")

    async def _handle_message(self, message: str):
        """
        Parse and handle WebSocket message

        Message formats:
        - Price updates: [pairId, price, pairId, price, ...]
        - Ping: [timestamp_ms]
        """
        try:
            data = json.loads(message)

            if not isinstance(data, list):
                logger.warning(f"Invalid message format (not array): {message[:100]}")
                return

            # Ping message (single element array with timestamp)
            if len(data) == 1:
                # Pong (no action needed, websockets handles it)
                return

            # Price updates (even length array: [id, price, id, price, ...])
            if len(data) % 2 != 0:
                logger.warning(f"Invalid price update (odd length): {data}")
                return

            # Parse price pairs
            timestamp_ms = int(time.time() * 1000)
            ticks = []

            for i in range(0, len(data), 2):
                pair_id = data[i]
                price = data[i + 1]

                # Validate
                if not isinstance(pair_id, int) or not isinstance(price, (int, float)):
                    logger.warning(f"Invalid price data: pair_id={pair_id}, price={price}")
                    continue

                # Map pairId to symbol
                symbol = GTRADE_PAIR_ID_TO_SYMBOL.get(pair_id)
                if symbol is None:
                    # Unknown pair ID (ignore silently - not subscribed)
                    continue

                # Convert to float
                price_float = float(price)
                ticks.append((symbol, price_float, timestamp_ms))

                # Update cache
                async with self._lock:
                    self._latest_price[symbol] = price_float

            # Queue ticks for consumption (blocking to prevent loss)
            for tick in ticks:
                await self._tick_queue.put(tick)

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def get_ticks(self) -> Tuple[str, float, int]:
        """
        Get next tick from queue (blocks until available)

        Returns:
            Tuple of (symbol, price, timestamp_ms)
        """
        return await self._tick_queue.get()

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get latest cached price for symbol

        Args:
            symbol: Symbol name (e.g., "XAUUSD")

        Returns:
            Latest price or None if not available
        """
        async with self._lock:
            return self._latest_price.get(symbol)

    async def get_all_latest_prices(self) -> Dict[str, float]:
        """Get all latest prices (snapshot)"""
        async with self._lock:
            return dict(self._latest_price)
