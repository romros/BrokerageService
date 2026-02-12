#!/usr/bin/env python3
"""
Lab Script: WebSocket Price Feed Monitor

Connecta al price feed de gTrade i mostra preus en temps real.
Útil per validar scaling, latència, i disponibilitat de dades.

Usage:
    python lab/gtrade/ws_price_probe.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.price_feed_ws_client import GTradePriceFeedWSClient
from infrastructure.venues.gtrade.config import GTRADE_SUPPORTED_SYMBOLS
from loguru import logger


async def main():
    print("\n" + "=" * 80)
    print("📡 WebSocket Price Feed Monitor")
    print("=" * 80)
    print()

    # WebSocket URL
    ws_url = "wss://feed-gtrade-arb.gainsnetwork.io/ws"

    print(f"Connecting to: {ws_url}")
    print(f"Symbols: {', '.join(GTRADE_SUPPORTED_SYMBOLS)}")
    print()

    client = GTradePriceFeedWSClient(ws_url=ws_url)

    try:
        # Start client
        await client.start()
        print("✅ Connected")
        print()

        print("⏳ Waiting for price updates...")
        print("   (Press Ctrl+C to stop)")
        print()

        # Monitor prices
        last_prices = {}

        while True:
            await asyncio.sleep(2)

            # Get all latest prices
            prices = await client.get_all_latest_prices()

            if not prices:
                print("⚠️  No prices received yet...")
                continue

            # Check if any price changed
            changed = any(
                prices.get(symbol) != last_prices.get(symbol)
                for symbol in GTRADE_SUPPORTED_SYMBOLS
            )

            if not changed and last_prices:
                # No updates, just show timestamp
                print(f"\r[{datetime.utcnow().strftime('%H:%M:%S')}] Waiting for updates...", end="", flush=True)
                continue

            # Clear line and show updates
            print("\r" + " " * 80 + "\r", end="")
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Price Update:")

            for symbol in GTRADE_SUPPORTED_SYMBOLS:
                price = prices.get(symbol)
                if price:
                    # Show price and scaled value (1e10)
                    scaled = int(price * 1e10)
                    print(f"   {symbol:8} ${price:>10,.2f}  (scaled: {scaled})")

                    last_prices[symbol] = price
                else:
                    print(f"   {symbol:8} [no data]")

            print()

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user")
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await client.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
