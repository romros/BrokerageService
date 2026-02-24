"""
Integration test: Lighter ticks → candles → store (Milestone M1)

Deterministic flow without network:
1. Fake tick feed (list of (symbol, price, timestamp_ms))
2. LiveMarketDataService processes ticks
3. CandleBuilder generates 1m candles
4. CSVCandleStore persists
5. No gaps, no duplicate closes, monotonic timestamps

Validates M1 pipeline: Lighter market data → candles 1m → CSV → WS-ready.
"""

import asyncio
import traceback
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.services.live_marketdata_service import LiveMarketDataService
from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.storage.gap_validator import GapValidator


class FakeLighterPriceFeedClient:
    """Fake price feed for deterministic tests (no network)."""

    def __init__(self, ticks: list):
        """
        Args:
            ticks: List of (symbol, price, timestamp_ms) tuples
        """
        self.ticks = ticks
        self._index = 0

    async def get_ticks(self):
        if self._index >= len(self.ticks):
            await asyncio.sleep(999999)
        tick = self.ticks[self._index]
        self._index += 1
        return tick

    async def start(self):
        pass

    async def stop(self):
        pass


def generate_lighter_ticks():
    """
    Generate deterministic ticks for 2 minutes (ETH + BTC).
    TZ America/New_York; timestamps contiguous.
    """
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    base_ms = int(base.timestamp() * 1000)

    ticks = []
    # Minute 1: 14:00–14:01
    ticks.append(("ETH", 3500.0, base_ms + 0))
    ticks.append(("BTC", 98000.0, base_ms + 0))
    ticks.append(("ETH", 3501.0, base_ms + 30000))
    ticks.append(("BTC", 98050.0, base_ms + 30000))
    # Minute 2: 14:01–14:02
    ticks.append(("ETH", 3502.0, base_ms + 60000))
    ticks.append(("BTC", 98100.0, base_ms + 60000))
    ticks.append(("ETH", 3503.0, base_ms + 90000))
    ticks.append(("BTC", 98150.0, base_ms + 90000))
    # Minute 3 start (closes minute 2)
    ticks.append(("ETH", 3504.0, base_ms + 120000))
    ticks.append(("BTC", 98200.0, base_ms + 120000))
    return ticks


async def test_lighter_ticks_to_candles_flow():
    """Ticks → candles → store; 2 candles per symbol, OHLC correct."""
    print("Testing Lighter ticks → candles → store flow...")

    tmpdir = tempfile.mkdtemp()
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="lighter",
        canonical_tz="America/New_York",
    )

    ticks = generate_lighter_ticks()
    fake = FakeLighterPriceFeedClient(ticks)

    service = LiveMarketDataService(
        price_feed_client=fake,
        candle_store=store,
        symbols=["ETH", "BTC"],
        tz=ZoneInfo("America/New_York"),
        ticker_broadcast_ms=0,
    )

    await service.start()
    await asyncio.sleep(0.5)
    await service.stop()

    print("  ✓ Service processed all ticks")

    tz = ZoneInfo("America/New_York")
    start_ts = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    end_ts = datetime(2026, 2, 10, 14, 3, 0, tzinfo=tz)

    candles_eth = store.read_range("ETH", start_ts, end_ts).candles
    assert len(candles_eth) == 2, f"Expected 2 ETH candles, got {len(candles_eth)}"
    c1, c2 = candles_eth[0], candles_eth[1]
    assert c1.open == 3500.0 and c1.high == 3501.0 and c1.low == 3500.0 and c1.close == 3501.0
    assert c2.open == 3502.0 and c2.high == 3503.0 and c2.low == 3502.0 and c2.close == 3503.0
    print("  ✓ ETH: 2 candles stored, OHLC correct")

    candles_btc = store.read_range("BTC", start_ts, end_ts).candles
    assert len(candles_btc) == 2
    c1, c2 = candles_btc[0], candles_btc[1]
    assert c1.open == 98000.0 and c1.close == 98050.0
    assert c2.open == 98100.0 and c2.close == 98150.0
    print("  ✓ BTC: 2 candles stored, OHLC correct")

    print("✓ Lighter ticks → candles → store test passed")


async def test_no_duplicate_candle_closes():
    """No duplicate close per minute (single finalize per minute)."""
    print("Testing no duplicate candle closes...")

    tmpdir = tempfile.mkdtemp()
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="lighter",
        canonical_tz="America/New_York",
    )

    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 15, 0, 0, tzinfo=tz)
    base_ms = int(base.timestamp() * 1000)

    # One symbol, 3 ticks in same minute, then 1 tick in next minute (closes first)
    ticks = [
        ("ETH", 3600.0, base_ms + 0),
        ("ETH", 3601.0, base_ms + 20000),
        ("ETH", 3602.0, base_ms + 40000),
        ("ETH", 3603.0, base_ms + 60000),  # closes minute 1, opens minute 2
    ]
    fake = FakeLighterPriceFeedClient(ticks)
    service = LiveMarketDataService(
        price_feed_client=fake,
        candle_store=store,
        symbols=["ETH"],
        tz=ZoneInfo("America/New_York"),
    )
    await service.start()
    await asyncio.sleep(0.3)
    await service.stop()

    start_ts = datetime(2026, 2, 10, 15, 0, 0, tzinfo=tz)
    end_ts = datetime(2026, 2, 10, 15, 2, 0, tzinfo=tz)
    candles = store.read_range("ETH", start_ts, end_ts).candles
    assert len(candles) == 1, f"Expected 1 candle (one minute closed), got {len(candles)}"
    assert candles[0].close == 3602.0
    print("  ✓ Single close per minute, no duplicates")
    print("✓ No duplicate candle closes test passed")


async def test_gap_validation_after_flow():
    """Stored candles pass gap validation (contiguous, sorted)."""
    print("Testing gap validation after flow...")

    tmpdir = tempfile.mkdtemp()
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="lighter",
        canonical_tz="America/New_York",
    )
    ticks = generate_lighter_ticks()
    fake = FakeLighterPriceFeedClient(ticks)
    service = LiveMarketDataService(
        price_feed_client=fake,
        candle_store=store,
        symbols=["ETH", "BTC"],
        tz=ZoneInfo("America/New_York"),
    )
    await service.start()
    await asyncio.sleep(0.5)
    await service.stop()

    tz = ZoneInfo("America/New_York")
    start_ts = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    end_ts = datetime(2026, 2, 10, 14, 2, 0, tzinfo=tz)

    for symbol in ["ETH", "BTC"]:
        candles = store.read_range(symbol, start_ts, end_ts).candles
        gaps = GapValidator.find_gaps(candles, start_ts, end_ts)
        assert len(gaps) == 0, f"Expected no gaps for {symbol}, got {gaps}"
        valid, msg = GapValidator.check_integrity(candles)
        assert valid, f"Integrity check failed for {symbol}: {msg}"
    print("  ✓ No gaps, integrity OK")
    print("✓ Gap validation test passed")


def main():
    print("\n" + "=" * 60)
    print("Integration Tests - Lighter Ticks → Candles → Store (M1)")
    print("=" * 60 + "\n")

    try:
        asyncio.run(test_lighter_ticks_to_candles_flow())
        asyncio.run(test_no_duplicate_candle_closes())
        asyncio.run(test_gap_validation_after_flow())

        print("\n" + "=" * 60)
        print("✓ All Lighter ticks→candles flow tests passed!")
        print("=" * 60 + "\n")
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
