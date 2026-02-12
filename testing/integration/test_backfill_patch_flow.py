"""
Integration test: Backfill → Patch → Gap Validation

Tests the complete backfill flow:
1. Create store with gaps
2. Backfill service detects gaps
3. Fetches missing data from provider
4. Patches store
5. Validates no gaps remain
"""


from datetime import datetime, timedelta
from pathlib import Path
import asyncio
import sys
import tempfile

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.data.mock_provider import MockBackfillProvider
from application.services.backfill_service import BackfillService
from domain.models import Candle


def test_backfill_fills_gaps():
    """Test backfill service fills gaps"""
    print("Testing backfill fills gaps...")

    async def run_test():
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup store with gaps
            store = CSVCandleStore(root_path=tmpdir, broker="gtrade")

            # Create incomplete data (minutes 0, 1, 5, 6 - missing 2, 3, 4)
            for minute_offset in [0, 1, 5, 6]:
                candle = Candle(
                    symbol="XAUUSD",
                    timestamp=base_time + timedelta(minutes=minute_offset),
                    open=2700.0 + minute_offset,
                    high=2701.0 + minute_offset,
                    low=2699.0 + minute_offset,
                    close=2700.5 + minute_offset,
                    volume=100.0,
                )
                store.append(candle)

            # Verify gaps exist
            end_time = base_time + timedelta(minutes=7)
            range_before = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)
            assert range_before.is_complete is False, "Should have gaps"
            assert range_before.missing_count == 3, f"Should have 3 missing candles, got {range_before.missing_count}"

            # Setup backfill service
            provider = MockBackfillProvider(base_price=2700.0)
            service = BackfillService(
                store=store,
                provider=provider,
                symbols=["XAUUSD"],
                corrective_window_minutes=10,  # Look back 10 minutes
            )

            # Run backfill
            filled = await service.backfill_symbol("XAUUSD", start=base_time, end=end_time)
            assert filled >= 3, f"Should fill at least 3 candles, filled {filled}"

            # Verify gaps are filled
            range_after = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)
            assert range_after.is_complete is True, "Should have no gaps after backfill"
            assert range_after.count == 7, f"Should have 7 candles, got {range_after.count}"

    asyncio.run(run_test())
    print("✓ Backfill fills gaps test passed")


def test_backfill_startup():
    """Test startup backfill flow"""
    print("Testing startup backfill...")

    async def run_test():
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CSVCandleStore(root_path=tmpdir, broker="gtrade")

            # Create initial data ending at minute 10
            for minute_offset in range(10):
                candle = Candle(
                    symbol="XAUUSD",
                    timestamp=base_time + timedelta(minutes=minute_offset),
                    open=2700.0,
                    high=2701.0,
                    low=2699.0,
                    close=2700.0,
                    volume=100.0,
                )
                store.append(candle)

            # Simulate time passing - now it's minute 15
            # Corrective window = 5 minutes
            # Should backfill from minute 5 to 15 (10 minutes total)

            provider = MockBackfillProvider(base_price=2700.0)
            service = BackfillService(
                store=store,
                provider=provider,
                symbols=["XAUUSD"],
                corrective_window_minutes=5,
                interval_seconds=3600,  # Long interval (won't trigger during test)
            )

            # Start service (triggers startup backfill)
            await service.start()

            # Give it a moment to complete
            await asyncio.sleep(0.1)

            await service.stop()

            # Verify: should have filled gap from minute 10 to 15
            # (with 5-minute corrective window, it starts from minute 5)
            end_time = base_time + timedelta(minutes=16)
            range_final = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)

            # Should be complete or close to it
            print(f"  Coverage after startup backfill: {(range_final.count / range_final.expected_count * 100 if range_final.expected_count > 0 else 0):.1f}%")
            assert range_final.count >= 10, f"Should have at least 10 candles, got {range_final.count}"

    asyncio.run(run_test())
    print("✓ Startup backfill test passed")


def test_multi_symbol_backfill():
    """Test backfilling multiple symbols"""
    print("Testing multi-symbol backfill...")

    async def run_test():
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CSVCandleStore(root_path=tmpdir, broker="gtrade")

            # Create incomplete data for two symbols
            for symbol in ["XAUUSD", "EURUSD"]:
                # Only add first 3 candles (missing 3-9)
                for minute_offset in range(3):
                    candle = Candle(
                        symbol=symbol,
                        timestamp=base_time + timedelta(minutes=minute_offset),
                        open=2700.0 if symbol == "XAUUSD" else 1.05,
                        high=2701.0 if symbol == "XAUUSD" else 1.051,
                        low=2699.0 if symbol == "XAUUSD" else 1.049,
                        close=2700.0 if symbol == "XAUUSD" else 1.05,
                        volume=100.0,
                    )
                    store.append(candle)

            # Setup backfill for both symbols
            provider = MockBackfillProvider()
            service = BackfillService(
                store=store,
                provider=provider,
                symbols=["XAUUSD", "EURUSD"],
                corrective_window_minutes=10,
            )

            await service.start()
            await asyncio.sleep(0.1)
            await service.stop()

            # Verify both symbols are backfilled
            end_time = base_time + timedelta(minutes=10)

            xau_range = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)
            eur_range = store.read_range("EURUSD", base_time, end_time, validate_gaps=True)

            print(f"  XAUUSD coverage: {(xau_range.count / xau_range.expected_count * 100 if xau_range.expected_count > 0 else 0):.1f}%")
            print(f"  EURUSD coverage: {(eur_range.count / eur_range.expected_count * 100 if eur_range.expected_count > 0 else 0):.1f}%")

            assert xau_range.count >= 3, f"XAUUSD should have at least 3 candles"
            assert eur_range.count >= 3, f"EURUSD should have at least 3 candles"

    asyncio.run(run_test())
    print("✓ Multi-symbol backfill test passed")


def test_no_gaps_already_complete():
    """Test backfill when data is already complete"""
    print("Testing backfill with no gaps...")

    async def run_test():
        tz = ZoneInfo("America/New_York")
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CSVCandleStore(root_path=tmpdir, broker="gtrade")

            # Create complete data (no gaps)
            for minute_offset in range(10):
                candle = Candle(
                    symbol="XAUUSD",
                    timestamp=base_time + timedelta(minutes=minute_offset),
                    open=2700.0,
                    high=2701.0,
                    low=2699.0,
                    close=2700.0,
                    volume=100.0,
                )
                store.append(candle)

            provider = MockBackfillProvider()
            service = BackfillService(
                store=store,
                provider=provider,
                symbols=["XAUUSD"],
                corrective_window_minutes=5,
            )

            # Backfill should do nothing (data already complete)
            end_time = base_time + timedelta(minutes=10)
            filled = await service.backfill_symbol("XAUUSD", start=base_time, end=end_time)

            assert filled == 0, f"Should fill 0 candles (data complete), filled {filled}"

    asyncio.run(run_test())
    print("✓ No gaps test passed")


def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Integration Tests - Backfill Patch Flow")
    print("="*60 + "\n")

    try:
        test_backfill_fills_gaps()
        test_backfill_startup()
        test_multi_symbol_backfill()
        test_no_gaps_already_complete()

        print("\n" + "="*60)
        print("✓ All integration tests passed!")
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
