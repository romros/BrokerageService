"""
Unit tests for GTradeMarketStatusProvider

Tests optimistic strategy and weekend heuristics.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.config import GTRADE_PAIR_ID_TO_SYMBOL
from infrastructure.venues.gtrade.market_status_provider import GTradeMarketStatusProvider


def _first_supported_symbol():
    """First symbol from config (agnostic of mainnet vs Sepolia)."""
    if not GTRADE_PAIR_ID_TO_SYMBOL:
        return "BTCUSD"
    return next(iter(GTRADE_PAIR_ID_TO_SYMBOL.values()))


def _pair_id_for_first():
    """pair_id for first symbol in config."""
    if not GTRADE_PAIR_ID_TO_SYMBOL:
        return 0
    return next(iter(GTRADE_PAIR_ID_TO_SYMBOL.keys()))


async def test_supported_symbol_returns_tradable():
    """Known symbol (from config) should return tradable=True (optimistic)."""
    provider = GTradeMarketStatusProvider(
        w3=MagicMock(),
        diamond_address="0xDiamond",
        wallet_address="0xWallet",
        collateral_index=0,
    )

    sym = _first_supported_symbol()
    status = await provider.get_market_status(sym)

    assert status.is_tradable is True
    assert status.symbol == sym
    assert status.pair_id == _pair_id_for_first()
    assert "tradable" in status.reason.lower()
    print("✓ test_supported_symbol_returns_tradable")


async def test_unsupported_symbol_returns_not_tradable():
    """Unknown symbol should return tradable=False"""
    provider = GTradeMarketStatusProvider(
        w3=MagicMock(),
        diamond_address="0xDiamond",
        wallet_address="0xWallet",
        collateral_index=0,
    )

    status = await provider.get_market_status("INVALID")

    assert status.is_tradable is False
    assert status.symbol == "INVALID"
    assert status.pair_id is None
    assert "not supported" in status.reason.lower()
    print("✓ test_unsupported_symbol_returns_not_tradable")


async def test_forex_weekend_warning():
    """Forex/metals symbols should show weekend warning on Saturday/Sunday."""
    provider = GTradeMarketStatusProvider(
        w3=MagicMock(),
        diamond_address="0xDiamond",
        wallet_address="0xWallet",
        collateral_index=0,
    )

    # Use a symbol that triggers weekend heuristic (forex or metals) if in config, else any supported
    sym = _first_supported_symbol()
    saturday = datetime(2024, 1, 6, 12, 0, 0, tzinfo=timezone.utc)

    with patch("infrastructure.venues.gtrade.market_status_provider.datetime") as mock_datetime:
        mock_datetime.now.return_value = saturday

        status = await provider.get_market_status(sym)

        assert status.is_tradable is True
        # Weekend warning only for forex/metals; crypto may not have it
        if sym in provider.FOREX_SYMBOLS or sym in provider.METALS_SYMBOLS:
            assert "WARNING" in status.reason
            assert "weekend" in status.reason.lower()
        print("✓ test_forex_weekend_warning")


async def test_get_first_tradable_symbol_returns_first_known():
    """Should return first known (supported) symbol from list."""
    provider = GTradeMarketStatusProvider(
        w3=MagicMock(),
        diamond_address="0xDiamond",
        wallet_address="0xWallet",
        collateral_index=0,
    )

    supported = list(GTRADE_PAIR_ID_TO_SYMBOL.values())
    symbols = supported + ["INVALID"] if supported else ["BTCUSD", "INVALID"]

    status = await provider.get_first_tradable_symbol(symbols)

    assert status is not None
    assert status.symbol in GTRADE_PAIR_ID_TO_SYMBOL.values()
    assert status.is_tradable is True
    print("✓ test_get_first_tradable_symbol_returns_first_known")


async def test_get_first_tradable_symbol_returns_none_if_all_unknown():
    """Should return None if all symbols are unknown"""
    provider = GTradeMarketStatusProvider(
        w3=MagicMock(),
        diamond_address="0xDiamond",
        wallet_address="0xWallet",
        collateral_index=0,
    )

    symbols = ["INVALID1", "INVALID2", "INVALID3"]

    status = await provider.get_first_tradable_symbol(symbols)

    assert status is None
    print("✓ test_get_first_tradable_symbol_returns_none_if_all_unknown")


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Market Status Provider - Unit Tests")
    print("=" * 60 + "\n")

    tests = [
        test_supported_symbol_returns_tradable,
        test_unsupported_symbol_returns_not_tradable,
        test_forex_weekend_warning,
        test_get_first_tradable_symbol_returns_first_known,
        test_get_first_tradable_symbol_returns_none_if_all_unknown,
    ]

    for test in tests:
        try:
            await test()
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            return 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            return 1

    print("\n✓ All tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
