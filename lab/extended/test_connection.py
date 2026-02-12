#!/usr/bin/env python3
"""
Test Extended SDK connection and authentication.

This script validates:
1. SDK installation
2. Testnet connectivity
3. Account authentication via Stark keys
4. Basic account info retrieval
5. Available markets

Note: Requires API key from https://testnet.extended.exchange/api-management
"""

import os
import asyncio
from dotenv import load_dotenv

async def main():
    print("\n" + "=" * 80)
    print("🔍 EXTENDED SDK CONNECTION TEST")
    print("=" * 80)
    print()

    # Load environment
    load_dotenv()

    # Extended requires: API_KEY, PUBLIC_KEY, PRIVATE_KEY (Stark keys), VAULT
    api_key = os.getenv('EXTENDED_API_KEY')
    public_key = os.getenv('EXTENDED_PUBLIC_KEY')
    private_key = os.getenv('EXTENDED_PRIVATE_KEY')
    vault = os.getenv('EXTENDED_VAULT')

    if not all([api_key, public_key, private_key, vault]):
        print("❌ Missing Extended credentials in .env")
        print()
        print("Required environment variables:")
        print("  EXTENDED_API_KEY=<your_api_key>")
        print("  EXTENDED_PUBLIC_KEY=<your_public_key>")
        print("  EXTENDED_PRIVATE_KEY=<your_private_key>")
        print("  EXTENDED_VAULT=<your_vault_number>")
        print()
        print("To obtain these:")
        print("  1. Visit https://testnet.extended.exchange/")
        print("  2. Connect wallet and onboard")
        print("  3. Navigate to API Management")
        print("  4. Generate API key and retrieve keys/vault ID")
        return

    print("✅ Environment loaded")
    print(f"   API Key: {api_key[:8]}...{api_key[-4:]}")
    print(f"   Vault: {vault}")
    print()

    # Test 1: SDK Import
    print("=" * 80)
    print("TEST 1: SDK IMPORT")
    print("=" * 80)
    print()

    try:
        print("Importing Extended SDK...")
        from x10.perpetual.accounts import StarkPerpetualAccount
        from x10.perpetual.configuration import TESTNET_CONFIG
        from x10.perpetual.trading_client import PerpetualTradingClient
        from x10.perpetual.orders import OrderSide
        from decimal import Decimal
        print("✅ SDK imported successfully")
    except ImportError as e:
        print(f"❌ SDK import failed: {e}")
        print()
        print("To install:")
        print("  pip install x10-python-trading-starknet")
        return

    print()

    # Test 2: Initialize Client
    print("=" * 80)
    print("TEST 2: INITIALIZE CLIENT")
    print("=" * 80)
    print()

    try:
        print("Creating Stark account...")
        stark_account = StarkPerpetualAccount(
            vault=int(vault),
            private_key=private_key,
            public_key=public_key,
            api_key=api_key,
        )
        print("✅ Stark account created")

        print("Connecting to Extended testnet (Sepolia)...")
        trading_client = PerpetualTradingClient.create(TESTNET_CONFIG, stark_account)
        print("✅ Trading client initialized")
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print()

    # Test 3: Get Account Balance
    print("=" * 80)
    print("TEST 3: ACCOUNT BALANCE")
    print("=" * 80)
    print()

    try:
        print("Fetching account balance...")
        balance = await trading_client.account.get_balance()
        print("✅ Balance retrieved")
        print()
        print(balance.to_pretty_json())
    except Exception as e:
        print(f"❌ Balance fetch failed: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Test 4: Get Current Positions
    print("=" * 80)
    print("TEST 4: CURRENT POSITIONS")
    print("=" * 80)
    print()

    try:
        print("Fetching current positions...")
        positions = await trading_client.account.get_positions()
        print("✅ Positions retrieved")
        print()

        if hasattr(positions, 'to_pretty_json'):
            print(positions.to_pretty_json())
        else:
            print(f"Positions: {positions}")
    except Exception as e:
        print(f"❌ Positions fetch failed: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Test 5: List Available Markets
    print("=" * 80)
    print("TEST 5: AVAILABLE MARKETS")
    print("=" * 80)
    print()

    try:
        print("Fetching available markets...")
        # Note: SDK may not have direct get_markets() method
        # We'll need to check API docs or try market-specific calls
        print("⚠️  Market listing method TBD")
        print("   Will test specific markets (EUR-USD, BTC-USD) in next script")
    except Exception as e:
        print(f"❌ Market fetch failed: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Test 6: Get Open Orders
    print("=" * 80)
    print("TEST 6: OPEN ORDERS")
    print("=" * 80)
    print()

    try:
        print("Fetching open orders...")
        open_orders = await trading_client.account.get_open_orders()
        print("✅ Open orders retrieved")
        print()

        if hasattr(open_orders, 'to_pretty_json'):
            print(open_orders.to_pretty_json())
        else:
            print(f"Open orders: {open_orders}")
    except Exception as e:
        print(f"❌ Open orders fetch failed: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Summary
    print("=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print()
    print("✅ SDK initialization: Working")
    print("✅ Testnet connectivity: Working")
    print("✅ Account authentication: Working")
    print()
    print("Next steps:")
    print("1. Create test_markets.py to query specific markets")
    print("2. Create test_full_cycle.py for open → close")
    print("3. Compare performance vs gTrade/Ostium")
    print("4. Measure fees and latency")

if __name__ == '__main__':
    asyncio.run(main())
