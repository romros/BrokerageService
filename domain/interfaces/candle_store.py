"""
ICandleStore - Interface for OHLCV data persistence

Responsibilities:
- Read candle ranges from storage (CSV files)
- Append new closed candles
- Patch (update) ranges of candles (backfill/correction)
- Ensure atomic writes (no corruption)
- Support "no gaps" invariant validation

Storage layout:
  datafiles/{broker}/{asset}/{timezone}/{YYYY}/{MM}.csv

Format: ts,open,high,low,close,volume
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from domain.models import Candle, CandleRange


class ICandleStore(ABC):
    """
    Abstract interface for candle storage

    Implementation must ensure:
    - Thread-safe writes (file locks)
    - Atomic writes (tmp + rename)
    - Single-writer per symbol (avoid corruption)
    """

    @abstractmethod
    def read_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        validate_gaps: bool = True,
    ) -> CandleRange:
        """
        Read candles in time range [start, end)

        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            start: Start timestamp (inclusive)
            end: End timestamp (exclusive)
            validate_gaps: If True, check for gaps and set is_complete flag

        Returns:
            CandleRange with candles and gap info

        Note:
            - Returns empty list if no data available
            - If validate_gaps=True, sets is_complete=False if gaps detected
        """
        pass

    @abstractmethod
    def append(self, candle: Candle) -> bool:
        """
        Append a new closed candle

        Args:
            candle: Candle to append (must have is_closed=True)

        Returns:
            True if successful, False if candle already exists

        Note:
            - Only appends if timestamp > last stored timestamp
            - Writes atomically (tmp + rename)
            - Uses file lock to prevent concurrent writes
        """
        pass

    @abstractmethod
    def patch(self, candles: List[Candle]) -> int:
        """
        Patch (insert/update) multiple candles

        Used for:
        - Backfill missing data
        - Corrective updates (e.g., last N minutes)

        Args:
            candles: List of candles to patch

        Returns:
            Number of candles actually written/updated

        Note:
            - Reads existing data
            - Merges with new candles (prefer new data)
            - Writes atomically
            - Uses file lock
        """
        pass

    @abstractmethod
    def get_last_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        Get timestamp of last stored candle

        Args:
            symbol: Trading pair

        Returns:
            Timestamp of last candle, or None if no data

        Note:
            - Used to determine where to start appending
            - Used to calculate backfill range
        """
        pass

    @abstractmethod
    def get_coverage(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[int, int, float]:
        """
        Get data coverage statistics for a range

        Args:
            symbol: Trading pair
            start: Start timestamp
            end: End timestamp

        Returns:
            Tuple of (actual_count, expected_count, coverage_percent)

        Note:
            - expected_count = minutes between start and end
            - coverage_percent = (actual / expected) * 100
            - Used to check if backfill is needed
        """
        pass

    @abstractmethod
    def validate_integrity(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> bool:
        """
        Validate data integrity (no gaps, no duplicates, sorted)

        Args:
            symbol: Trading pair
            start: Start timestamp (optional, checks all data if None)
            end: End timestamp (optional)

        Returns:
            True if data is valid

        Raises:
            ValueError: If data integrity issues found (with details)

        Note:
            - Checks for gaps
            - Checks for duplicates
            - Checks timestamps are sorted
            - Checks OHLC values are valid
        """
        pass
