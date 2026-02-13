"""
Unit test for gTrade price feed parser

Tests message parsing logic without actual WebSocket connection.
"""


from pathlib import Path
import asyncio
import json
import sys


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.gtrade.config import GTRADE_PAIR_ID_TO_SYMBOL
from infrastructure.venues.gtrade.price_feed_ws_client import GTradePriceFeedWSClient


def test_parse_price_updates():
    """Test parsing of valid price updates (agnostic of mainnet vs testnet mapping)."""
    print("Testing parse price updates...")

    client = GTradePriceFeedWSClient()

    # pairId 0 and 2: use mapping from config (Sepolia: 0=BTCUSD, 2=LINKUSD; mainnet: 0=XAUUSD, 2=EURUSD)
    pair0, price0_expected = 0, 2700.50
    pair2, price2_expected = 2, 1.0500
    symbol0_expected = GTRADE_PAIR_ID_TO_SYMBOL.get(pair0)
    symbol2_expected = GTRADE_PAIR_ID_TO_SYMBOL.get(pair2)
    assert symbol0_expected and symbol2_expected, "pairId 0 and 2 must be in GTRADE_PAIR_ID_TO_SYMBOL"

    message = json.dumps([pair0, price0_expected, pair2, price2_expected])

    async def parse_and_check():
        await client._handle_message(message)

        ticks = []
        while not client._tick_queue.empty():
            tick = await client._tick_queue.get()
            ticks.append(tick)

        assert len(ticks) == 2, f"Expected 2 ticks, got {len(ticks)}"

        symbol0, price0, ts0 = ticks[0]
        assert symbol0 == symbol0_expected, f"Expected {symbol0_expected}, got {symbol0}"
        assert abs(price0 - price0_expected) < 0.01, f"Expected {price0_expected}, got {price0}"

        symbol1, price1, ts1 = ticks[1]
        assert symbol1 == symbol2_expected, f"Expected {symbol2_expected}, got {symbol1}"
        assert abs(price1 - price2_expected) < 0.0001, f"Expected {price2_expected}, got {price1}"

        print(f"  ✓ Parsed 2 ticks: {symbol0}={price0}, {symbol1}={price1}")

    asyncio.run(parse_and_check())
    print("✓ Parse price updates test passed")


def test_parse_ping_message():
    """Test parsing of ping message (single timestamp)"""
    print("Testing parse ping message...")

    client = GTradePriceFeedWSClient()

    # Ping message: [timestamp_ms]
    message = json.dumps([1234567890000])

    async def parse_and_check():
        await client._handle_message(message)

        # Check no ticks were queued (ping is ignored)
        assert client._tick_queue.empty(), "Ping should not queue ticks"

        print(f"  ✓ Ping message handled (no ticks queued)")

    asyncio.run(parse_and_check())
    print("✓ Parse ping message test passed")


def test_parse_invalid_odd_length():
    """Test handling of invalid message (odd length array)"""
    print("Testing parse invalid odd length...")

    client = GTradePriceFeedWSClient()

    # Invalid: odd length array
    message = json.dumps([0, 2700.50, 2])  # Missing last price

    async def parse_and_check():
        await client._handle_message(message)

        # Check no ticks were queued (invalid message)
        assert client._tick_queue.empty(), "Invalid message should not queue ticks"

        print(f"  ✓ Invalid odd length handled (no ticks queued)")

    asyncio.run(parse_and_check())
    print("✓ Parse invalid odd length test passed")


def test_parse_unknown_pair_id():
    """Test handling of unknown pairId (not in mapping)"""
    print("Testing parse unknown pairId...")

    client = GTradePriceFeedWSClient()

    # Unknown pairId: 999
    message = json.dumps([999, 1234.56])

    async def parse_and_check():
        await client._handle_message(message)

        # Check no ticks were queued (unknown pairId)
        assert client._tick_queue.empty(), "Unknown pairId should not queue ticks"

        print(f"  ✓ Unknown pairId handled (no ticks queued)")

    asyncio.run(parse_and_check())
    print("✓ Parse unknown pairId test passed")


def test_parse_invalid_price_type():
    """Test handling of invalid price type (non-numeric)"""
    print("Testing parse invalid price type...")

    client = GTradePriceFeedWSClient()

    # Invalid: price is string
    message = json.dumps([0, "invalid_price"])

    async def parse_and_check():
        await client._handle_message(message)

        # Check no ticks were queued (invalid price)
        assert client._tick_queue.empty(), "Invalid price should not queue ticks"

        print(f"  ✓ Invalid price type handled (no ticks queued)")

    asyncio.run(parse_and_check())
    print("✓ Parse invalid price type test passed")


def test_parse_malformed_json():
    """Test handling of malformed JSON"""
    print("Testing parse malformed JSON...")

    client = GTradePriceFeedWSClient()

    # Malformed JSON
    message = "{invalid json"

    async def parse_and_check():
        await client._handle_message(message)

        # Check no ticks were queued (malformed JSON)
        assert client._tick_queue.empty(), "Malformed JSON should not queue ticks"

        print(f"  ✓ Malformed JSON handled (no ticks queued)")

    asyncio.run(parse_and_check())
    print("✓ Parse malformed JSON test passed")


def test_latest_price_cache():
    """Test latest price cache update (uses mapping from config)."""
    print("Testing latest price cache...")

    client = GTradePriceFeedWSClient()

    symbol0 = GTRADE_PAIR_ID_TO_SYMBOL.get(0)
    symbol2 = GTRADE_PAIR_ID_TO_SYMBOL.get(2)
    assert symbol0 and symbol2, "pairId 0 and 2 must be in GTRADE_PAIR_ID_TO_SYMBOL"
    price0_expected, price2_expected = 2700.00, 1.0500
    message = json.dumps([0, price0_expected, 2, price2_expected])

    async def parse_and_check():
        await client._handle_message(message)

        price_a = await client.get_latest_price(symbol0)
        price_b = await client.get_latest_price(symbol2)

        assert price_a is not None, f"{symbol0} price should be cached"
        assert abs(price_a - price0_expected) < 0.01, f"Expected {price0_expected}, got {price_a}"

        assert price_b is not None, f"{symbol2} price should be cached"
        assert abs(price_b - price2_expected) < 0.0001, f"Expected {price2_expected}, got {price_b}"

        print(f"  ✓ Cache updated: {symbol0}={price_a}, {symbol2}={price_b}")

    asyncio.run(parse_and_check())
    print("✓ Latest price cache test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("GTrade Price Feed Parser Unit Tests")
    print("="*60 + "\n")

    try:
        test_parse_price_updates()
        test_parse_ping_message()
        test_parse_invalid_odd_length()
        test_parse_unknown_pair_id()
        test_parse_invalid_price_type()
        test_parse_malformed_json()
        test_latest_price_cache()

        print("\n" + "="*60)
        print("✓ All GTrade price feed parser tests passed!")
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
