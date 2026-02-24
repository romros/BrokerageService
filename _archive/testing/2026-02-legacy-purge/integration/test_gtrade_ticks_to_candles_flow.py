"""
Integration test: gTrade ticks → candles → store

Tests the complete flow without actual network connection:
1. Fake tick generator
2. LiveMarketDataService processes ticks
3. CandleBuilder generates candles
4. CSVCandleStore persists candles
5. Gap validation passes (no gaps, no duplicates)

Multi-symbol test (XAUUSD + EURUSD)
"""


from datetime import datetime, timezone
from pathlib import Path
import asyncio
import sys
import tempfile

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.storage.gap_validator import GapValidator
from application.services.live_marketdata_service import LiveMarketDataService


class FakeGTradePriceFeedClient:
    """Fake price feed client for testing"""

    def __init__(self, ticks: list):
        """
        Initialize with pre-generated ticks

        Args:
            ticks: List of (symbol, price, timestamp_ms) tuples
        """
        self.ticks = ticks
        self._tick_index = 0
        self._latest_price = {}

    async def get_ticks(self):
        """Get next tick (simulated)"""
        if self._tick_index >= len(self.ticks):
            # No more ticks, block forever
            await asyncio.sleep(999999)

        tick = self.ticks[self._tick_index]
        self._tick_index += 1

        # Update cache
        symbol, price, _ = tick
        self._latest_price[symbol] = price

        return tick

    async def get_latest_price(self, symbol: str):
        """Get latest price"""
        return self._latest_price.get(symbol)

    async def start(self):
        """Start client (no-op for fake)"""
        pass

    async def stop(self):
        """Stop client (no-op for fake)"""
        pass


def generate_test_ticks():
    """
    Generate test ticks for 2 minutes (XAUUSD + EURUSD)

    Ticks at t=0s, t=30s, t=60s, t=90s, t=120s for each symbol
    """
    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
    base_epoch_ms = int(base_time.timestamp() * 1000)

    ticks = []

    # Minute 1: t=0s, t=30s
    ticks.append(("XAUUSD", 2700.00, base_epoch_ms + 0))
    ticks.append(("EURUSD", 1.0500, base_epoch_ms + 0))
    ticks.append(("XAUUSD", 2701.00, base_epoch_ms + 30000))
    ticks.append(("EURUSD", 1.0505, base_epoch_ms + 30000))

    # Minute 2: t=60s, t=90s
    ticks.append(("XAUUSD", 2702.00, base_epoch_ms + 60000))
    ticks.append(("EURUSD", 1.0510, base_epoch_ms + 60000))
    ticks.append(("XAUUSD", 2703.00, base_epoch_ms + 90000))
    ticks.append(("EURUSD", 1.0515, base_epoch_ms + 90000))

    # Minute 3 start: t=120s (closes minute 2)
    ticks.append(("XAUUSD", 2704.00, base_epoch_ms + 120000))
    ticks.append(("EURUSD", 1.0520, base_epoch_ms + 120000))

    return ticks


