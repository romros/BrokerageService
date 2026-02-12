"""
gTrade Price Provider

Implementació de proveïdor de preus basat en WebSocket feed de gTrade.
"""

from typing import Protocol, Optional
import asyncio

from foundation.logging import get_logger
from .price_feed_ws_client import GTradePriceFeedWSClient
from .config import DEFAULT_GTRADE_PRICE_WS_URL

logger = get_logger(__name__)


class IPriceProvider(Protocol):
    """
    Interface per proveïdors de preus

    Permet obtenir preus de mercat actuals per símbol.
    """

    async def start(self) -> None:
        """Initialize price provider (connect, start polling, etc.)"""
        ...

    async def stop(self) -> None:
        """Stop price provider and cleanup resources"""
        ...

    async def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for symbol

        Args:
            symbol: Trading symbol (e.g., "BTCUSD", "ETHUSD")

        Returns:
            Current price as float (e.g., 70457.42 for BTC)

        Raises:
            ValueError: If price not available
        """
        ...


class GTradePriceProviderWS:
    """
    WebSocket-based price provider using gTrade feed

    Uses GTradePriceFeedWSClient to get real-time prices from:
    wss://feed-gtrade-arb.gainsnetwork.io/ws

    Thread-safe, non-blocking price queries via cached latest values.
    """

    def __init__(
        self,
        ws_url: str = DEFAULT_GTRADE_PRICE_WS_URL,
        warmup_seconds: float = 5.0,
    ):
        """
        Initialize price provider

        Args:
            ws_url: WebSocket URL (default: gTrade feed)
            warmup_seconds: Time to wait for initial prices (default: 5s)
        """
        self._ws_url = ws_url
        self._warmup_seconds = warmup_seconds
        self._client: Optional[GTradePriceFeedWSClient] = None
        self._started = False

        logger.info(f"GTradePriceProviderWS initialized: url={ws_url}")

    async def start(self) -> None:
        """Start WebSocket client and wait for initial prices"""
        if self._started:
            logger.warning("Price provider already started")
            return

        logger.info("Starting price provider...")

        # Create and start WS client
        self._client = GTradePriceFeedWSClient(ws_url=self._ws_url)
        await self._client.start()

        # Wait for initial prices
        logger.info(f"Waiting {self._warmup_seconds}s for initial prices...")
        await asyncio.sleep(self._warmup_seconds)

        # Verify we have some prices
        prices = await self._client.get_all_latest_prices()
        if not prices:
            logger.warning("No prices received during warmup")
        else:
            logger.info(f"✓ Received prices for {len(prices)} symbols: {list(prices.keys())}")

        self._started = True

    async def stop(self) -> None:
        """Stop WebSocket client"""
        if not self._started:
            return

        logger.info("Stopping price provider...")

        if self._client:
            await self._client.stop()
            self._client = None

        self._started = False

    async def get_current_price(self, symbol: str) -> float:
        """
        Get latest cached price for symbol (non-blocking)

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")

        Returns:
            Current price as float

        Raises:
            ValueError: If price not available or provider not started
        """
        if not self._started or not self._client:
            raise ValueError("Price provider not started")

        price = await self._client.get_latest_price(symbol)

        if price is None:
            raise ValueError(f"Price not available for {symbol}")

        return price

    async def get_all_prices(self) -> dict[str, float]:
        """
        Get all available prices

        Returns:
            Dict mapping symbol → price
        """
        if not self._started or not self._client:
            return {}

        return await self._client.get_all_latest_prices()
