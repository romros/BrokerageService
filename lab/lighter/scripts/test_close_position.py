#!/usr/bin/env python3
"""
Lighter - Monitor and close positions
"""
import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

# Lighter configuration
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

async def main():
    print("=" * 70)
    print("LIGHTER TESTNET - MONITOR & CLOSE POSITION")
    print("=" * 70)
    print(f"Wallet: {L1_ADDRESS}")
    print(f"Account Index: {ACCOUNT_INDEX}\n")

    client = lighter.ApiClient()

    # Step 1: Check current positions
    print("Step 1: Checking open positions...")
    try:
        account_api = lighter.AccountApi(client)
        account = await account_api.account(by="index", value=str(ACCOUNT_INDEX))

        print(f"✅ Account data retrieved")
        print(f"\nAccount Info:")
        print(f"   {account}\n")

        # Try to access positions
        if hasattr(account, 'positions'):
            positions = account.positions
            if positions:
                print(f"📊 Found {len(positions)} open position(s):")
                for i, pos in enumerate(positions):
                    print(f"\n   Position {i+1}:")
                    print(f"      {pos}")
            else:
                print("📊 No open positions found")
        else:
            print("⚠️  Position data not available in account object")

    except Exception as e:
        print(f"❌ Error fetching account: {e}")
        import traceback
        traceback.print_exc()

    # Step 2: Initialize SignerClient for closing
    print("\nStep 2: Initialize SignerClient...")
    try:
        signer = lighter.SignerClient(
            url=BASE_URL,
            api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
            account_index=ACCOUNT_INDEX
        )
        print("✅ SignerClient initialized\n")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        await client.close()
        return

    # Step 3: Close position (opposite of LONG = SHORT/sell)
    print("Step 3: Attempting to close position...")
    print("   Market: ETH/USDC (market_index=0)")
    print("   Side: SHORT/SELL (is_ask=True) - to close LONG")
    print("   Size: 0.05 ETH")
    print("   Type: Market order\n")

    try:
        # Close the LONG position by selling (is_ask=True)
        create_order, send_tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=50000,  # Same size as opening: 0.05 ETH * 10^6
            avg_execution_price=1950000000,  # $1950 * 10^6
            is_ask=True,  # True = SELL/SHORT (closes LONG position)
            reduce_only=True  # Only reduce position, don't flip to SHORT
        )

        if err:
            print(f"❌ CLOSE ORDER FAILED: {err}")
        else:
            print("✅ CLOSE ORDER SUBMITTED!")
            print(f"\nCreate Order: {create_order}")
            print(f"\nSend TX Response: {send_tx_resp}")

            if send_tx_resp and hasattr(send_tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {send_tx_resp.tx_hash}")

    except Exception as e:
        print(f"❌ CLOSE ORDER FAILED: {e}")
        import traceback
        traceback.print_exc()

    # Step 4: Wait a bit and check positions again
    print("\nStep 4: Waiting 3 seconds for settlement...")
    await asyncio.sleep(3)

    print("Step 5: Verifying position closed...")
    try:
        account = await account_api.account(by="index", value=str(ACCOUNT_INDEX))

        if hasattr(account, 'positions'):
            positions = account.positions
            if positions:
                print(f"📊 Still {len(positions)} position(s) open:")
                for i, pos in enumerate(positions):
                    print(f"   Position {i+1}: {pos}")
            else:
                print("✅ All positions closed successfully!")
        else:
            print("⚠️  Position data not available")

    except Exception as e:
        print(f"⚠️  Error verifying: {e}")

    await client.close()

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
