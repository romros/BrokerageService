"""
GapValidator - Validates candle data for gaps and integrity

Features:
- Detect missing minutes (gaps)
- Detect duplicates
- Validate chronological order
- Calculate coverage statistics
- Generate gap reports

Used by:
- CSVCandleStore (validation)
- Backfill scheduler (identify what needs filling)
- Health checks (data quality monitoring)
"""


from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from domain.models import Candle
from foundation.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Gap:
    """Represents a gap in candle data"""
    start: datetime  # First missing timestamp
    end: datetime    # Last missing timestamp (exclusive)
    count: int       # Number of missing minutes

    def __str__(self) -> str:
        return f"Gap({self.start} to {self.end}, {self.count} minutes)"


@dataclass
class ValidationReport:
    """Validation report with detailed statistics"""
    symbol: str
    start: datetime
    end: datetime
    actual_count: int
    expected_count: int
    missing_count: int
    coverage_percent: float
    has_gaps: bool
    has_duplicates: bool
    is_sorted: bool
    gaps: List[Gap]

    def is_valid(self) -> bool:
        """Check if data is valid (no gaps, duplicates, sorted)"""
        return not self.has_gaps and not self.has_duplicates and self.is_sorted

    def __str__(self) -> str:
        status = "✓ VALID" if self.is_valid() else "✗ INVALID"
        return (
            f"{status} - {self.symbol} [{self.start} to {self.end}]\n"
            f"  Coverage: {self.actual_count}/{self.expected_count} "
            f"({self.coverage_percent:.1f}%)\n"
            f"  Gaps: {len(self.gaps)} ({self.missing_count} minutes)\n"
            f"  Duplicates: {'Yes' if self.has_duplicates else 'No'}\n"
            f"  Sorted: {'Yes' if self.is_sorted else 'No'}"
        )


