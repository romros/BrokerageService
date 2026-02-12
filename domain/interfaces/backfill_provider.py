"""
IBackfillProvider - Interface for fetching historical OHLCV data

Responsibilities:
- Fetch historical candles from venue (if available)
- Fill gaps in local storage
- Support corrective window updates

Implementations:
- gTrade: may have historical endpoint (TBD)
- Dukascopy: read from pre-downloaded CSV files
- Mock: generate synthetic data for testing
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from domain.models import Candle


class IBackfillProvider(ABC):
    """
    Abstract interface for historical data provider

    Implementation depends on venue:
    - Some venues provide historical API (REST/GraphQL)
    - Some require pre-downloaded data (Dukascopy)
    - Paper/backtest may use mock data
    """

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch historical OHLCV candles

        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            start: Start timestamp (inclusive)
            end: End timestamp (exclusive)

        Returns:
            List of Candle objects (may be empty if no data available)

        Raises:
            NotImplementedError: If venue doesn't support historical data
            ConnectionError: If API request fails
            ValueError: If invalid parameters

        Note:
            - Returns candles in ascending order by timestamp
            - Returned candles should have is_closed=True
            - May return partial data if full range not available
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if backfill is available

        Returns:
            True if provider can fetch historical data

        Note:
            - Some venues may not have historical endpoints
            - Used to determine if backfill scheduler should run
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Get provider name

        Returns:
            Provider identifier (e.g., "gtrade", "dukascopy", "mock")
        """
        pass

    @property
    @abstractmethod
    def max_range_minutes(self) -> int:
        """
        Get maximum range that can be fetched in single request

        Returns:
            Maximum minutes per request (e.g., 1000, 10000)

        Note:
            - Used to chunk large backfill requests
            - Prevents API rate limits or timeout
        """
        pass
