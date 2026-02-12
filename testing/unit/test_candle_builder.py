"""
Unit test for CandleBuilder

Tests:
- Single tick → candle
- Multiple ticks within minute → single candle
- Minute transition → finalize + new candle
- OHLC calculation correctness
- Timezone handling
- Reset functionality
"""


from datetime import datetime, timedelta
from pathlib import Path
import sys

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Tick
from infrastructure.builders.candle_builder import CandleBuilder


def test_single_tick():
    """Test building candle from single tick"""
    print("Testing single tick...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    # Send one tick
    timestamp = datetime(2026, 2, 8, 10, 0, 30, tzinfo=tz)
    tick = Tick(symbol="XAUUSD", price=2700.0, timestamp=timestamp, volume=100.0)

    result = builder.on_tick(tick)
    assert result is None, "First tick should not close candle"
    assert builder.has_data is True, "Builder should have data"

    # Finalize manually
    candle = builder.finalize_current()
    assert candle is not None, "Should return candle"
    assert candle.open == 2700.0
    assert candle.high == 2700.0
    assert candle.low == 2700.0
    assert candle.close == 2700.0
    assert candle.volume == 100.0

    print("✓ Single tick test passed")


def test_multiple_ticks_same_minute():
    """Test accumulating multiple ticks within same minute"""
    print("Testing multiple ticks same minute...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="EURUSD", tz=tz)

    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Send 5 ticks within same minute
    ticks = [
        Tick("EURUSD", 1.0500, base_time + timedelta(seconds=0), 10.0),   # Open
        Tick("EURUSD", 1.0520, base_time + timedelta(seconds=15), 20.0),  # High
        Tick("EURUSD", 1.0480, base_time + timedelta(seconds=30), 15.0),  # Low
        Tick("EURUSD", 1.0510, base_time + timedelta(seconds=45), 25.0),  # Mid
        Tick("EURUSD", 1.0505, base_time + timedelta(seconds=59), 30.0),  # Close
    ]

    for tick in ticks:
        result = builder.on_tick(tick)
        assert result is None, "Should not close candle within same minute"

    # Finalize
    candle = builder.finalize_current()
    assert candle is not None

    # Check OHLC
    assert candle.open == 1.0500, f"Expected open=1.0500, got {candle.open}"
    assert candle.high == 1.0520, f"Expected high=1.0520, got {candle.high}"
    assert candle.low == 1.0480, f"Expected low=1.0480, got {candle.low}"
    assert candle.close == 1.0505, f"Expected close=1.0505, got {candle.close}"
    assert candle.volume == 100.0, f"Expected volume=100.0, got {candle.volume}"

    print("✓ Multiple ticks same minute test passed")


def test_minute_transition():
    """Test minute transition closes candle"""
    print("Testing minute transition...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    # First minute: 10:00
    minute1_start = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
    tick1 = Tick("XAUUSD", 2700.0, minute1_start + timedelta(seconds=30), 100.0)

    result = builder.on_tick(tick1)
    assert result is None, "First tick should not close candle"

    # Second minute: 10:01 (transition!)
    minute2_start = datetime(2026, 2, 8, 10, 1, 0, tzinfo=tz)
    tick2 = Tick("XAUUSD", 2701.0, minute2_start + timedelta(seconds=10), 150.0)

    result = builder.on_tick(tick2)
    assert result is not None, "Minute transition should close previous candle"

    # Check closed candle
    assert result.timestamp == minute1_start, "Should be first minute"
    assert result.open == 2700.0
    assert result.high == 2700.0
    assert result.low == 2700.0
    assert result.close == 2700.0
    assert result.volume == 100.0

    # Check builder is now on second minute
    assert builder.get_current_minute() == minute2_start
    assert builder.has_data is True

    # Finalize second candle
    candle2 = builder.finalize_current()
    assert candle2 is not None
    assert candle2.timestamp == minute2_start
    assert candle2.open == 2701.0

    print("✓ Minute transition test passed")


def test_ohlc_correctness():
    """Test OHLC calculation with various price sequences"""
    print("Testing OHLC correctness...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Price sequence: up, down, up, down
    prices = [2700.0, 2710.0, 2690.0, 2705.0, 2695.0]
    expected_high = 2710.0
    expected_low = 2690.0
    expected_open = 2700.0
    expected_close = 2695.0

    for i, price in enumerate(prices):
        tick = Tick("XAUUSD", price, base_time + timedelta(seconds=i*10), 10.0)
        builder.on_tick(tick)

    candle = builder.finalize_current()
    assert candle.open == expected_open, f"Open mismatch: {candle.open}"
    assert candle.high == expected_high, f"High mismatch: {candle.high}"
    assert candle.low == expected_low, f"Low mismatch: {candle.low}"
    assert candle.close == expected_close, f"Close mismatch: {candle.close}"

    print("✓ OHLC correctness test passed")


def test_timezone_handling():
    """Test timezone conversion"""
    print("Testing timezone handling...")

    # Builder with NY timezone
    tz_ny = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz_ny)

    # Tick with UTC timestamp
    tz_utc = ZoneInfo("UTC")
    utc_time = datetime(2026, 2, 8, 15, 0, 30, tzinfo=tz_utc)  # 15:00 UTC
    tick = Tick("XAUUSD", 2700.0, utc_time, 100.0)

    builder.on_tick(tick)

    # Current minute should be in NY timezone
    current_minute = builder.get_current_minute()
    assert current_minute.tzinfo == tz_ny, "Should convert to NY timezone"

    # 15:00 UTC = 10:00 NY (EST)
    expected_hour = 10
    assert current_minute.hour == expected_hour, f"Expected hour {expected_hour}, got {current_minute.hour}"

    print("✓ Timezone handling test passed")


def test_reset():
    """Test reset functionality"""
    print("Testing reset...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    # Add some ticks
    timestamp = datetime(2026, 2, 8, 10, 0, 30, tzinfo=tz)
    tick = Tick("XAUUSD", 2700.0, timestamp, 100.0)
    builder.on_tick(tick)

    assert builder.has_data is True
    assert builder.get_current_minute() is not None

    # Reset
    builder.reset()

    assert builder.has_data is False, "Should have no data after reset"
    assert builder.get_current_minute() is None, "Should have no current minute"

    # Can accept new ticks after reset
    tick2 = Tick("XAUUSD", 2701.0, timestamp + timedelta(seconds=10), 50.0)
    builder.on_tick(tick2)
    assert builder.has_data is True

    print("✓ Reset test passed")


def test_no_volume():
    """Test handling ticks without volume"""
    print("Testing no volume...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    timestamp = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Ticks without volume
    tick1 = Tick("XAUUSD", 2700.0, timestamp + timedelta(seconds=0), None)
    tick2 = Tick("XAUUSD", 2705.0, timestamp + timedelta(seconds=30), None)

    builder.on_tick(tick1)
    builder.on_tick(tick2)

    candle = builder.finalize_current()
    assert candle.volume == 0.0, "Volume should be 0 when ticks have no volume"

    print("✓ No volume test passed")


def test_empty_finalize():
    """Test finalizing with no data"""
    print("Testing empty finalize...")

    tz = ZoneInfo("America/New_York")
    builder = CandleBuilder(symbol="XAUUSD", tz=tz)

    # Finalize without any ticks
    candle = builder.finalize_current()
    assert candle is None, "Should return None when no data"

    print("✓ Empty finalize test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CandleBuilder Unit Tests")
    print("="*60 + "\n")

    try:
        test_single_tick()
        test_multiple_ticks_same_minute()
        test_minute_transition()
        test_ohlc_correctness()
        test_timezone_handling()
        test_reset()
        test_no_volume()
        test_empty_finalize()

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