async def test_ticks_to_candles_flow():
    """Test complete flow: ticks → candles → store"""
    print("Testing ticks → candles → store flow...")

    # Setup temp storage
    tmpdir = tempfile.mkdtemp()
    store = CSVCandleStore(root_path=tmpdir, broker="gtrade", canonical_tz="America/New_York")

    # Generate test ticks
    ticks = generate_test_ticks()
    print(f"  Generated {len(ticks)} test ticks")

    # Create fake client
    fake_client = FakeGTradePriceFeedClient(ticks)

    # Create service
    service = LiveMarketDataService(
        price_feed_client=fake_client,
        candle_store=store,
        symbols=["XAUUSD", "EURUSD"],
        tz=ZoneInfo("America/New_York"),
        ticker_broadcast_ms=0,  # No throttle for testing
    )

    # Start service
    await service.start()

    # Wait for all ticks to be processed
    # (service will block on get_ticks() after consuming all)
    await asyncio.sleep(0.5)

    # Stop service
    await service.stop()

    print("  ✓ Service processed all ticks")

    # Check storage: should have 2 candles for each symbol (minute 1 and minute 2)
    tz = ZoneInfo("America/New_York")
    start_ts = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
    end_ts = datetime(2026, 2, 8, 10, 3, 0, tzinfo=tz)

    # XAUUSD
    candles_xau = store.read_range("XAUUSD", start_ts, end_ts).candles
    assert len(candles_xau) == 2, f"Expected 2 XAUUSD candles, got {len(candles_xau)}"
    print(f"  ✓ XAUUSD: 2 candles stored")

    # Check XAUUSD candle 1 (minute 1)
    c1 = candles_xau[0]
    assert c1.open == 2700.00
    assert c1.high == 2701.00
    assert c1.low == 2700.00
    assert c1.close == 2701.00
    print(f"    - Candle 1: O={c1.open} H={c1.high} L={c1.low} C={c1.close}")

    # Check XAUUSD candle 2 (minute 2)
    c2 = candles_xau[1]
    assert c2.open == 2702.00
    assert c2.high == 2703.00
    assert c2.low == 2702.00
    assert c2.close == 2703.00
    print(f"    - Candle 2: O={c2.open} H={c2.high} L={c2.low} C={c2.close}")

    # EURUSD
    candles_eur = store.read_range("EURUSD", start_ts, end_ts).candles
    assert len(candles_eur) == 2, f"Expected 2 EURUSD candles, got {len(candles_eur)}"
    print(f"  ✓ EURUSD: 2 candles stored")

    # Check EURUSD candle 1 (minute 1)
    c1 = candles_eur[0]
    assert abs(c1.open - 1.0500) < 0.0001
    assert abs(c1.high - 1.0505) < 0.0001
    assert abs(c1.low - 1.0500) < 0.0001
    assert abs(c1.close - 1.0505) < 0.0001
    print(f"    - Candle 1: O={c1.open:.4f} H={c1.high:.4f} L={c1.low:.4f} C={c1.close:.4f}")

    # Check EURUSD candle 2 (minute 2)
    c2 = candles_eur[1]
    assert abs(c2.open - 1.0510) < 0.0001
    assert abs(c2.high - 1.0515) < 0.0001
    assert abs(c2.low - 1.0510) < 0.0001
    assert abs(c2.close - 1.0515) < 0.0001
    print(f"    - Candle 2: O={c2.open:.4f} H={c2.high:.4f} L={c2.low:.4f} C={c2.close:.4f}")

    print("✓ Ticks → candles → store test passed")


async def test_gap_validation():
    """Test that stored candles have no gaps"""
    print("Testing gap validation...")

    # Setup temp storage
    tmpdir = tempfile.mkdtemp()
    store = CSVCandleStore(root_path=tmpdir, broker="gtrade", canonical_tz="America/New_York")

    # Generate test ticks
    ticks = generate_test_ticks()

    # Create fake client
    fake_client = FakeGTradePriceFeedClient(ticks)

    # Create service
    service = LiveMarketDataService(
        price_feed_client=fake_client,
        candle_store=store,
        symbols=["XAUUSD", "EURUSD"],
        tz=ZoneInfo("America/New_York"),
    )

    # Start and process
    await service.start()
    await asyncio.sleep(0.5)
    await service.stop()

    # Validate gaps
    tz = ZoneInfo("America/New_York")
    start_ts = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
    end_ts = datetime(2026, 2, 8, 10, 2, 0, tzinfo=tz)  # Only 2 candles: 10:00 and 10:01

    # XAUUSD
    candles_xau = store.read_range("XAUUSD", start_ts, end_ts).candles
    gaps_xau = GapValidator.find_gaps(candles_xau, start_ts, end_ts)
    assert len(gaps_xau) == 0, f"Expected no gaps for XAUUSD, got {len(gaps_xau)}"
    print(f"  ✓ XAUUSD: no gaps")

    # EURUSD
    candles_eur = store.read_range("EURUSD", start_ts, end_ts).candles
    gaps_eur = GapValidator.find_gaps(candles_eur, start_ts, end_ts)
    assert len(gaps_eur) == 0, f"Expected no gaps for EURUSD, got {len(gaps_eur)}"
    print(f"  ✓ EURUSD: no gaps")

    # Check integrity (sorted, no duplicates)
    assert GapValidator.check_integrity(candles_xau), "XAUUSD integrity check failed"
    assert GapValidator.check_integrity(candles_eur), "EURUSD integrity check failed"
    print(f"  ✓ Integrity check passed (sorted, no duplicates)")

    print("✓ Gap validation test passed")


def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Integration Tests - gTrade Ticks → Candles → Store")
    print("="*60 + "\n")

    try:
        asyncio.run(test_ticks_to_candles_flow())
        asyncio.run(test_gap_validation())

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