class GapValidator:
    """
    Validator for candle data integrity

    Validates:
    - No gaps (all minutes present)
    - No duplicates
    - Chronological order
    - OHLC values valid
    """

    @staticmethod
    def validate(
        candles: List[Candle],
        start: datetime,
        end: datetime,
        symbol: str = "UNKNOWN",
    ) -> ValidationReport:
        """
        Validate candle data and generate report

        Args:
            candles: List of candles to validate (assumed sorted)
            start: Expected start timestamp (inclusive)
            end: Expected end timestamp (exclusive)
            symbol: Trading pair (for reporting)

        Returns:
            ValidationReport with detailed statistics
        """
        if not candles:
            expected_count = int((end - start).total_seconds() / 60)
            return ValidationReport(
                symbol=symbol,
                start=start,
                end=end,
                actual_count=0,
                expected_count=expected_count,
                missing_count=expected_count,
                coverage_percent=0.0,
                has_gaps=True,
                has_duplicates=False,
                is_sorted=True,
                gaps=[Gap(start=start, end=end, count=expected_count)],
            )

        actual_count = len(candles)
        expected_count = int((end - start).total_seconds() / 60)
        missing_count = max(0, expected_count - actual_count)
        coverage_percent = (actual_count / expected_count * 100) if expected_count > 0 else 0.0

        # Check for duplicates
        timestamps = [c.timestamp for c in candles]
        has_duplicates = len(timestamps) != len(set(timestamps))

        # Check if sorted
        is_sorted = all(
            candles[i].timestamp < candles[i + 1].timestamp
            for i in range(len(candles) - 1)
        )

        # Find gaps
        gaps = GapValidator.find_gaps(candles, start, end)

        has_gaps = len(gaps) > 0

        return ValidationReport(
            symbol=symbol,
            start=start,
            end=end,
            actual_count=actual_count,
            expected_count=expected_count,
            missing_count=missing_count,
            coverage_percent=coverage_percent,
            has_gaps=has_gaps,
            has_duplicates=has_duplicates,
            is_sorted=is_sorted,
            gaps=gaps,
        )

    @staticmethod
    def find_gaps(
        candles: List[Candle],
        start: datetime,
        end: datetime,
    ) -> List[Gap]:
        """
        Find all gaps in candle data

        Args:
            candles: List of candles (assumed sorted)
            start: Expected start timestamp
            end: Expected end timestamp

        Returns:
            List of Gap objects
        """
        if not candles:
            count = int((end - start).total_seconds() / 60)
            return [Gap(start=start, end=end, count=count)]

        gaps = []

        # Check gap before first candle
        first_candle = candles[0]
        if first_candle.timestamp > start:
            gap_minutes = int((first_candle.timestamp - start).total_seconds() / 60)
            if gap_minutes > 0:
                gaps.append(Gap(
                    start=start,
                    end=first_candle.timestamp,
                    count=gap_minutes,
                ))

        # Check gaps between candles
        for i in range(len(candles) - 1):
            current = candles[i]
            next_candle = candles[i + 1]

            expected_next = current.timestamp + timedelta(minutes=1)

            if next_candle.timestamp > expected_next:
                gap_minutes = int((next_candle.timestamp - expected_next).total_seconds() / 60)
                gaps.append(Gap(
                    start=expected_next,
                    end=next_candle.timestamp,
                    count=gap_minutes,
                ))

        # Check gap after last candle
        last_candle = candles[-1]
        expected_last = end - timedelta(minutes=1)

        if last_candle.timestamp < expected_last:
            gap_start = last_candle.timestamp + timedelta(minutes=1)
            gap_minutes = int((end - gap_start).total_seconds() / 60)
            if gap_minutes > 0:
                gaps.append(Gap(
                    start=gap_start,
                    end=end,
                    count=gap_minutes,
                ))

        return gaps

    @staticmethod
    def check_integrity(candles: List[Candle]) -> Tuple[bool, str]:
        """
        Quick integrity check

        Args:
            candles: List of candles

        Returns:
            (is_valid, error_message)
        """
        if not candles:
            return True, ""

        # Check sorted
        for i in range(len(candles) - 1):
            if candles[i].timestamp >= candles[i + 1].timestamp:
                return False, f"Not sorted at index {i}"

        # Check duplicates
        timestamps = [c.timestamp for c in candles]
        if len(timestamps) != len(set(timestamps)):
            return False, "Duplicate timestamps found"

        # Check OHLC validity
        for i, candle in enumerate(candles):
            try:
                # This will raise ValueError if OHLC invalid
                # (validation happens in Candle.__post_init__)
                _ = candle.range
            except ValueError as e:
                return False, f"Invalid OHLC at index {i}: {e}"

        return True, ""

    @staticmethod
    def get_missing_ranges(
        gaps: List[Gap],
        max_range_size: int = 1000,
    ) -> List[Tuple[datetime, datetime]]:
        """
        Convert gaps into fetchable ranges for backfill

        Args:
            gaps: List of gaps
            max_range_size: Maximum minutes per range (for chunking)

        Returns:
            List of (start, end) tuples for backfill requests

        Note:
            - Chunks large gaps into smaller ranges
            - Merges adjacent gaps if possible
        """
        if not gaps:
            return []

        ranges = []

        for gap in gaps:
            # If gap is small enough, add as-is
            if gap.count <= max_range_size:
                ranges.append((gap.start, gap.end))
            else:
                # Chunk large gap
                current = gap.start
                while current < gap.end:
                    chunk_end = min(
                        current + timedelta(minutes=max_range_size),
                        gap.end
                    )
                    ranges.append((current, chunk_end))
                    current = chunk_end

        return ranges

    @staticmethod
    def log_report(report: ValidationReport) -> None:
        """
        Log validation report

        Args:
            report: Validation report to log
        """
        if report.is_valid():
            logger.info(f"✓ Validation passed: {report.symbol} - {report.actual_count} candles")
        else:
            logger.warning(f"✗ Validation failed: {report.symbol}")
            logger.warning(f"  Coverage: {report.coverage_percent:.1f}%")

            if report.has_gaps:
                logger.warning(f"  Found {len(report.gaps)} gaps ({report.missing_count} minutes):")
                for gap in report.gaps[:5]:  # Show first 5 gaps
                    logger.warning(f"    - {gap}")
                if len(report.gaps) > 5:
                    logger.warning(f"    ... and {len(report.gaps) - 5} more gaps")

            if report.has_duplicates:
                logger.warning("  Duplicate timestamps detected")

            if not report.is_sorted:
                logger.warning("  Data not chronologically sorted")
