#!/usr/bin/env python3
"""
Lab Script: Open Trade Once (Testnet)

Executa 1 trade mínim amb preu real del WebSocket feed.
NOMÉS amb safety guards: E2E_TESTNET=1 + ENABLE_LIVE_TRADING=1

Usage:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
    WALLET_PRIVATE_KEY=0x... \
    python lab/gtrade/open_trade_once.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade.price_provider import GTradePriceProviderWS
from infrastructure.venues.gtrade import abi_encoder
from loguru import logger

# Test configuration
SYMBOL = "BTCUSD"
COLLATERAL = 150.0  # USDC (meets $1,500 minimum @ 10x)
LEVERAGE = 10
IS_LONG = True


async def main():
    print("\n" + "=" * 80)
    print("🧪 LAB: Open Trade Once (Testnet)")
    print("=" * 80)
    print()

    # Safety check 1: E2E_TESTNET
    if os.getenv("E2E_TESTNET") != "1":
        print("❌ E2E_TESTNET not set")
        print()
        print("This script executes REAL testnet transactions.")
        print("Set E2E_TESTNET=1 to confirm execution.")
        return 1

    # Safety check 2: ENABLE_LIVE_TRADING
    if os.getenv("ENABLE_LIVE_TRADING") != "1":
        print("❌ ENABLE_LIVE_TRADING not set")
        return 1

    print(f"📋 Configuration:")
    print(f"   Symbol: {SYMBOL}")
    print(f"   Direction: {'LONG' if IS_LONG else 'SHORT'}")
    print(f"   Collateral: {COLLATERAL} USDC")
    print(f"   Leverage: {LEVERAGE}x")
    print(f"   Position Size: ${COLLATERAL * LEVERAGE:,.0f} USD")
    print()

    # Start price provider
    print("📡 Starting price provider...")
    price_provider = GTradePriceProviderWS()
    await price_provider.start()

    try:
        # Get current price
        print(f"🔍 Fetching current price for {SYMBOL}...")
        oracle_price = await price_provider.get_current_price(SYMBOL)
        print(f"   Oracle Price: ${oracle_price:,.2f}")
        print()

        # Calculate openPrice with buffer
        buffer = 1.05 if IS_LONG else 0.95  # 5% buffer
        open_price = oracle_price * buffer
        open_price_scaled = abi_encoder.price_to_contract_units(open_price)

        print(f"💡 Calculated openPrice:")
        print(f"   Buffer: {buffer:.2%}")
        print(f"   openPrice: ${open_price:,.2f}")
        print(f"   Scaled (1e10): {open_price_scaled}")
        print()

        # Create adapter
        print("🔧 Initializing adapter...")
        adapter = GTradeVenueAdapter(mode="live")
        await adapter.start()

        # Health check
        print("🏥 Health check...")
        health = await adapter.health_check()

        if isinstance(health, dict):
            print(f"   ✅ Chain ID: {health['chain_id']} (Sepolia)")
            print(f"   ETH Balance: {health['eth_balance']:.6f} ETH")
            print(f"   USDC Balance: {health['usdc_balance']:.2f} USDC")
            print()

            # Verify balances
            if health['eth_balance'] < 0.01:
                print("❌ Insufficient ETH for gas (need >= 0.01 ETH)")
                return 1

            if health['usdc_balance'] < COLLATERAL:
                print(f"❌ Insufficient USDC (need >= {COLLATERAL} USDC)")
                return 1
        else:
            print("⚠️  Health check returned bool (no wallet configured?)")

        print()

        # Confirm execution
        print("⚠️  READY TO EXECUTE REAL TRANSACTION")
        print()
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            print("❌ Aborted by user")
            return 1

        print()

        # Open position
        print(f"📈 Opening position...")
        result = await adapter.open_position(
            symbol=SYMBOL,
            is_long=IS_LONG,
            collateral=COLLATERAL,
            leverage=LEVERAGE,
            sl_price=None,
            tp_price=None,
        )

        print()
        print("=" * 80)
        print("✅ TRADE EXECUTED SUCCESSFULLY")
        print("=" * 80)
        print()
        print(f"Position ID: {result.position_id}")
        print(f"Fill Price: ${result.fill_price:,.2f}")

        if hasattr(result, 'tx_hash') and result.tx_hash:
            print(f"TxHash: {result.tx_hash}")
            print(f"Explorer: https://sepolia.arbiscan.io/tx/{result.tx_hash}")

        print()
        print("📝 Next steps:")
        print("   1. Verify transaction on Arbiscan")
        print("   2. Check position appears in /open-trades")
        print("   3. Document results in lab/NOTES.md")

        return 0

    except Exception as e:
        print()
        print("=" * 80)
        print("❌ TRADE FAILED")
        print("=" * 80)
        print()
        print(f"Error: {e}")
        print()

        # Check if it's the price validation error
        error_str = str(e)
        if "0x10906acb" in error_str:
            print("💡 This is the price validation error!")
            print("   openPrice might be outside acceptable range")
            print(f"   Tried: ${open_price:,.2f} (oracle: ${oracle_price:,.2f})")
        elif "insufficient" in error_str.lower():
            print("💡 Check balances and allowances")
        elif "collateral" in error_str.lower():
            print("💡 Check collateralIndex (should be 3 for Sepolia)")

        import traceback
        traceback.print_exc()

        return 1

    finally:
        await price_provider.stop()
        if 'adapter' in locals():
            await adapter.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
