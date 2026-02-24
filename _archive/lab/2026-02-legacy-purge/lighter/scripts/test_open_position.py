#!/usr/bin/env python3
"""
Lighter - Test opening a position (based on official examples)
"""
import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

# Lighter configuration (separate L1 and API keys!)
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

async def main():
    print("=" * 70)
    print("LIGHTER TESTNET - OPEN POSITION TEST")
    print("=" * 70)
    print(f"Wallet: {L1_ADDRESS}")
    print(f"Account Index: {ACCOUNT_INDEX}")
    print(f"API Key Index: {API_KEY_INDEX}\n")

    client = lighter.ApiClient()

    print("Step 1: Initialize SignerClient...")
    try:
        signer = lighter.SignerClient(
            url=BASE_URL,
            api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},  # Use correct index!
            account_index=ACCOUNT_INDEX
        )
        print("✅ SignerClient initialized\n")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        await client.close()
        return

    print("Step 2: Attempting to open position...")
    print("   Market: ETH/USDC (market_index=0)")
    print("   Side: LONG (is_ask=False)")
    print("   Size: 0.05 ETH")
    print("   Avg price: $1950")
    print("   Type: Market order\n")

    try:
        # Parameters: market_index, client_order_index, base_amount, avg_execution_price, is_ask
        # Amounts need to be scaled: ETH uses 10^6 decimals, price uses 10^6 decimals
        create_order, send_tx_resp, err = await signer.create_market_order(
            market_index=0,  # ETH/USDC is typically market_index 0
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=50000,  # 0.05 ETH * 10^6 = 50,000
            avg_execution_price=1950000000,  # $1950 * 10^6 = 1,950,000,000
            is_ask=False,  # False = BUY/LONG, True = SELL/SHORT
            reduce_only=False
        )

        if err:
            print(f"❌ ORDER FAILED: {err}")
        else:
            print("✅ ORDER SUBMITTED!")
            print(f"\nCreate Order: {create_order}")
            print(f"\nSend TX Response: {send_tx_resp}")

            if send_tx_resp and hasattr(send_tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {send_tx_resp.tx_hash}")

    except Exception as e:
        print(f"❌ ORDER FAILED: {e}")
        import traceback
        traceback.print_exc()

    await client.close()

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
