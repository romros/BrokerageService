"""
Candle (OHLCV) data models

Canonical representation:
- Timestamp represents start-of-minute (epoch UTC internally)
- Candle represents [ts, ts+60s) and only written when closed
- Volume = 0 when real volume unavailable
- Timezone for storage/API: America/New_York
"""


from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Candle:
    """
    OHLCV candle (1-minute resolution)

    Attributes:
        symbol: Trading pair (e.g., "XAUUSD", "EURUSD")
        timestamp: Start of minute (epoch UTC)
        open: Open price
        high: High price
        low: Low price
        close: Close price
        volume: Volume (0 if unavailable)
        is_closed: Whether this candle is finalized
    """
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_closed: bool = True

    def __post_init__(self):
        """Validate candle data"""
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if self.open > self.high or self.open < self.low:
            raise ValueError(f"Open ({self.open}) must be between low ({self.low}) and high ({self.high})")
        if self.close > self.high or self.close < self.low:
            raise ValueError(f"Close ({self.close}) must be between low ({self.low}) and high ({self.high})")
        if self.volume < 0:
            raise ValueError(f"Volume ({self.volume}) cannot be negative")

    @property
    def range(self) -> float:
        """Get price range (high - low)"""
        return self.high - self.low

    @property
    def body(self) -> float:
        """Get candle body size (abs(close - open))"""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish (close > open)"""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """Check if candle is bearish (close < open)"""
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        """Check if candle is doji (close ~= open)"""
        return abs(self.close - self.open) < (self.range * 0.1) if self.range > 0 else True

    def to_csv_row(self) -> str:
        """
        Convert to CSV row format
        Format: ts,open,high,low,close,volume
        """
        # Convert datetime to epoch (seconds)
        ts_epoch = int(self.timestamp.timestamp())
        return f"{ts_epoch},{self.open},{self.high},{self.low},{self.close},{self.volume}"

    @classmethod
    def from_csv_row(cls, symbol: str, row: str) -> "Candle":
        """
        Create Candle from CSV row
        Format: ts,open,high,low,close,volume

        Args:
            symbol: Trading pair
            row: CSV row string

        Returns:
            Candle instance
        """
        parts = row.strip().split(',')
        if len(parts) != 6:
            raise ValueError(f"Invalid CSV row format: expected 6 fields, got {len(parts)}")

        ts_epoch = int(parts[0])
        timestamp = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)

        return cls(
            symbol=symbol,
            timestamp=timestamp,
            open=float(parts[1]),
            high=float(parts[2]),
            low=float(parts[3]),
            close=float(parts[4]),
            volume=float(parts[5]),
            is_closed=True
        )


@dataclass
class CandleRange:
    """
    Request/response for OHLCV range queries

    Attributes:
        symbol: Trading pair
        start: Start timestamp (inclusive)
        end: End timestamp (exclusive)
        candles: List of candles
        is_complete: Whether range has no gaps
        missing_count: Number of missing candles (gaps)
    """
    symbol: str
    start: datetime
    end: datetime
    candles: list[Candle]
    is_complete: bool = True
    missing_count: int = 0

    @property
    def count(self) -> int:
        """Number of candles in range"""
        return len(self.candles)

    @property
    def expected_count(self) -> int:
        """Expected number of 1-minute candles in range"""
        delta_seconds = (self.end - self.start).total_seconds()
        return int(delta_seconds / 60)

    def validate_completeness(self) -> bool:
        """
        Validate if range is complete (no gaps)
        Updates is_complete and missing_count
        """
        expected = self.expected_count
        actual = self.count
        self.missing_count = max(0, expected - actual)
        self.is_complete = (self.missing_count == 0)
        return self.is_complete
