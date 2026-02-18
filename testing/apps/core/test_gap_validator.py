"""
Unit test for GapValidator

Tests:
- Find gaps in candle data
- Validate integrity
- Generate validation reports
- Get missing ranges for backfill
"""


from datetime import datetime, timedelta
from pathlib import Path
import sys

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.gap_validator import GapValidator, Gap


def test_find_gaps():
    """Test gap detection"""
    print("Testing find_gaps...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Create candles with gaps
    candles = [
        Candle("XAUUSD", base_time, 2700, 2701, 2699, 2700, 100),
        # Gap: minute 1 missing
        Candle("XAUUSD", base_time + timedelta(minutes=2), 2700, 2701, 2699, 2700, 100),
        Candle("XAUUSD", base_time + timedelta(minutes=3), 2700, 2701, 2699, 2700, 100),
        # Gap: minutes 4-5 missing
        Candle("XAUUSD", base_time + timedelta(minutes=6), 2700, 2701, 2699, 2700, 100),
    ]

    start = base_time
    end = base_time + timedelta(minutes=7)

    gaps = GapValidator.find_gaps(candles, start, end)

    assert len(gaps) == 2, f"Expected 2 gaps, found {len(gaps)}"
    assert gaps[0].count == 1, f"First gap should be 1 minute, got {gaps[0].count}"
    assert gaps[1].count == 2, f"Second gap should be 2 minutes, got {gaps[1].count}"

    print("✓ find_gaps test passed")


def test_no_gaps():
    """Test with complete data (no gaps)"""
    print("Testing no gaps...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Complete candles
    candles = [
        Candle("EURUSD", base_time + timedelta(minutes=i), 1.05, 1.051, 1.049, 1.05, 50)
        for i in range(5)
    ]

    start = base_time
    end = base_time + timedelta(minutes=5)

    gaps = GapValidator.find_gaps(candles, start, end)

    assert len(gaps) == 0, f"Expected no gaps, found {len(gaps)}"

    print("✓ no gaps test passed")


def test_validate_report():
    """Test validation report generation"""
    print("Testing validation report...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Create candles with gap
    candles = [
        Candle("XAUUSD", base_time, 2700, 2701, 2699, 2700, 100),
        Candle("XAUUSD", base_time + timedelta(minutes=1), 2700, 2701, 2699, 2700, 100),
        # Gap: minute 2 missing
        Candle("XAUUSD", base_time + timedelta(minutes=3), 2700, 2701, 2699, 2700, 100),
    ]

    start = base_time
    end = base_time + timedelta(minutes=4)

    report = GapValidator.validate(candles, start, end, symbol="XAUUSD")

    assert report.symbol == "XAUUSD"
    assert report.actual_count == 3, f"Expected 3 candles, got {report.actual_count}"
    assert report.expected_count == 4, f"Expected 4 minutes, got {report.expected_count}"
    assert report.missing_count == 1, f"Expected 1 missing, got {report.missing_count}"
    assert report.has_gaps is True, "Should detect gap"
    assert report.is_sorted is True, "Should be sorted"
    assert report.has_duplicates is False, "Should have no duplicates"
    assert report.is_valid() is False, "Should be invalid due to gap"
    assert 74 <= report.coverage_percent <= 76, f"Expected ~75% coverage, got {report.coverage_percent}"

    print("✓ validation report test passed")


def test_check_integrity():
    """Test quick integrity check"""
    print("Testing check_integrity...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Valid candles
    valid_candles = [
        Candle("XAUUSD", base_time + timedelta(minutes=i), 2700, 2701, 2699, 2700, 100)
        for i in range(3)
    ]

    is_valid, error = GapValidator.check_integrity(valid_candles)
    assert is_valid is True, f"Should be valid: {error}"

    # Unsorted candles
    unsorted = [
        Candle("XAUUSD", base_time + timedelta(minutes=2), 2700, 2701, 2699, 2700, 100),
        Candle("XAUUSD", base_time + timedelta(minutes=1), 2700, 2701, 2699, 2700, 100),
    ]

    is_valid, error = GapValidator.check_integrity(unsorted)
    assert is_valid is False, "Should detect unsorted"
    assert "sorted" in error.lower(), f"Error should mention sorting: {error}"

    print("✓ check_integrity test passed")


def test_get_missing_ranges():
    """Test converting gaps to backfill ranges"""
    print("Testing get_missing_ranges...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Create gaps
    gaps = [
        Gap(start=base_time, end=base_time + timedelta(minutes=5), count=5),
        Gap(start=base_time + timedelta(minutes=10), end=base_time + timedelta(minutes=15), count=5),
    ]

    # Get ranges
    ranges = GapValidator.get_missing_ranges(gaps, max_range_size=1000)

    assert len(ranges) == 2, f"Expected 2 ranges, got {len(ranges)}"
    assert ranges[0][0] == base_time, "First range start mismatch"
    assert ranges[1][0] == base_time + timedelta(minutes=10), "Second range start mismatch"

    # Test chunking large gap
    large_gap = Gap(start=base_time, end=base_time + timedelta(minutes=2500), count=2500)
    ranges = GapValidator.get_missing_ranges([large_gap], max_range_size=1000)

    assert len(ranges) == 3, f"Expected 3 chunks, got {len(ranges)}"
    # First chunk: 0-1000
    # Second chunk: 1000-2000
    # Third chunk: 2000-2500

    print("✓ get_missing_ranges test passed")


def test_empty_data():
    """Test with empty data"""
    print("Testing empty data...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    start = base_time
    end = base_time + timedelta(minutes=10)

    report = GapValidator.validate([], start, end, symbol="EMPTY")

    assert report.actual_count == 0
    assert report.expected_count == 10
    assert report.missing_count == 10
    assert report.has_gaps is True
    assert len(report.gaps) == 1
    assert report.gaps[0].count == 10

    print("✓ empty data test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("GapValidator Unit Tests")
    print("="*60 + "\n")

    try:
        test_find_gaps()
        test_no_gaps()
        test_validate_report()
        test_check_integrity()
        test_get_missing_ranges()
        test_empty_data()

        print("\n" + "="*60)
        print("✓ All tests passed!")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
