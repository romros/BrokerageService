"""
IPriceFeedClient - Protocol for live price tick feed

Used by LiveMarketDataService to consume ticks from any venue:
- gTrade: WebSocket (GTradePriceFeedWSClient)
- Lighter: Polling (LighterPriceFeedClient)

Contract:
- get_ticks() blocks until next (symbol, price, timestamp_ms)
- start() / stop() lifecycle
"""

from typing import Protocol, Tuple


class IPriceFeedClient(Protocol):
    """
    Protocol for price feed clients (tick stream)

    Implementations:
    - GTradePriceFeedWSClient (WebSocket)
    - LighterPriceFeedClient (polling)
    """

    async def get_ticks(self) -> Tuple[str, float, int]:
        """
        Get next tick (blocks until available)

        Returns:
            (symbol, price, timestamp_ms)
        """
        ...

    async def start(self) -> None:
        """Start the feed (connect / start polling loop)"""
        ...

    async def stop(self) -> None:
        """Stop the feed (disconnect / cancel loop)"""
        ...
