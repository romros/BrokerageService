"""
Integration test: LighterVenueAdapter Market Data (TASK 3)

Tests get_pairs() and get_latest_price() with mocked market data client:
- get_pairs() returns TradingPair list
- get_latest_price() returns PriceData with bid/ask/mid
- MarketNotFoundError for unknown symbols
- NoLiquidityError for empty orderbook

Uses mocked ILighterMarketDataClient (NO network calls).
"""


import asyncio
import traceback
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from typing import List

from infrastructure.venues.lighter.config import LighterConfig
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.market_data_client import ILighterMarketDataClient
from domain.errors import MarketNotFoundError, NoLiquidityError
from domain.models import TradingPair, PriceData


# ============================================================================
# Mock OrderBook and OrderBookOrders objects
# ============================================================================

def create_mock_order_book(market_id: int, symbol: str, status: str = "active"):
    """Create mock OrderBook object"""
    mock = MagicMock()
    mock.market_id = market_id
    mock.symbol = symbol
    mock.status = status
    mock.maker_fee = 0.0
    mock.taker_fee = 0.0
    mock.min_base_amount = 0.01
    mock.min_quote_amount = 10.0
    mock.supported_size_decimals = 2
    mock.supported_price_decimals = 4
    mock.supported_quote_decimals = 6
    return mock


def create_mock_simple_order(price: str, size: str = "1.0"):
    """Create mock SimpleOrder object"""
    mock = MagicMock()
    mock.price = price
    mock.remaining_base_amount = size
    mock.order_id = "12345"
    mock.order_index = 12345
    return mock


def create_mock_order_book_orders(bid_price: str, ask_price: str):
    """Create mock OrderBookOrders object"""
    mock = MagicMock()
    mock.bids = [create_mock_simple_order(bid_price)] if bid_price else []
    mock.asks = [create_mock_simple_order(ask_price)] if ask_price else []
    mock.total_bids = len(mock.bids)
    mock.total_asks = len(mock.asks)
    return mock


# ============================================================================
# Test: get_pairs()
# ============================================================================

async def test_get_pairs_maps_min_fields():
    """Test get_pairs() returns TradingPair list with minimum fields"""
    # Setup
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={},
    )

    mock_client = AsyncMock(spec=ILighterMarketDataClient)
    mock_order_books = [
        create_mock_order_book(market_id=0, symbol="ETH"),
        create_mock_order_book(market_id=1, symbol="BTC"),
    ]
    mock_client.list_order_books = AsyncMock(return_value=mock_order_books)

    adapter = LighterVenueAdapter(config, mode="live", market_data_client=mock_client)

    # Execute
    pairs = await adapter.get_pairs()

    # Assert
    assert len(pairs) == 2, f"Expected 2 pairs, got {len(pairs)}"

    eth_pair = next((p for p in pairs if p.symbol == "ETH-USDC"), None)
    assert eth_pair is not None, "ETH-USDC pair not found"
    assert eth_pair.pair_id == 0
    assert eth_pair.base == "ETH"
    assert eth_pair.quote == "USDC"
    assert eth_pair.maker_fee_percent == 0.0
    assert eth_pair.taker_fee_percent == 0.0
    assert eth_pair.is_market_open is True
    assert eth_pair.max_leverage is None  # Not available in OrderBook

    btc_pair = next((p for p in pairs if p.symbol == "BTC-USDC"), None)
    assert btc_pair is not None, "BTC-USDC pair not found"
    assert btc_pair.pair_id == 1

    print("✓ test_get_pairs_maps_min_fields")


# ============================================================================
# Test: get_latest_price() - Success
# ============================================================================

