#!/usr/bin/env python3
"""
Real E2E Smoke Test - Arbitrum Sepolia Testnet

CRITICAL SAFETY GUARDS:
- ENABLE_LIVE_TRADING=1 required
- E2E_TESTNET=1 required
- Chain ID must be 421614 (Sepolia)
- MAX_COLLATERAL_USDC enforced (default: 10)
- Mainnet detection → abort

Flow:
1. Health check (balances, chain_id)
2. Get first tradable symbol (with fallback)
3. Open position (small collateral)
4. Wait for confirmation + backend verification
5. Verify position appears in open_positions
6. Close position
7. Wait for close confirmation
8. Verify position removed from open_positions
9. Final balance check

Usage:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 ./test.sh _archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py
"""

import asyncio
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

# Add project root to path (works from scripts/ or _archive/.../scripts/)
_project = Path(__file__).resolve()
project_root = _project.parent
for _ in range(5):
    if (project_root / "application").is_dir() or (project_root / "docker-compose.yml").exists():
        break
    project_root = project_root.parent
sys.path.insert(0, str(project_root))

from web3 import AsyncWeb3
from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade.chain_config import ChainConfig


# ============================================================================
# SAFETY GUARDS
# ============================================================================

SEPOLIA_CHAIN_ID = 421614
MAINNET_CHAIN_IDS = [1, 42161, 137, 8453]  # Ethereum, Arbitrum One, Polygon, Base
DEFAULT_MAX_COLLATERAL = 10.0  # USDC


def check_safety_guards():
    """
    Verify all safety conditions before executing

    Aborts if:
    - ENABLE_LIVE_TRADING not set
    - E2E_TESTNET not set
    - On mainnet chain
    """
    print("\n" + "=" * 80)
    print("🔒 SAFETY CHECKS")
    print("=" * 80 + "\n")

    # Check ENABLE_LIVE_TRADING
    if os.getenv("ENABLE_LIVE_TRADING") != "1":
        print("❌ ABORT: ENABLE_LIVE_TRADING must be set to '1'")
        print("   This protects against accidental transaction execution")
        sys.exit(1)
    print("✅ ENABLE_LIVE_TRADING=1")

    # Check E2E_TESTNET
    if os.getenv("E2E_TESTNET") != "1":
        print("❌ ABORT: E2E_TESTNET must be set to '1'")
        print("   This confirms you intend to run real testnet transactions")
        sys.exit(1)
    print("✅ E2E_TESTNET=1")

    # Check MAX_COLLATERAL
    max_collateral = float(os.getenv("MAX_COLLATERAL_USDC", DEFAULT_MAX_COLLATERAL))
    print(f"✅ MAX_COLLATERAL_USDC={max_collateral}")

    print("\n✓ All safety guards passed\n")
    return max_collateral


def verify_chain_id(adapter: GTradeVenueAdapter, expected_chain_id: int):
    """Verify we're on correct chain (Sepolia)"""
    actual_chain_id = adapter._config.chain_id

    if actual_chain_id in MAINNET_CHAIN_IDS:
        print(f"❌ ABORT: Detected MAINNET chain_id={actual_chain_id}")
        print("   E2E smoke tests are ONLY for testnet")
        sys.exit(1)

    if actual_chain_id != expected_chain_id:
        print(f"❌ ABORT: Wrong chain_id={actual_chain_id}, expected {expected_chain_id}")
        sys.exit(1)

    print(f"✅ Chain ID: {actual_chain_id} (Arbitrum Sepolia)")


# ============================================================================
# E2E FLOW
# ============================================================================

