"""
gTrade venue integration

Components:
- price_feed_ws_client: WebSocket client for live price feed
- config: Configuration constants and mappings

References:
- https://gains.trade/
- https://docs.gains.trade/
"""


from .config import (
    DEFAULT_GTRADE_PRICE_WS_URL,
    GTRADE_PAIR_ID_TO_SYMBOL,
    GTRADE_SYMBOL_TO_PAIR_ID,
    GTRADE_SUPPORTED_SYMBOLS,
)
from .price_feed_ws_client import GTradePriceFeedWSClient

__all__ = [
    "GTradePriceFeedWSClient",
    "DEFAULT_GTRADE_PRICE_WS_URL",
    "GTRADE_PAIR_ID_TO_SYMBOL",
    "GTRADE_SYMBOL_TO_PAIR_ID",
    "GTRADE_SUPPORTED_SYMBOLS",
]
