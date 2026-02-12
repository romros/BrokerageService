"""
Unit test for MockBackfillProvider

Tests:
- Generate synthetic candles
- OHLC validity
- Range handling
- Availability check
"""


from datetime import datetime, timedelta
from pathlib import Path
import asyncio
import sys

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.data.mock_provider import MockBackfillProvider


def test_generate_candles():
    """Test generating synthetic candles"""
    print("Testing generate candles...")

    async def run_test():
        provider = MockBackfillProvider(base_price=2700.0, volatility=0.001)

        tz = ZoneInfo("America/New_York")
        start = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
        end = datetime(2026, 2, 8, 10, 10, 0, tzinfo=tz)  # 10 minutes

        candles = await provider.fetch_ohlcv("XAUUSD", start, end)

        assert len(candles) == 10, f"Expected 10 candles, got {len(candles)}"

        # Check all candles are closed
        for candle in candles:
            assert candle.is_closed is True, "Candle should be closed"
            assert candle.symbol == "XAUUSD"

        # Check timestamps are sequential
        for i in range(1, len(candles)):
            delta = (candles[i].timestamp - candles[i-1].timestamp).total_seconds()
            assert delta == 60, f"Expected 60s between candles, got {delta}s"

    asyncio.run(run_test())
    print("✓ Generate candles test passed")


def test_ohlc_validity():
    """Test OHLC values are valid"""
    print("Testing OHLC validity...")

    async def run_test():
        provider = MockBackfillProvider(base_price=2700.0, volatility=0.002)

        tz = ZoneInfo("America/New_York")
        start = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
        end = datetime(2026, 2, 8, 10, 5, 0, tzinfo=tz)

        candles = await provider.fetch_ohlcv("EURUSD", start, end)

        for candle in candles:
            # OHLC constraints
            assert candle.high >= candle.open, f"High < Open: {candle}"
            assert candle.high >= candle.close, f"High < Close: {candle}"
            assert candle.low <= candle.open, f"Low > Open: {candle}"
            assert candle.low <= candle.close, f"Low > Close: {candle}"
            assert candle.high >= candle.low, f"High < Low: {candle}"

            # Volume should be positive
            assert candle.volume > 0, f"Volume should be positive: {candle.volume}"

    asyncio.run(run_test())
    print("✓ OHLC validity test passed")


def test_price_behavior():
    """Test price behavior (trend, volatility)"""
    print("Testing price behavior...")

    async def run_test():
        # Test trending (deterministic with seed)
        provider_up = MockBackfillProvider(base_price=2700.0, trend=0.0001, seed=42)  # +0.01% per minute

        tz = ZoneInfo("America/New_York")
        start = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
        end = datetime(2026, 2, 8, 10, 30, 0, tzinfo=tz)  # 30 minutes

        candles = await provider_up.fetch_ohlcv("XAUUSD", start, end)

        # Prices should generally trend up
        first_avg = (candles[0].open + candles[0].close) / 2
        last_avg = (candles[-1].open + candles[-1].close) / 2

        assert last_avg > first_avg, f"Expected upward trend: {first_avg} -> {last_avg}"

    asyncio.run(run_test())
    print("✓ Price behavior test passed")


def test_is_available():
    """Test availability check"""
    print("Testing is_available...")

    async def run_test():
        provider = MockBackfillProvider()

        is_available = await provider.is_available()
        assert is_available is True, "Mock provider should always be available"

        # Check properties
        assert provider.provider_name == "mock"
        assert provider.max_range_minutes > 0

    asyncio.run(run_test())
    print("✓ is_available test passed")


def test_large_range():
    """Test handling large time ranges"""
    print("Testing large range...")

    async def run_test():
        provider = MockBackfillProvider(base_price=2700.0)

        tz = ZoneInfo("America/New_York")
        start = datetime(2026, 2, 1, 0, 0, 0, tzinfo=tz)
        end = datetime(2026, 2, 2, 0, 0, 0, tzinfo=tz)  # 1 day = 1440 minutes

        candles = await provider.fetch_ohlcv("XAUUSD", start, end)

        assert len(candles) == 1440, f"Expected 1440 candles (1 day), got {len(candles)}"

    asyncio.run(run_test())
    print("✓ Large range test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("MockBackfillProvider Unit Tests")
    print("="*60 + "\n")

    try:
        test_generate_candles()
        test_ohlc_validity()
        test_price_behavior()
        test_is_available()
        test_large_range()

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
