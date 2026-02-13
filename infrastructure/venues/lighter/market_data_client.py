"""
Lighter Market Data Client

Provides market data access via Lighter SDK OrderApi:
- list_order_books() - Get all markets
- get_order_book_orders() - Get orderbook (bid/ask) for a market

Features:
- Lazy import of SDK (avoids dependency if not using Lighter)
- Symbol → market_id cache (lazy loaded)
- Protocol interface for testing (mockable)

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Market Data Investigation
"""


from typing import Protocol, List, Optional, Dict
from datetime import datetime

from foundation.logging import get_logger

logger = get_logger(__name__)


class ILighterMarketDataClient(Protocol):
    """
    Protocol for Lighter market data client (mockable for tests)

    Methods:
        list_order_books() - Get all OrderBook objects
        get_order_book_orders() - Get orderbook (bids/asks) for market_id
    """

    async def list_order_books(self) -> List:
        """Get all OrderBook objects from Lighter"""
        ...

    async def get_order_book_orders(self, market_id: int, limit: int = 10):
        """Get OrderBookOrders (bids + asks) for market_id"""
        ...


class LighterMarketDataClient:
    """
    Lighter market data client (real SDK implementation)

    Uses OrderApi from lighter SDK to fetch:
    - Markets list (order_books)
    - Orderbook data (order_book_orders)

    Maintains lazy-loaded cache of symbol → market_id mapping.
    """

    def __init__(self, base_url: str):
        """
        Initialize market data client

        Args:
            base_url: Lighter API base URL (e.g., https://testnet.zklighter.elliot.ai)
        """
        self._base_url = base_url
        self._api_client = None  # Lazy initialized
        self._orders_api = None  # Lazy initialized
        self._symbol_to_market_id: Optional[Dict[str, int]] = None  # Lazy cache

        logger.info(f"LighterMarketDataClient initialized: base_url={base_url}")

    def _ensure_sdk_loaded(self):
        """Lazy load SDK (avoids import if not using Lighter)"""
        if self._api_client is None:
            try:
                import lighter
            except ImportError as e:
                raise ImportError(
                    "lighter SDK not installed. Install with: pip install lighter-python-sdk"
                ) from e

            self._api_client = lighter.ApiClient()
            self._orders_api = lighter.OrderApi(self._api_client)

    async def _ensure_market_cache_loaded(self):
        """
        Lazy load symbol → market_id cache

        Builds cache from order_books() on first access.
        """
        if self._symbol_to_market_id is not None:
            return

        self._ensure_sdk_loaded()

        logger.debug("Loading market cache from order_books()...")

        try:
            order_books_response = await self._orders_api.order_books()

            if not hasattr(order_books_response, 'order_books') or not order_books_response.order_books:
                logger.warning("order_books() returned empty list")
                self._symbol_to_market_id = {}
                return

            # Build cache: symbol → market_id
            cache = {}
            for order_book in order_books_response.order_books:
                market_id = getattr(order_book, 'market_id', None)
                symbol = getattr(order_book, 'symbol', None)

                if market_id is not None and symbol:
                    # Normalize symbol (uppercase, base only)
                    from .mappers import normalize_symbol
                    symbol_normalized = normalize_symbol(symbol)
                    cache[symbol_normalized] = market_id

                    # Also cache with "-USDC" suffix if not present
                    if not symbol_normalized.endswith("-USDC"):
                        cache[f"{symbol_normalized}-USDC"] = market_id

            self._symbol_to_market_id = cache
            logger.info(f"Market cache loaded: {len(cache)} symbols")

        except Exception as e:
            logger.error(f"Failed to load market cache: {e}")
            self._symbol_to_market_id = {}  # Empty cache on error
            raise

    async def list_order_books(self) -> List:
        """
        Get all OrderBook objects

        Returns:
            List of OrderBook objects

        Raises:
            ImportError: If lighter SDK not installed
            Exception: On API errors
        """
        self._ensure_sdk_loaded()

        try:
            order_books_response = await self._orders_api.order_books()

            if not hasattr(order_books_response, 'order_books'):
                logger.warning("order_books() response missing 'order_books' field")
                return []

            return order_books_response.order_books or []

        except Exception as e:
            logger.error(f"Failed to list order books: {e}")
            raise

    async def get_order_book_orders(self, market_id: int, limit: int = 10):
        """
        Get orderbook (bids + asks) for market_id

        Args:
            market_id: Market ID (e.g., 0 for ETH, 1 for BTC)
            limit: Number of bids/asks to return (default: 10)

        Returns:
            OrderBookOrders object with bids and asks lists

        Raises:
            ImportError: If lighter SDK not installed
            Exception: On API errors
        """
        self._ensure_sdk_loaded()

        try:
            order_book_orders = await self._orders_api.order_book_orders(
                market_id=market_id,
                limit=limit
            )

            return order_book_orders

        except Exception as e:
            logger.error(f"Failed to get orderbook for market_id={market_id}: {e}")
            raise

    def resolve_symbol_to_market_id(self, symbol: str) -> Optional[int]:
        """
        Resolve symbol to market_id using cache

        Args:
            symbol: Symbol (e.g., "ETH", "ETH-USDC")

        Returns:
            market_id or None if not found

        Note:
            Cache must be loaded first (call _ensure_market_cache_loaded()).
            This is a sync method for quick lookups.
        """
        if self._symbol_to_market_id is None:
            return None

        from .mappers import normalize_symbol
        symbol_normalized = normalize_symbol(symbol)

        return self._symbol_to_market_id.get(symbol_normalized)

    async def close(self):
        """Close API client connection"""
        if self._api_client:
            try:
                await self._api_client.close()
            except Exception as e:
                logger.warning(f"Error closing API client: {e}")
            finally:
                self._api_client = None
                self._orders_api = None
