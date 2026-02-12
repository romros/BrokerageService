#!/usr/bin/env python3
"""
Lab Script: Test openPrice with Different Buffers

Test amb diferents buffers per trobar el rang acceptable.

MANUAL EXECUTION REQUIRED:
1. Obtén preu actual de BTC (ex: CoinGecko, Binance)
2. Edita MANUAL_PRICE_BTC a sota
3. Executa script
4. Documenta resultats a lab/NOTES.md

Usage:
    LAB_CONFIRM=1 python lab/sepolia/test_open_price_buffer.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade import abi_encoder
from loguru import logger

# ============================================
# MANUAL CONFIGURATION
# ============================================

# 🔴 IMPORTANT: Update this with CURRENT BTC price before running!
# Source: https://www.coingecko.com/en/coins/bitcoin
MANUAL_PRICE_BTC = 70500.0  # USD (UPDATE THIS!)

# Buffers to test (for LONG positions)
BUFFERS_TO_TEST = [
    1.02,  # 2% buffer
    1.05,  # 5% buffer
    1.10,  # 10% buffer
    1.15,  # 15% buffer
]

# Test configuration
TEST_SYMBOL = "BTCUSD"
TEST_COLLATERAL = 150.0  # USDC (meets $1,500 minimum @ 10x)
TEST_LEVERAGE = 10
TEST_IS_LONG = True

# ============================================


async def test_open_price_buffer(oracle_price: float, buffer: float):
    """
    Test openTrade with specific buffer

    Returns:
        tuple: (success: bool, error_message: str)
    """
    print(f"\n{'=' * 60}")
    print(f"Testing buffer: {buffer:.2%}")
    print(f"{'=' * 60}")

    # Calculate openPrice
    open_price = oracle_price * buffer
    open_price_scaled = abi_encoder.price_to_contract_units(open_price)

    print(f"Oracle Price: ${oracle_price:,.2f}")
    print(f"Open Price: ${open_price:,.2f} (buffer: {buffer:.2%})")
    print(f"Scaled (1e10): {open_price_scaled}")
    print()

    # Create adapter
    adapter = GTradeVenueAdapter(mode="live")
    await adapter.start()

    try:
        # Try to open position (will fail at gas estimation if invalid)
        print(f"🔍 Testing with {TEST_SYMBOL} {TEST_LEVERAGE}x {'LONG' if TEST_IS_LONG else 'SHORT'}...")
        print(f"   Collateral: {TEST_COLLATERAL} USDC")
        print()

        # IMPORTANT: This will do gas estimation only (eth_estimateGas)
        # If estimation succeeds → params are valid
        # If estimation fails → params are rejected by contract

        result = await adapter.open_position(
            symbol=TEST_SYMBOL,
            is_long=TEST_IS_LONG,
            collateral=TEST_COLLATERAL,
            leverage=TEST_LEVERAGE,
            sl_price=None,
            tp_price=None,
        )

        print(f"✅ SUCCESS: Position opened")
        print(f"   Position ID: {result.position_id}")
        print(f"   Fill Price: ${result.fill_price:,.2f}")

        return (True, None)

    except Exception as e:
        error_msg = str(e)
        print(f"❌ FAILED: {error_msg}")

        # Check if it's the price validation error
        if "0x10906acb" in error_msg:
            return (False, "PRICE_VALIDATION_ERROR (0x10906acb)")
        else:
            return (False, error_msg)

    finally:
        await adapter.stop()


async def main():
    print("\n" + "=" * 80)
    print("🧪 LAB: Test openPrice Buffer")
    print("=" * 80)
    print()

    # Safety check
    if os.getenv("LAB_CONFIRM") != "1":
        print("❌ LAB_CONFIRM not set")
        print()
        print("This script will attempt REAL testnet transactions.")
        print("Set LAB_CONFIRM=1 to confirm execution.")
        return 1

    if os.getenv("ENABLE_LIVE_TRADING") != "1":
        print("❌ ENABLE_LIVE_TRADING not set")
        return 1

    # Verify manual price is updated
    if MANUAL_PRICE_BTC == 70500.0:
        print("⚠️  WARNING: Using default BTC price (70,500 USD)")
        print("   Update MANUAL_PRICE_BTC with current price for accurate results")
        print()
        response = input("Continue anyway? [y/N]: ")
        if response.lower() != 'y':
            return 1

    print(f"📋 Test Configuration:")
    print(f"   Symbol: {TEST_SYMBOL}")
    print(f"   Oracle Price: ${MANUAL_PRICE_BTC:,.2f} (MANUAL)")
    print(f"   Direction: {'LONG' if TEST_IS_LONG else 'SHORT'}")
    print(f"   Collateral: {TEST_COLLATERAL} USDC")
    print(f"   Leverage: {TEST_LEVERAGE}x")
    print(f"   Position Size: ${TEST_COLLATERAL * TEST_LEVERAGE:,.0f} USD")
    print()

    # Test each buffer
    results = []
    for buffer in BUFFERS_TO_TEST:
        success, error = await test_open_price_buffer(MANUAL_PRICE_BTC, buffer)
        results.append({
            "buffer": buffer,
            "buffer_pct": f"{(buffer - 1) * 100:.0f}%",
            "open_price": MANUAL_PRICE_BTC * buffer,
            "success": success,
            "error": error,
        })

        # Wait between attempts
        if buffer != BUFFERS_TO_TEST[-1]:
            print("\n⏳ Waiting 5 seconds before next test...")
            await asyncio.sleep(5)

    # Summary
    print("\n" + "=" * 80)
    print("📊 Results Summary")
    print("=" * 80)
    print()

    for r in results:
        status = "✅ OK" if r["success"] else "❌ FAIL"
        print(f"{r['buffer_pct']:>5} buffer: {status:12} (openPrice: ${r['open_price']:,.2f})")
        if not r["success"]:
            print(f"        Error: {r['error']}")

    print()

    # Find optimal buffer
    successful_buffers = [r for r in results if r["success"]]
    if successful_buffers:
        optimal = min(successful_buffers, key=lambda x: x["buffer"])
        print(f"🎯 Optimal buffer: {optimal['buffer_pct']} (${optimal['open_price']:,.2f})")
        print()
        print("💡 Recommendation:")
        print(f"   Use buffer = {optimal['buffer']:.3f} for LONG positions")
        print(f"   This allows ~{(optimal['buffer'] - 1) * 100:.1f}% price movement tolerance")
    else:
        print("❌ No successful buffer found")
        print("   All openPrice values were rejected by contract")

    print()
    print("📝 Next step: Document these results in lab/NOTES.md")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
