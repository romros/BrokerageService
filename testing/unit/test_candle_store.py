"""
Unit test for CSVCandleStore

Tests:
- Read/write operations
- Append new candles
- Patch existing candles
- Get last timestamp
- Coverage statistics
- Integrity validation
"""


from datetime import datetime, timedelta
from pathlib import Path
import shutil
import sys
import tempfile

from zoneinfo import ZoneInfo


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore


def test_append_and_read():
    """Test appending candles and reading them back"""
    print("Testing append and read...")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(
            root_path=tmpdir,
            broker="test",
            canonical_tz="America/New_York",
        )

        # Create test candles
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        candles = [
            Candle(
                symbol="XAUUSD",
                timestamp=base_time + timedelta(minutes=i),
                open=2700.0 + i,
                high=2701.0 + i,
                low=2699.0 + i,
                close=2700.5 + i,
                volume=100.0,
            )
            for i in range(5)
        ]

        # Append candles
        for candle in candles:
            result = store.append(candle)
            assert result is True, f"Failed to append candle {candle.timestamp}"

        # Try appending duplicate (should return False)
        result = store.append(candles[0])
        assert result is False, "Duplicate candle should not be appended"

        # Read back
        start = base_time
        end = base_time + timedelta(minutes=5)

        candle_range = store.read_range("XAUUSD", start, end, validate_gaps=True)

        assert candle_range.count == 5, f"Expected 5 candles, got {candle_range.count}"
        assert candle_range.is_complete is True, "Range should be complete"
        assert candle_range.candles[0].open == 2700.0, "First candle open mismatch"
        assert candle_range.candles[-1].open == 2704.0, "Last candle open mismatch"

    print("✓ Append and read test passed")


def test_patch():
    """Test patching (updating) candles"""
    print("Testing patch...")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="test")

        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        # Initial candles with gap
        candles = [
            Candle(
                symbol="EURUSD",
                timestamp=base_time,
                open=1.05,
                high=1.051,
                low=1.049,
                close=1.0505,
                volume=50.0,
            ),
            # Gap here (minute 1 missing)
            Candle(
                symbol="EURUSD",
                timestamp=base_time + timedelta(minutes=2),
                open=1.051,
                high=1.052,
                low=1.050,
                close=1.0515,
                volume=50.0,
            ),
        ]

        for candle in candles:
            store.append(candle)

        # Verify gap exists
        candle_range = store.read_range(
            "EURUSD",
            base_time,
            base_time + timedelta(minutes=3),
            validate_gaps=True,
        )
        assert candle_range.is_complete is False, "Should have gap"
        assert candle_range.missing_count == 1, "Should have 1 missing candle"

        # Patch missing candle
        missing_candle = Candle(
            symbol="EURUSD",
            timestamp=base_time + timedelta(minutes=1),
            open=1.0505,
            high=1.0515,
            low=1.0495,
            close=1.051,
            volume=50.0,
        )

        written = store.patch([missing_candle])
        assert written == 1, f"Expected 1 candle written, got {written}"

        # Verify gap filled
        candle_range = store.read_range(
            "EURUSD",
            base_time,
            base_time + timedelta(minutes=3),
            validate_gaps=True,
        )
        assert candle_range.is_complete is True, "Gap should be filled"
        assert candle_range.count == 3, f"Expected 3 candles, got {candle_range.count}"

    print("✓ Patch test passed")


def test_get_last_timestamp():
    """Test getting last stored timestamp"""
    print("Testing get_last_timestamp...")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="test")

        # No data yet
        last_ts = store.get_last_timestamp("XAUUSD")
        assert last_ts is None, "Should return None for empty store"

        # Add candles
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 15, 30, 0, tzinfo=tz)

        for i in range(3):
            candle = Candle(
                symbol="XAUUSD",
                timestamp=base_time + timedelta(minutes=i),
                open=2700.0,
                high=2701.0,
                low=2699.0,
                close=2700.0,
                volume=100.0,
            )
            store.append(candle)

        # Get last timestamp
        last_ts = store.get_last_timestamp("XAUUSD")
        assert last_ts is not None, "Should return timestamp"
        assert last_ts == base_time + timedelta(minutes=2), "Last timestamp mismatch"

    print("✓ get_last_timestamp test passed")


def test_coverage():
    """Test coverage statistics"""
    print("Testing coverage...")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="test")

        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 12, 0, 0, tzinfo=tz)

        # Add 7 out of 10 candles (70% coverage)
        for i in [0, 1, 2, 5, 6, 7, 9]:
            candle = Candle(
                symbol="EURUSD",
                timestamp=base_time + timedelta(minutes=i),
                open=1.05,
                high=1.051,
                low=1.049,
                close=1.05,
                volume=50.0,
            )
            store.append(candle)

        # Check coverage
        actual, expected, percent = store.get_coverage(
            "EURUSD",
            base_time,
            base_time + timedelta(minutes=10),
        )

        assert actual == 7, f"Expected 7 actual, got {actual}"
        assert expected == 10, f"Expected 10 expected, got {expected}"
        assert 69 <= percent <= 71, f"Expected ~70% coverage, got {percent}%"

    print("✓ Coverage test passed")


def test_validate_integrity():
    """Test integrity validation"""
    print("Testing validate_integrity...")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="test")

        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 9, 0, 0, tzinfo=tz)

        # Add valid candles (no gaps)
        for i in range(5):
            candle = Candle(
                symbol="XAUUSD",
                timestamp=base_time + timedelta(minutes=i),
                open=2700.0,
                high=2701.0,
                low=2699.0,
                close=2700.0,
                volume=100.0,
            )
            store.append(candle)

        # Validation should pass
        try:
            is_valid = store.validate_integrity(
                "XAUUSD",
                base_time,
                base_time + timedelta(minutes=5),
            )
            assert is_valid is True, "Validation should pass"
        except ValueError as e:
            assert False, f"Validation should not raise error: {e}"

    print("✓ validate_integrity test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CSVCandleStore Unit Tests")
    print("="*60 + "\n")

    try:
        test_append_and_read()
        test_patch()
        test_get_last_timestamp()
        test_coverage()
        test_validate_integrity()

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
