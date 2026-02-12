"""
Integration test: Live Tick → CandleBuilder → Store → OHLCV

Tests the complete flow:
1. Simulate live ticks arriving
2. CandleBuilder accumulates and finalizes candles
3. Candles written to CSVCandleStore
4. Read back via store.read_range()
5. Validate no gaps and correct OHLC
"""


from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Tick
from infrastructure.builders.candle_builder import CandleBuilder
from infrastructure.storage.csv_store import CSVCandleStore


def test_tick_to_store_flow():
    """Test complete flow: tick → builder → store"""
    print("Testing tick → builder → store flow...")

    tz = ZoneInfo("America/New_York")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup
        store = CSVCandleStore(root_path=tmpdir, broker="gtrade", canonical_tz="America/New_York")
        builder = CandleBuilder(symbol="XAUUSD", tz=tz)

        # Simulate 3 minutes of ticks (10 ticks per minute)
        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
        closed_candles = []

        for minute_offset in range(3):
            minute_start = base_time + timedelta(minutes=minute_offset)

            for second in range(0, 60, 6):  # 10 ticks per minute
                timestamp = minute_start + timedelta(seconds=second)
                price = 2700.0 + minute_offset * 0.5 + (second / 60) * 0.3  # Gradual increase

                tick = Tick(
                    symbol="XAUUSD",
                    price=price,
                    timestamp=timestamp,
                    volume=10.0
                )

                closed_candle = builder.on_tick(tick)
                if closed_candle:
                    closed_candles.append(closed_candle)
                    store.append(closed_candle)
                    print(f"  ✓ Candle closed and stored: {closed_candle.timestamp}")

        # Finalize last candle
        last_candle = builder.finalize_current()
        if last_candle:
            closed_candles.append(last_candle)
            store.append(last_candle)
            print(f"  ✓ Final candle stored: {last_candle.timestamp}")

        # Validate: should have 3 candles
        assert len(closed_candles) == 3, f"Expected 3 candles, got {len(closed_candles)}"

        # Read back from store
        end_time = base_time + timedelta(minutes=3)
        candle_range = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)

        assert candle_range.count == 3, f"Expected 3 candles from store, got {candle_range.count}"
        assert candle_range.is_complete is True, "Range should be complete (no gaps)"

        # Validate OHLC values match
        for i, original_candle in enumerate(closed_candles):
            stored_candle = candle_range.candles[i]

            assert stored_candle.timestamp == original_candle.timestamp
            assert abs(stored_candle.open - original_candle.open) < 0.0001
            assert abs(stored_candle.high - original_candle.high) < 0.0001
            assert abs(stored_candle.low - original_candle.low) < 0.0001
            assert abs(stored_candle.close - original_candle.close) < 0.0001
            assert abs(stored_candle.volume - original_candle.volume) < 0.0001

    print("✓ Tick → builder → store flow test passed")


def test_multi_symbol_flow():
    """Test handling multiple symbols simultaneously"""
    print("Testing multi-symbol flow...")

    tz = ZoneInfo("America/New_York")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="gtrade")

        # Create builders for 2 symbols
        builder_xau = CandleBuilder(symbol="XAUUSD", tz=tz)
        builder_eur = CandleBuilder(symbol="EURUSD", tz=tz)

        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        # Send ticks for both symbols (2 minutes)
        for minute_offset in range(2):
            minute_start = base_time + timedelta(minutes=minute_offset)

            # XAUUSD ticks
            for second in range(0, 60, 10):
                timestamp = minute_start + timedelta(seconds=second)
                tick = Tick("XAUUSD", 2700.0 + minute_offset, timestamp, 100.0)

                closed = builder_xau.on_tick(tick)
                if closed:
                    store.append(closed)

            # EURUSD ticks
            for second in range(0, 60, 10):
                timestamp = minute_start + timedelta(seconds=second)
                tick = Tick("EURUSD", 1.05 + minute_offset * 0.001, timestamp, 50.0)

                closed = builder_eur.on_tick(tick)
                if closed:
                    store.append(closed)

        # Finalize both
        for builder in [builder_xau, builder_eur]:
            last = builder.finalize_current()
            if last:
                store.append(last)

        # Read back both symbols
        end_time = base_time + timedelta(minutes=2)

        xau_range = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)
        eur_range = store.read_range("EURUSD", base_time, end_time, validate_gaps=True)

        assert xau_range.count == 2, f"Expected 2 XAUUSD candles, got {xau_range.count}"
        assert eur_range.count == 2, f"Expected 2 EURUSD candles, got {eur_range.count}"

        assert xau_range.is_complete is True
        assert eur_range.is_complete is True

    print("✓ Multi-symbol flow test passed")


