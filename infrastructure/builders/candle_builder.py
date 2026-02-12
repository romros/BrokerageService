"""
CandleBuilder - Build 1-minute candles from ticks

Features:
- Accumulates ticks within current minute
- Updates OHLC as ticks arrive
- Detects minute transitions
- Finalizes candle when minute closes
- Timezone-aware (canonical TZ: America/New_York)

Usage:
    builder = CandleBuilder(symbol="XAUUSD", tz=ZoneInfo("America/New_York"))

    for tick in tick_stream:
        closed_candle = builder.on_tick(tick)
        if closed_candle:
            store.append(closed_candle)
"""


from datetime import datetime, timedelta
from typing import Optional

from zoneinfo import ZoneInfo

from domain.interfaces import ICandleBuilder
from domain.models import Tick, Candle
from foundation.logging import get_logger


logger = get_logger(__name__)


class CandleBuilder(ICandleBuilder):
    """
    Build 1-minute candles from price ticks

    Thread-safe for single symbol (not safe for concurrent updates)
    """

    def __init__(self, symbol: str, tz: Optional[ZoneInfo] = None):
        """
        Initialize candle builder

        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            tz: Timezone for minute boundaries (default: America/New_York)
        """
        self.symbol = symbol
        self.tz = tz or ZoneInfo("America/New_York")

        # Current candle state
        self._current_minute: Optional[datetime] = None
        self._open: Optional[float] = None
        self._high: Optional[float] = None
        self._low: Optional[float] = None
        self._close: Optional[float] = None
        self._volume: float = 0.0
        self._tick_count: int = 0

        logger.info(f"CandleBuilder initialized: symbol={symbol}, tz={self.tz}")

    def on_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Process a new tick

        Args:
            tick: Price tick with timestamp

        Returns:
            Closed candle if minute transition detected, None otherwise

        Logic:
            1. Get minute boundary for tick timestamp
            2. If different from current minute:
                - Finalize current candle (if any)
                - Start new candle
            3. Update OHLC with tick price
            4. Return finalized candle (if any)
        """
        if tick.symbol != self.symbol:
            logger.warning(f"Tick symbol mismatch: expected {self.symbol}, got {tick.symbol}")
            return None

        # Get minute boundary (start of minute)
        tick_minute = self._get_minute_boundary(tick.timestamp)

        # Check for minute transition
        closed_candle = None
        if self._current_minute is not None and tick_minute > self._current_minute:
            # Finalize current candle before starting new one
            closed_candle = self._finalize()

        # Initialize new minute if needed
        if self._current_minute is None or tick_minute > self._current_minute:
            self._start_new_minute(tick_minute)

        # Update OHLC with tick
        self._update_ohlc(tick)

        return closed_candle

    def finalize_current(self) -> Optional[Candle]:
        """
        Finalize current candle (force close)

        Returns:
            Current candle if any data accumulated, None otherwise

        Note:
            - Used when stream stops or service shutdown
            - Marks candle as closed even if minute not complete
        """
        return self._finalize()

    def get_current_minute(self) -> Optional[datetime]:
        """
        Get current minute boundary being built

        Returns:
            Start timestamp of current minute, None if no data yet
        """
        return self._current_minute

    def reset(self) -> None:
        """
        Reset builder state

        Note:
            - Clears current candle data
            - Used when switching symbols or restarting
        """
        self._current_minute = None
        self._open = None
        self._high = None
        self._low = None
        self._close = None
        self._volume = 0.0
        self._tick_count = 0

        logger.debug(f"CandleBuilder reset: symbol={self.symbol}")

    @property
    def has_data(self) -> bool:
        """Check if builder has accumulated any ticks"""
        return self._tick_count > 0

    # ============ INTERNAL METHODS ============

    def _get_minute_boundary(self, timestamp: datetime) -> datetime:
        """
        Get start-of-minute for given timestamp

        Args:
            timestamp: Tick timestamp

        Returns:
            Start of minute (seconds/microseconds zeroed)

        Note:
            - Ensures timezone-aware datetime
            - Converts to canonical TZ if needed
        """
        # Ensure timezone-aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=self.tz)
        else:
            # Convert to canonical TZ
            timestamp = timestamp.astimezone(self.tz)

        # Zero out seconds and microseconds
        return timestamp.replace(second=0, microsecond=0)

    def _start_new_minute(self, minute: datetime) -> None:
        """
        Start a new minute candle

        Args:
            minute: Start of minute timestamp
        """
        self._current_minute = minute
        self._open = None
        self._high = None
        self._low = None
        self._close = None
        self._volume = 0.0
        self._tick_count = 0

        logger.debug(f"Started new minute: {self.symbol} @ {minute}")

    def _update_ohlc(self, tick: Tick) -> None:
        """
        Update OHLC with new tick

        Args:
            tick: Price tick

        Logic:
            - First tick: sets open/high/low/close
            - Subsequent ticks: update high/low/close
            - Volume: accumulate if available
        """
        price = tick.price

        if self._open is None:
            # First tick of minute
            self._open = price
            self._high = price
            self._low = price
            self._close = price
        else:
            # Update high/low/close
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price

        # Accumulate volume if available
        if tick.volume is not None:
            self._volume += tick.volume

        self._tick_count += 1

    def _finalize(self) -> Optional[Candle]:
        """
        Finalize current candle

        Returns:
            Candle if data exists, None otherwise

        Note:
            - Only creates candle if at least one tick received
            - Marks candle as closed
        """
        if not self.has_data:
            return None

        candle = Candle(
            symbol=self.symbol,
            timestamp=self._current_minute,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            is_closed=True,
        )

        logger.debug(
            f"Finalized candle: {self.symbol} @ {self._current_minute} "
            f"[O={self._open:.4f} H={self._high:.4f} L={self._low:.4f} C={self._close:.4f}] "
            f"({self._tick_count} ticks)"
        )

        return candle
