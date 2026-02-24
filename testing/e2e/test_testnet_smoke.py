"""
Real E2E Testnet Smoke Test (pytest wrapper)

⚠️  MANUAL/SLOW TEST - NOT RUN IN CI BY DEFAULT

This test executes REAL transactions on Arbitrum Sepolia testnet.
It is marked with @pytest.mark.e2e and skipped unless:
- E2E_TESTNET=1
- ENABLE_LIVE_TRADING=1

Usage:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/test_testnet_smoke.py -v -s

Why pytest wrapper?
- Integration with CI/CD pipelines (manual trigger)
- Compatibility with pytest tooling (coverage, reporting)
- Consistent test discovery pattern

For standalone execution:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 python _archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py
"""

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter


# ============================================================================
# SKIP CONDITIONS
# ============================================================================

skip_reason = None

if os.getenv("E2E_TESTNET") != "1":
    skip_reason = "E2E_TESTNET=1 required (protects against accidental execution)"

if os.getenv("ENABLE_LIVE_TRADING") != "1":
    skip_reason = "ENABLE_LIVE_TRADING=1 required (real transactions)"


# ============================================================================
# TEST
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.skipif(skip_reason is not None, reason=skip_reason)
async def test_e2e_testnet_smoke():
    """
    E2E smoke test: open + close position on Arbitrum Sepolia

    Validates:
    - Chain connection (Sepolia only)
    - Balance checks
    - Market fallback logic
    - Open position with TxSender + backend verification
    - Position appears in open_positions
    - Close position
    - Position removed from open_positions
    """

    # Configuration
    SEPOLIA_CHAIN_ID = 421614
    MAX_COLLATERAL = float(os.getenv("MAX_COLLATERAL_USDC", "10.0"))
    collateral = min(5.0, MAX_COLLATERAL)
    leverage = 2

    primary_symbols = os.getenv("PRIMARY_SYMBOLS", "XAUUSD,EURUSD").split(",")
    fallback_symbols = os.getenv("FALLBACK_SYMBOLS", "BTCUSD").split(",")
    all_symbols = primary_symbols + fallback_symbols

    # Create adapter
    adapter = GTradeVenueAdapter()
    await adapter.start()

    try:
        # Verify chain ID (must be Sepolia)
        assert adapter._config.chain_id == SEPOLIA_CHAIN_ID, \
            f"Wrong chain_id={adapter._config.chain_id}, expected Sepolia (421614)"

        # Health check
        health = await adapter.health_check()
        initial_eth = Decimal(str(health["eth_balance"]))
        initial_usdc = Decimal(str(health["usdc_balance"]))

        assert initial_eth >= Decimal("0.001"), "Insufficient ETH balance"
        assert initial_usdc >= Decimal(str(collateral)), f"Insufficient USDC balance"

        # Get tradable symbol
        status = await adapter._market_status.get_first_tradable_symbol(all_symbols)
        assert status is not None, "No tradable symbols found"

        symbol = status.symbol

        # Open position
        result = await adapter.open_position(
            symbol=symbol,
            is_long=True,
            collateral=collateral,
            leverage=leverage,
            sl_price=None,
            tp_price=None,
            client_order_id=f"pytest_e2e_{os.getpid()}"
        )

        assert result.position_id is not None
        assert result.fill_price > 0
        position_id = result.position_id

        # Verify position listed
        open_positions = await adapter.get_open_positions()
        assert any(pos.position_id == position_id for pos in open_positions), \
            "Position not found in open_positions"

        # Close position
        close_result = await adapter.close_position(position_id)
        assert close_result.fill_price > 0

        # Verify position removed
        open_positions_after = await adapter.get_open_positions()
        assert not any(pos.position_id == position_id for pos in open_positions_after), \
            "Position still in open_positions after close"

        # Final balance check
        final_health = await adapter.health_check()
        final_eth = Decimal(str(final_health["eth_balance"]))
        final_usdc = Decimal(str(final_health["usdc_balance"]))

        eth_spent = initial_eth - final_eth
        usdc_change = final_usdc - initial_usdc

        # Sanity checks
        assert eth_spent > 0, "Should have spent ETH on gas"
        assert eth_spent < Decimal("0.1"), "Gas cost too high (sanity check)"

        print(f"\n✅ E2E Smoke Test Passed:")
        print(f"   Symbol: {symbol}")
        print(f"   ETH spent: {eth_spent:.6f} ETH")
        print(f"   USDC change: {usdc_change:+.2f} USDC")

    finally:
        await adapter.stop()


# ============================================================================
# STANDALONE EXECUTION (fallback to script)
# ============================================================================

if __name__ == "__main__":
    print("⚠️  Running E2E test outside pytest")
    print("   For better reporting, use:")
    print("   E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/test_testnet_smoke.py -v -s")
    print()

    if skip_reason:
        print(f"❌ Skipped: {skip_reason}")
        sys.exit(0)

    asyncio.run(test_e2e_testnet_smoke())