def test_irregular_ticks():
    """Test handling irregular tick arrival (gaps, bursts)"""
    print("Testing irregular ticks...")

    tz = ZoneInfo("America/New_York")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(root_path=tmpdir, broker="gtrade")
        builder = CandleBuilder(symbol="XAUUSD", tz=tz)

        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        # Minute 0: 3 ticks (sparse)
        for second in [5, 30, 55]:
            tick = Tick("XAUUSD", 2700.0 + second/100, base_time + timedelta(seconds=second), 10.0)
            closed = builder.on_tick(tick)
            if closed:
                store.append(closed)

        # Minute 1: No ticks (gap)

        # Minute 2: 20 ticks (burst)
        minute2 = base_time + timedelta(minutes=2)
        for second in range(0, 60, 3):
            tick = Tick("XAUUSD", 2701.0 + second/100, minute2 + timedelta(seconds=second), 5.0)
            closed = builder.on_tick(tick)
            if closed:
                store.append(closed)

        # Finalize
        last = builder.finalize_current()
        if last:
            store.append(last)

        # Read back
        end_time = base_time + timedelta(minutes=3)
        candle_range = store.read_range("XAUUSD", base_time, end_time, validate_gaps=True)

        # Should have 2 candles (minute 0 and minute 2)
        assert candle_range.count == 2, f"Expected 2 candles, got {candle_range.count}"

        # Gap detection: minute 1 is missing
        assert candle_range.is_complete is False, "Should detect gap (minute 1 missing)"
        assert candle_range.missing_count == 1, f"Expected 1 missing candle, got {candle_range.missing_count}"

    print("✓ Irregular ticks test passed")


def test_persistent_storage():
    """Test that candles persist across store instances"""
    print("Testing persistent storage...")

    tz = ZoneInfo("America/New_York")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Phase 1: Write candles
        store1 = CSVCandleStore(root_path=tmpdir, broker="gtrade")
        builder = CandleBuilder(symbol="XAUUSD", tz=tz)

        base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

        # Generate and store 2 candles
        for minute_offset in range(2):
            minute_start = base_time + timedelta(minutes=minute_offset)

            for second in range(0, 60, 10):
                timestamp = minute_start + timedelta(seconds=second)
                tick = Tick("XAUUSD", 2700.0 + minute_offset, timestamp, 100.0)

                closed = builder.on_tick(tick)
                if closed:
                    store1.append(closed)

        last = builder.finalize_current()
        if last:
            store1.append(last)

        # Phase 2: Create new store instance, read back
        store2 = CSVCandleStore(root_path=tmpdir, broker="gtrade")

        end_time = base_time + timedelta(minutes=2)
        candle_range = store2.read_range("XAUUSD", base_time, end_time, validate_gaps=True)

        assert candle_range.count == 2, f"Expected 2 persisted candles, got {candle_range.count}"
        assert candle_range.is_complete is True

    print("✓ Persistent storage test passed")


def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Integration Tests - Live to Store Flow")
    print("="*60 + "\n")

    try:
        test_tick_to_store_flow()
        test_multi_symbol_flow()
        test_irregular_ticks()
        test_persistent_storage()

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
