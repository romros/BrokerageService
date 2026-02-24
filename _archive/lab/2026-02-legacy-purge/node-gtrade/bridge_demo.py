#!/usr/bin/env python3
"""
DEMO: Python bridge per cridar Node.js CLI

Mostra com Python pot cridar el Node.js script i parsejar JSON.
"""

import json
import subprocess
from pathlib import Path

NODE_DIR = Path(__file__).parent


def get_quote(pair: str, is_long: bool, collateral: float, leverage: int):
    """Call Node.js CLI and parse JSON response"""

    cmd = [
        "node",
        str(NODE_DIR / "simpleQuote.js"),
        pair,
        "long" if is_long else "short",
        str(collateral),
        str(leverage)
    ]

    print(f"🔧 Calling Node.js CLI...")
    print(f"   Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=NODE_DIR
    )

    if result.returncode != 0:
        print(f"❌ Node.js CLI failed!")
        print(f"   stderr: {result.stderr}")
        return None

    # Parse JSON from stdout
    data = json.loads(result.stdout)

    # Show stderr (logs)
    if result.stderr:
        print("📋 Node.js logs:")
        for line in result.stderr.strip().split('\n'):
            print(f"   {line}")
        print()

    return data


def main():
    print("=" * 80)
    print("🧪 DEMO: Node.js + Python Bridge")
    print("=" * 80)
    print()

    # Test: Get quote for BTC LONG
    quote = get_quote(
        pair="BTCUSD",
        is_long=True,
        collateral=150.0,
        leverage=10
    )

    if not quote:
        print("❌ Failed to get quote")
        return 1

    if not quote.get('success'):
        print(f"❌ Quote generation failed: {quote.get('error')}")
        return 1

    print("✅ Quote received from Node.js!")
    print()
    print("📊 Quote details:")
    print(f"   Pair: {quote['config']['pair']}")
    print(f"   Direction: {quote['config']['direction']}")
    print(f"   Collateral: ${quote['config']['collateral']} USDC")
    print(f"   Leverage: {quote['config']['leverage']}x")
    print()
    print(f"   Oracle Price: ${quote['quote']['oraclePrice']:,.2f}")
    print(f"   Open Price: ${quote['quote']['openPrice']:,.2f}")
    print(f"   Max Slippage: {quote['quote']['maxSlippage']} ({quote['quote']['maxSlippage'] - 1:.0%})")
    print(f"   Position Size: ${quote['quote']['positionSize']:,.0f}")
    print()
    print("🔧 Scaled parameters:")
    print(f"   openPrice: {quote['parameters']['openPriceScaled']}")
    print(f"   maxSlippage: {quote['parameters']['maxSlippageScaled']}")
    print(f"   leverage: {quote['parameters']['leverageScaled']}")
    print(f"   collateral: {quote['parameters']['collateralScaled']}")
    print()
    print("📝 Transaction:")
    print(f"   to: {quote['transaction']['to']}")
    print(f"   data: {quote['transaction']['data'][:66]}...")
    print()
    print("=" * 80)
    print("✅ DEMO SUCCESS: Node.js CLI → Python bridge works!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