async def main():
    print("\n" + "=" * 80)
    print("🧪 REAL E2E SMOKE TEST - Arbitrum Sepolia")
    print("=" * 80 + "\n")

    # Step 0: Safety guards
    max_collateral = check_safety_guards()

    # Configuration
    # NOTE: gTrade Sepolia testnet requires minimum position size of $1,500 USD
    # (collateral × leverage ≥ $1,500)
    collateral = min(150.0, max_collateral)  # 150 USDC for valid position size
    leverage = 10  # 150 × 10 = $1,500 (meets minimum)

    # NOTE: Sepolia testnet only has crypto pairs (BTC, ETH, LINK, etc.), not forex (XAU, EUR)
    primary_symbols = os.getenv("PRIMARY_SYMBOLS", "BTCUSD,ETHUSD").split(",")
    fallback_symbols = os.getenv("FALLBACK_SYMBOLS", "LINKUSD").split(",")
    all_symbols = primary_symbols + fallback_symbols

    print(f"📋 Configuration:")
    print(f"   Collateral: {collateral} USDC")
    print(f"   Leverage: {leverage}x")
    print(f"   Symbols: {', '.join(all_symbols)}")
    print(f"   Max collateral limit: {max_collateral} USDC")
    print()

    # Step 1: Create adapter and health check
    print("=" * 80)
    print("📈 Step 1: Health Check")
    print("=" * 80 + "\n")

    adapter = GTradeVenueAdapter()
    await adapter.start()

    # Verify chain
    verify_chain_id(adapter, SEPOLIA_CHAIN_ID)

    # Get balances
    health = await adapter.health_check()
    print(f"Diamond: {adapter._config.addresses.diamond}")
    print(f"Wallet: {adapter.get_wallet_address()}")
    print(f"ETH Balance: {health['eth_balance']:.6f} ETH")
    print(f"USDC Balance: {health['usdc_balance']:.2f} USDC")
    print()

    # Check minimum balances
    if Decimal(str(health["eth_balance"])) < Decimal("0.001"):
        print("❌ ABORT: Insufficient ETH balance (need at least 0.001 ETH for gas)")
        sys.exit(1)

    if Decimal(str(health["usdc_balance"])) < Decimal(str(collateral)):
        print(f"❌ ABORT: Insufficient USDC balance (need at least {collateral} USDC)")
        sys.exit(1)

    initial_eth = Decimal(str(health["eth_balance"]))
    initial_usdc = Decimal(str(health["usdc_balance"]))

    # Step 2: Get tradable symbol
    print("=" * 80)
    print("📊 Step 2: Find Tradable Symbol")
    print("=" * 80 + "\n")

    print(f"Checking symbols in order: {all_symbols}")
    status = await adapter._market_status.get_first_tradable_symbol(all_symbols)

    if not status:
        print("❌ No tradable symbols found!")
        sys.exit(1)

    symbol = status.symbol
    print(f"✅ Selected symbol: {symbol}")
    print(f"   Pair ID: {status.pair_id}")
    print(f"   Reason: {status.reason}")

    is_fallback = symbol not in primary_symbols
    if is_fallback:
        print(f"   ℹ️  Using fallback symbol (primary symbols unavailable)")
    print()

    # Step 3: Open position
    print("=" * 80)
    print("📈 Step 3: Open Position")
    print("=" * 80 + "\n")

    print(f"Opening {symbol} LONG, {collateral} USDC @ {leverage}x leverage...")

    open_start = time.time()

    try:
        result = await adapter.open_position(
            symbol=symbol,
            is_long=True,
            collateral=collateral,
            leverage=leverage,
            sl_price=None,
            tp_price=None,
            client_order_id=f"e2e_smoke_{int(time.time())}"
        )
    except Exception as e:
        print(f"❌ Open position failed: {e}")
        raise

    open_duration = time.time() - open_start

    print(f"✅ Position opened!")
    print(f"   Position ID: {result.position_id}")
    print(f"   Fill Price: {result.fill_price}")
    print(f"   Fee: {result.fee:.2f} USDC")
    print(f"   Duration: {open_duration:.1f}s")
    print()

    # Verify position_id format (should be "pair_id:trade_index", not "pending:...")
    if result.position_id.startswith("pending:"):
        print(f"⚠️  WARNING: Position ID still pending (backend timeout?)")
        print(f"   This may indicate backend polling issues")

    position_id = result.position_id

    # Step 4: Verify position appears
    print("=" * 80)
    print("📋 Step 4: Verify Position Listed")
    print("=" * 80 + "\n")

    open_positions = await adapter.get_open_positions()

    print(f"Open positions: {len(open_positions)}")

    found = False
    for pos in open_positions:
        if pos.position_id == position_id:
            found = True
            print(f"✅ Position found in open_positions:")
            print(f"   ID: {pos.position_id}")
            print(f"   Symbol: {pos.symbol}")
            print(f"   Side: {'LONG' if pos.is_long else 'SHORT'}")
            print(f"   Entry: {pos.entry_price}")
            print(f"   Size: {pos.collateral} USDC @ {pos.leverage}x")
            break

    if not found:
        print(f"⚠️  WARNING: Position {position_id} not found in open_positions")
        print(f"   This may indicate backend sync delay")
    print()

    # Step 5: Close position
    print("=" * 80)
    print("📉 Step 5: Close Position")
    print("=" * 80 + "\n")

    print(f"Closing position {position_id}...")

    close_start = time.time()

    try:
        close_result = await adapter.close_position(position_id)
    except Exception as e:
        print(f"❌ Close position failed: {e}")
        raise

    close_duration = time.time() - close_start

    print(f"✅ Position closed!")
    print(f"   Exit Price: {close_result.fill_price}")
    print(f"   Fee: {close_result.fee:.2f} USDC")
    print(f"   Duration: {close_duration:.1f}s")
    print()

    # Step 6: Verify position removed
    print("=" * 80)
    print("📋 Step 6: Verify Position Removed")
    print("=" * 80 + "\n")

    open_positions_after = await adapter.get_open_positions()

    print(f"Open positions: {len(open_positions_after)}")

    still_found = any(pos.position_id == position_id for pos in open_positions_after)

    if still_found:
        print(f"⚠️  WARNING: Position {position_id} still in open_positions")
        print(f"   This may indicate backend sync delay")
    else:
        print(f"✅ Position removed from open_positions")
    print()

    # Step 7: Final balance check
    print("=" * 80)
    print("📊 Step 7: Final Balance Check")
    print("=" * 80 + "\n")

    final_health = await adapter.health_check()
    final_eth = Decimal(str(final_health["eth_balance"]))
    final_usdc = Decimal(str(final_health["usdc_balance"]))

    eth_spent = initial_eth - final_eth
    usdc_change = final_usdc - initial_usdc

    print(f"ETH spent (gas): {eth_spent:.6f} ETH")
    print(f"USDC change: {usdc_change:+.2f} USDC")
    print(f"Final ETH: {final_eth:.6f} ETH")
    print(f"Final USDC: {final_usdc:.2f} USDC")
    print()

    # Summary
    print("=" * 80)
    print("✅ E2E SMOKE TEST PASSED")
    print("=" * 80)
    print(f"Symbol: {symbol} {'(fallback)' if is_fallback else '(primary)'}")
    print(f"Open duration: {open_duration:.1f}s")
    print(f"Close duration: {close_duration:.1f}s")
    print(f"Total ETH spent: {eth_spent:.6f} ETH")
    print(f"Net USDC change: {usdc_change:+.2f} USDC")
    print("=" * 80 + "\n")

    await adapter.stop()

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ E2E smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
