"""
Integration test for adapter fallback flow

Tests that adapter correctly falls back to alternative symbols
when primary symbol fails with MarketClosedError.

Uses simple async/assert pattern (no pytest dependency).
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade.chain_config import ChainConfig, ContractAddresses
from domain.errors import MarketClosedError, NoTradableSymbolError
from domain.models import OrderResult


def create_mock_adapter():
    """Helper to create adapter with mocked dependencies"""
    # Create mock chain config
    mock_config = ChainConfig(
        rpc_url="https://mock-rpc",
        chain_id=421614,
        addresses=ContractAddresses(
            diamond="0xd659a15812064C79E189fd950A189b15c75d3186",  # Real Sepolia address
            trading="0xd659a15812064C79E189fd950A189b15c75d3186",
            usdc="0x4cC7EbEeD5EA3adf3978F19833d2E1f3e8980cD6",  # Real GNS_USDC
        ),
        wallet_private_key="0x" + "11" * 32,  # Mock key (non-zero)
    )

    # Create adapter with mock config
    adapter = GTradeVenueAdapter(chain_config=mock_config)
    adapter._account = MagicMock()
    adapter._wallet_address = "0xWallet"
    adapter._w3 = MagicMock()
    adapter._verifier = MagicMock()

    return adapter


async def test_fallback_when_primary_market_closed():
    """Should fallback to EURUSD when XAUUSD market closed"""
    print("  → test_fallback_when_primary_market_closed...", end=" ")

    # Set env vars for test
    os.environ["ENABLE_LIVE_TRADING"] = "1"
    os.environ["PRIMARY_SYMBOLS"] = "XAUUSD,EURUSD"
    os.environ["FALLBACK_SYMBOLS"] = ""

    # Create adapter with mocked dependencies
    adapter = create_mock_adapter()

    # Mock _try_open_position_single_symbol
    call_count = {"count": 0}

    async def mock_try_open(symbol, **kwargs):
        call_count["count"] += 1
        if symbol == "XAUUSD":
            # First attempt (XAUUSD) fails with market closed
            raise MarketClosedError(symbol="XAUUSD", pair_id=0, reason="Market closed")
        elif symbol == "EURUSD":
            # Second attempt (EURUSD) succeeds
            return OrderResult(
                success=True,
                position_id="2:123",  # EURUSD pair_id=2
                order_id="0xtxhash",
                executed_price=1.1000,
                executed_size=1000.0,
                fee=0.5,
                fees_breakdown={},
            )
        else:
            raise ValueError(f"Unexpected symbol: {symbol}")

    adapter._try_open_position_single_symbol = mock_try_open

    # Call open_position with XAUUSD
    result = await adapter.open_position(
        symbol="XAUUSD",
        is_long=True,
        collateral=100.0,
        leverage=5.0,
    )

    # Verify fallback worked
    assert result.success is True, "Result should be successful"
    assert result.position_id == "2:123", f"Expected EURUSD pair (2:123), got {result.position_id}"
    assert call_count["count"] == 2, f"Expected 2 attempts (XAUUSD, EURUSD), got {call_count['count']}"

    print("✓")


async def test_no_fallback_on_other_errors():
    """Should NOT fallback on non-market-closed errors"""
    print("  → test_no_fallback_on_other_errors...", end=" ")

    os.environ["ENABLE_LIVE_TRADING"] = "1"

    adapter = create_mock_adapter()

    # Mock to raise non-market-closed error
    async def mock_try_open(symbol, **kwargs):
        raise ValueError("Insufficient balance")

    adapter._try_open_position_single_symbol = mock_try_open

    # Should raise ValueError, NOT try fallback
    try:
        await adapter.open_position(
            symbol="XAUUSD",
            is_long=True,
            collateral=100.0,
            leverage=5.0,
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Insufficient balance" in str(e)

    print("✓")


async def test_no_tradable_symbol_when_all_fail():
    """Should raise NoTradableSymbolError when all symbols fail"""
    print("  → test_no_tradable_symbol_when_all_fail...", end=" ")

    os.environ["ENABLE_LIVE_TRADING"] = "1"
    os.environ["PRIMARY_SYMBOLS"] = "XAUUSD,EURUSD"
    os.environ["FALLBACK_SYMBOLS"] = ""

    adapter = create_mock_adapter()

    # Mock all symbols market closed
    async def mock_try_open(symbol, **kwargs):
        raise MarketClosedError(symbol=symbol, pair_id=0, reason="Market closed")

    adapter._try_open_position_single_symbol = mock_try_open

    # Should raise NoTradableSymbolError
    try:
        await adapter.open_position(
            symbol="XAUUSD",
            is_long=True,
            collateral=100.0,
            leverage=5.0,
        )
        assert False, "Should have raised NoTradableSymbolError"
    except NoTradableSymbolError as e:
        assert "XAUUSD" in e.attempted_symbols
        assert "EURUSD" in e.attempted_symbols

    print("✓")


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Adapter Fallback Flow - Integration Tests")
    print("=" * 60 + "\n")

    tests = [
        test_fallback_when_primary_market_closed,
        test_no_fallback_on_other_errors,
        test_no_tradable_symbol_when_all_fail,
    ]

    for test in tests:
        try:
            await test()
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            return 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            return 1

    print("\n✓ All tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
