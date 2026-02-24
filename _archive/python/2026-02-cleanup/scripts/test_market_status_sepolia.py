#!/usr/bin/env python3
"""
Test Market Status Provider with Arbitrum Sepolia testnet

Checks which symbols are currently tradable (XAUUSD vs EURUSD).
This is a manual verification script - NOT part of CI/CD test suite.

Usage:
    ./test.sh scripts/test_market_status_sepolia.py
"""

import asyncio
import os
import sys
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
from infrastructure.venues.gtrade.market_status_provider import GTradeMarketStatusProvider


async def main():
    print("=" * 80)
    print("🧪 MARKET STATUS CHECK - Arbitrum Sepolia")
    print("=" * 80)

    # Configuration (from .env or hardcoded for testnet)
    rpc_url = os.getenv("ARBITRUM_RPC_URL", "https://sepolia-rollup.arbitrum.io/rpc")
    diamond_address = os.getenv(
        "GTRADE_DIAMOND_ADDRESS", "0xd659a15812064C79E189fd950A189b15c75d3186"
    )
    wallet_address = os.getenv(
        "WALLET_ADDRESS", "0xD9fC17C093614D20976EFb1535A7142081A031b2"
    )

    print(f"\n📋 Configuration:")
    print(f"   RPC: {rpc_url}")
    print(f"   Diamond: {diamond_address}")
    print(f"   Wallet: {wallet_address}")

    # Create provider
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
    provider = GTradeMarketStatusProvider(
        w3=w3,
        diamond_address=diamond_address,
        wallet_address=wallet_address,
        collateral_index=0,  # USDC
    )

    # Test symbols
    symbols = ["EURUSD", "XAUUSD", "BTCUSD"]

    print(f"\n{'='*80}")
    print("📊 CHECKING MARKET STATUS")
    print(f"{'='*80}\n")

    results = {}
    for symbol in symbols:
        print(f"Checking {symbol}...", end=" ", flush=True)
        status = await provider.get_market_status(symbol)
        results[symbol] = status

        if status.is_tradable:
            print(f"✅ OPEN")
            print(f"   → Pair ID: {status.pair_id}")
            print(f"   → Reason: {status.reason}")
        else:
            print(f"❌ CLOSED")
            print(f"   → Pair ID: {status.pair_id}")
            print(f"   → Reason: {status.reason}")
            if status.details:
                revert = status.details.get("revert_msg", "")
                if revert:
                    print(f"   → Revert: {revert[:100]}...")
        print()

    # Test fallback logic
    print(f"{'='*80}")
    print("🔄 TESTING FALLBACK LOGIC")
    print(f"{'='*80}\n")

    fallback_order = ["XAUUSD", "EURUSD", "BTCUSD"]
    print(f"Trying symbols in order: {fallback_order}")
    print()

    first_tradable = await provider.get_first_tradable_symbol(fallback_order)

    if first_tradable:
        print(f"✅ Found tradable symbol: {first_tradable.symbol}")
        print(f"   → Pair ID: {first_tradable.pair_id}")
        print(f"   → Reason: {first_tradable.reason}")
    else:
        print(f"❌ No tradable symbols found!")

    # Summary
    print(f"\n{'='*80}")
    print("📋 SUMMARY")
    print(f"{'='*80}")

    tradable_count = sum(1 for s in results.values() if s.is_tradable)
    print(f"Tradable: {tradable_count}/{len(results)}")
    print()

    for symbol, status in results.items():
        emoji = "✅" if status.is_tradable else "❌"
        print(f"  {emoji} {symbol:8s} - {status.reason}")

    print()
    return tradable_count > 0


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
