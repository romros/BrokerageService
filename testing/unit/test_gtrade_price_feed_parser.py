"""
Unit test for gTrade price feed parser

Tests message parsing logic without actual WebSocket connection.
"""


from pathlib import Path
import asyncio
import json
import sys


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.gtrade.price_feed_ws_client import GTradePriceFeedWSClient


def test_parse_price_updates():
    """Test parsing of valid price updates"""
    print("Testing parse price updates...")

    client = GTradePriceFeedWSClient()

    # Mock message: [pairId0, price0, pairId2, price2]
    message = json.dumps([0, 2700.50, 2, 1.0500])

    # Parse (direct call to private method for testing)
    async def parse_and_check():
        await client._handle_message(message)

        # Check ticks were queued
        ticks = []
        while not client._tick_queue.empty():
            tick = await client._tick_queue.get()
            ticks.append(tick)

        assert len(ticks) == 2, f"Expected 2 ticks, got {len(ticks)}"

        # Check XAUUSD (pairId 0)
        symbol0, price0, ts0 = ticks[0]
        assert symbol0 == "XAUUSD", f"Expected XAUUSD, got {symbol0}"
        assert abs(price0 - 2700.50) < 0.01, f"Expected 2700.50, got {price0}"

        # Check EURUSD (pairId 2)
        symbol1, price1, ts1 = ticks[1]
        assert symbol1 == "EURUSD", f"Expected EURUSD, got {symbol1}"
        assert abs(price1 - 1.0500) < 0.0001, f"Expected 1.0500, got {price1}"

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
    """Test latest price cache update"""
    print("Testing latest price cache...")

    client = GTradePriceFeedWSClient()

    # Send price update
    message = json.dumps([0, 2700.00, 2, 1.0500])

    async def parse_and_check():
        await client._handle_message(message)

        # Check cache was updated
        price_xau = await client.get_latest_price("XAUUSD")
        price_eur = await client.get_latest_price("EURUSD")

        assert price_xau is not None, "XAUUSD price should be cached"
        assert abs(price_xau - 2700.00) < 0.01, f"Expected 2700.00, got {price_xau}"

        assert price_eur is not None, "EURUSD price should be cached"
        assert abs(price_eur - 1.0500) < 0.0001, f"Expected 1.0500, got {price_eur}"

        print(f"  ✓ Cache updated: XAUUSD={price_xau}, EURUSD={price_eur}")

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
