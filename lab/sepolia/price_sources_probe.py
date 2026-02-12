#!/usr/bin/env python3
"""
Lab Script: Price Sources Probe

Prova diferents fonts de preus per obtenir oracle price actual.

Usage:
    python lab/sepolia/price_sources_probe.py

Output:
    - Preus actuals de BTC/ETH/LINK
    - Font més fiable
    - Latència de cada font
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.price_feed_ws_client import GTradePriceFeedWSClient
from infrastructure.venues.gtrade.config import GTRADE_SYMBOL_TO_PAIR_ID
from loguru import logger


async def test_websocket_feed():
    """Test WebSocket price feed (primary source)"""
    print("\n" + "=" * 80)
    print("📡 Testing WebSocket Price Feed")
    print("=" * 80)
    print()

    # Use Sepolia WebSocket URL
    ws_url = "wss://feed-gtrade-arb.gainsnetwork.io/ws"

    print(f"Connecting to: {ws_url}")
    print()

    client = GTradePriceFeedWSClient(ws_url=ws_url)

    try:
        # Start client
        await client.start()

        # Wait for first ticks
        print("⏳ Waiting for price updates (10 seconds)...")
        await asyncio.sleep(10)

        # Get latest prices
        prices = await client.get_all_latest_prices()

        if not prices:
            print("❌ No prices received yet")
            return None

        print("✅ Prices received:")
        print()

        results = {}
        for symbol, price in prices.items():
            print(f"   {symbol}: ${price:,.2f}")
            results[symbol] = price

        # Save to artifacts
        output_path = Path(__file__).parent / "artifacts" / "last_run.json"
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump({
                "timestamp": datetime.utcnow().isoformat(),
                "source": "websocket",
                "url": ws_url,
                "prices": results,
            }, f, indent=2)

        print()
        print(f"✅ Saved to: {output_path}")

        return results

    except Exception as e:
        print(f"❌ WebSocket failed: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        await client.stop()


async def test_coingecko_fallback():
    """Test CoinGecko API as fallback"""
    print("\n" + "=" * 80)
    print("🦎 Testing CoinGecko API (Fallback)")
    print("=" * 80)
    print()

    try:
        import aiohttp

        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,chainlink",
            "vs_currencies": "usd"
        }

        async with aiohttp.ClientSession() as session:
            start = time.time()
            async with session.get(url, params=params) as response:
                latency = (time.time() - start) * 1000
                data = await response.json()

        print(f"✅ Response received (latency: {latency:.0f}ms)")
        print()

        results = {
            "BTCUSD": data.get("bitcoin", {}).get("usd"),
            "ETHUSD": data.get("ethereum", {}).get("usd"),
            "LINKUSD": data.get("chainlink", {}).get("usd"),
        }

        for symbol, price in results.items():
            if price:
                print(f"   {symbol}: ${price:,.2f}")

        return results

    except Exception as e:
        print(f"❌ CoinGecko failed: {e}")
        return None


async def main():
    print("\n" + "=" * 80)
    print("🔬 LAB: Price Sources Probe")
    print("=" * 80)
    print()

    # Test 1: WebSocket feed (primary)
    ws_prices = await test_websocket_feed()

    # Test 2: CoinGecko (fallback)
    cg_prices = await test_coingecko_fallback()

    # Compare
    print("\n" + "=" * 80)
    print("📊 Comparison")
    print("=" * 80)
    print()

    if ws_prices and cg_prices:
        for symbol in ["BTCUSD", "ETHUSD", "LINKUSD"]:
            ws_price = ws_prices.get(symbol)
            cg_price = cg_prices.get(symbol)

            if ws_price and cg_price:
                diff = abs(ws_price - cg_price)
                diff_pct = (diff / cg_price) * 100
                print(f"{symbol}:")
                print(f"  WebSocket: ${ws_price:,.2f}")
                print(f"  CoinGecko: ${cg_price:,.2f}")
                print(f"  Difference: ${diff:,.2f} ({diff_pct:.2f}%)")
                print()

    # Recommendation
    print("=" * 80)
    print("💡 Recommendation")
    print("=" * 80)
    print()

    if ws_prices:
        print("✅ Use WebSocket as primary source (GTradePriceFeedWSClient)")
        print("   - Real-time updates")
        print("   - Same feed as gTrade uses")
        print("   - Low latency")
        print()
        print("🔄 Fallback: CoinGecko API if WebSocket disconnected")
        return 0
    else:
        print("⚠️  WebSocket unavailable, use CoinGecko as temporary solution")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
