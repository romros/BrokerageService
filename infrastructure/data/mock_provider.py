"""
MockBackfillProvider - Generate synthetic OHLCV data for testing

Features:
- Generates realistic candle data
- No external dependencies
- Configurable price behavior (trending, ranging, volatile)
- Always available (no API calls)

Usage:
    provider = MockBackfillProvider(base_price=2700.0, volatility=0.001)
    candles = await provider.fetch_ohlcv("XAUUSD", start, end)
"""


from datetime import datetime, timedelta
from typing import List, Optional
import random

from domain.interfaces import IBackfillProvider
from domain.models import Candle
from foundation.logging import get_logger


logger = get_logger(__name__)


class MockBackfillProvider(IBackfillProvider):
    """
    Mock backfill provider for testing

    Generates synthetic candles with realistic OHLC behavior
    """

    def __init__(
        self,
        base_price: float = 2700.0,
        volatility: float = 0.001,
        trend: float = 0.0,
        seed: Optional[int] = None,
    ):
        """
        Initialize mock provider

        Args:
            base_price: Starting price
            volatility: Price volatility (0.001 = 0.1%)
            trend: Price trend per minute (0.0 = no trend, 0.001 = +0.1% per minute)
            seed: Random seed for deterministic testing (None = non-deterministic)
        """
        self.base_price = base_price
        self.volatility = volatility
        self.trend = trend
        self.seed = seed

        # Set random seed if provided (for deterministic tests)
        if seed is not None:
            random.seed(seed)

        logger.info(
            f"MockBackfillProvider initialized: base_price={base_price}, "
            f"volatility={volatility}, trend={trend}, seed={seed}"
        )

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch mock OHLCV candles

        Args:
            symbol: Trading pair
            start: Start timestamp (inclusive)
            end: End timestamp (exclusive)

        Returns:
            List of synthetic candles
        """
        candles = []

        # Generate candle for each minute
        current = start.replace(second=0, microsecond=0)
        current_price = self.base_price
        minute_count = 0

        while current < end:
            # Apply trend
            trend_delta = current_price * self.trend
            current_price += trend_delta

            # Generate OHLC with realistic behavior
            candle = self._generate_candle(symbol, current, current_price)
            candles.append(candle)

            # Update price for next candle (random walk)
            change = random.gauss(0, self.volatility * current_price)
            current_price += change

            # Move to next minute
            current += timedelta(minutes=1)
            minute_count += 1

        logger.debug(
            f"Generated {len(candles)} mock candles for {symbol} "
            f"[{start} to {end}]"
        )

        return candles

    async def is_available(self) -> bool:
        """
        Check if provider is available

        Returns:
            Always True (mock data always available)
        """
        return True

    @property
    def provider_name(self) -> str:
        """Get provider name"""
        return "mock"

    @property
    def max_range_minutes(self) -> int:
        """Get maximum range per request"""
        return 100000  # No practical limit for mock data

    def _generate_candle(
        self,
        symbol: str,
        timestamp: datetime,
        base_price: float,
    ) -> Candle:
        """
        Generate a single realistic candle

        Args:
            symbol: Trading pair
            timestamp: Candle timestamp
            base_price: Base price for this candle

        Returns:
            Candle with realistic OHLC
        """
        # Generate price movements within the minute
        price_range = base_price * self.volatility * 2

        # Open at base price with small random offset
        open_price = base_price + random.gauss(0, price_range * 0.3)

        # High/low relative to open
        high_offset = abs(random.gauss(0, price_range))
        low_offset = abs(random.gauss(0, price_range))

        high = open_price + high_offset
        low = open_price - low_offset

        # Close somewhere between high and low
        close_range = high - low
        if close_range > 0:
            close = low + random.random() * close_range
        else:
            close = open_price

        # Ensure OHLC constraints
        high = max(high, open_price, close)
        low = min(low, open_price, close)

        # Volume (random but consistent)
        volume = random.uniform(50.0, 200.0)

        return Candle(
            symbol=symbol,
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            is_closed=True,
        )