async def test_get_latest_price_ok_bid_ask_mid():
    """Test get_latest_price() returns PriceData with bid/ask/mid"""
    # Setup
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={"ETH": 0},  # Static mapping
    )

    mock_client = AsyncMock(spec=ILighterMarketDataClient)
    mock_order_book_orders = create_mock_order_book_orders(
        bid_price="1973.34",
        ask_price="1973.50"
    )
    mock_client.get_order_book_orders = AsyncMock(return_value=mock_order_book_orders)

    adapter = LighterVenueAdapter(config, mode="live", market_data_client=mock_client)

    # Execute
    price_data = await adapter.get_latest_price("ETH")

    # Assert
    assert price_data.symbol == "ETH"
    assert price_data.bid == 1973.34
    assert price_data.ask == 1973.50
    assert price_data.mid == (1973.34 + 1973.50) / 2.0
    assert isinstance(price_data.timestamp, datetime)

    print("✓ test_get_latest_price_ok_bid_ask_mid")


# ============================================================================
# Test: get_latest_price() - Market Not Found
# ============================================================================

async def test_get_latest_price_market_not_found():
    """Test get_latest_price() raises MarketNotFoundError for unknown symbol"""
    # Setup
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={},  # Empty mapping
    )

    mock_client = AsyncMock(spec=ILighterMarketDataClient)
    mock_client.list_order_books = AsyncMock(return_value=[])  # No markets

    adapter = LighterVenueAdapter(config, mode="live", market_data_client=mock_client)

    # Execute & Assert
    try:
        await adapter.get_latest_price("UNKNOWN")
        assert False, "Expected MarketNotFoundError"
    except MarketNotFoundError as e:
        assert e.symbol == "UNKNOWN"
        print("✓ test_get_latest_price_market_not_found")


# ============================================================================
# Test: get_latest_price() - No Liquidity
# ============================================================================

async def test_get_latest_price_no_liquidity_raises():
    """Test get_latest_price() raises NoLiquidityError for empty orderbook"""
    # Setup
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={"ETH": 0},
    )

    mock_client = AsyncMock(spec=ILighterMarketDataClient)
    # Empty orderbook (no bids, no asks)
    mock_order_book_orders = create_mock_order_book_orders(
        bid_price=None,  # No bids
        ask_price=None   # No asks
    )
    mock_client.get_order_book_orders = AsyncMock(return_value=mock_order_book_orders)

    adapter = LighterVenueAdapter(config, mode="live", market_data_client=mock_client)

    # Execute & Assert
    try:
        await adapter.get_latest_price("ETH")
        assert False, "Expected NoLiquidityError"
    except NoLiquidityError as e:
        assert e.symbol == "ETH"
        print("✓ test_get_latest_price_no_liquidity_raises")


# ============================================================================
# Test: get_latest_price() - Symbol Canonicalization
# ============================================================================

async def test_get_latest_price_symbol_canonicalization():
    """Test get_latest_price() accepts both "ETH" and "ETH-USDC" formats"""
    # Setup
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={"ETH": 0},
    )

    mock_client = AsyncMock(spec=ILighterMarketDataClient)
    mock_order_book_orders = create_mock_order_book_orders(
        bid_price="1973.34",
        ask_price="1973.50"
    )
    mock_client.get_order_book_orders = AsyncMock(return_value=mock_order_book_orders)

    adapter = LighterVenueAdapter(config, mode="live", market_data_client=mock_client)

    # Execute - both formats should work
    price1 = await adapter.get_latest_price("ETH")
    price2 = await adapter.get_latest_price("ETH-USDC")

    # Assert - both return same price
    assert price1.symbol == price2.symbol == "ETH"
    assert price1.mid == price2.mid

    print("✓ test_get_latest_price_symbol_canonicalization")


# ============================================================================
# Main test runner
# ============================================================================

async def main():
    """Run all tests"""
    print("=" * 80)
    print("LIGHTER ADAPTER MARKET DATA TESTS")
    print("=" * 80)
    print()

    tests = [
        test_get_pairs_maps_min_fields,
        test_get_latest_price_ok_bid_ask_mid,
        test_get_latest_price_market_not_found,
        test_get_latest_price_no_liquidity_raises,
        test_get_latest_price_symbol_canonicalization,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 80)
    print(f"Tests: {passed} passed, {failed} failed")
    print("=" * 80)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
