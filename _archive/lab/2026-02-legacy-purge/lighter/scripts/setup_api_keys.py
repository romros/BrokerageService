#!/usr/bin/env python3
"""
Lighter API Key Setup - Register new API keys for trading
Based on: https://github.com/elliottech/lighter-python/blob/main/examples/system_setup.py
"""
import os
import json
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ETH_PRIVATE_KEY = os.getenv("LIGHTER_L1_PRIVATE_KEY")  # L1 wallet private key (without 0x)
WALLET_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
NUM_API_KEYS = 1

async def main():
    print("=" * 70)
    print("LIGHTER - API KEY SETUP")
    print("=" * 70)
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Network: Testnet")
    print(f"Will register API key at index: {API_KEY_INDEX}\n")

    # Step 1: Get account_index from API (don't hardcode)
    print("Step 1: Finding account_index from API...")
    client = lighter.ApiClient()
    try:
        account_api = lighter.AccountApi(client)
        resp = await account_api.accounts_by_l1_address(l1_address=WALLET_ADDRESS)

        if not resp.sub_accounts or len(resp.sub_accounts) == 0:
            print("❌ No sub-accounts found")
            await client.close()
            return

        account_index = resp.sub_accounts[0].index
        print(f"✅ Found account_index: {account_index}\n")
    except Exception as e:
        print(f"⚠️  API error: {e}")
        # Fallback to env if API fails
        account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
        print(f"   Using fallback from env: {account_index}\n")
    finally:
        await client.close()

    # Step 2: Generate API key pair
    print("Step 2: Generating new API key pair...")
    private_keys = {}
    public_keys = {}

    for i in range(NUM_API_KEYS):
        idx = API_KEY_INDEX + i
        priv_key, pub_key, err = lighter.create_api_key()

        if err:
            print(f"❌ Failed to generate key #{idx}: {err}")
            return

        private_keys[idx] = priv_key
        public_keys[idx] = pub_key
        print(f"✅ Generated API key #{idx}")
        print(f"   Public:  {pub_key}")
        print(f"   Private: {priv_key[:20]}...{priv_key[-20:]}\n")

    # Step 3: Initialize SignerClient with new API keys
    print("Step 3: Initializing SignerClient...")
    try:
        signer = lighter.SignerClient(
            url=BASE_URL,
            account_index=account_index,
            api_private_keys=private_keys,
        )
        print("✅ SignerClient initialized\n")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        return

    # Step 4: Register each public key (requires L1 signature)
    print("Step 4: Registering API keys with Lighter...")
    print("   (This requires L1 wallet signature)\n")

    for idx, pub in public_keys.items():
        try:
            print(f"   Registering API key #{idx}...")
            result = await signer.change_api_key(
                eth_private_key=ETH_PRIVATE_KEY,
                new_pubkey=pub,
                api_key_index=idx
            )

            # Result might be just tx hash or (tx, err) tuple
            if isinstance(result, tuple):
                tx, err = result
            else:
                tx = result
                err = None

            if err:
                print(f"   ❌ Failed: {err}")
                continue

            print(f"   ✅ Registered API key #{idx}")
            print(f"      TX: {tx}\n")
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            import traceback
            traceback.print_exc()

    # Step 5: Verify setup with polling (wait for ZK-rollup confirmation)
    print("Step 5: Verifying setup (polling for confirmation)...")

    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"   Attempt {attempt}/{max_attempts}...")

            # Check if client is ready
            err = await signer.check_client()

            if err:
                if attempt < max_attempts:
                    print(f"   ⏳ Not ready yet: {err}")
                    await asyncio.sleep(2)
                    continue
                else:
                    print(f"   ❌ Verification failed after {max_attempts} attempts: {err}")
            else:
                print(f"   ✅ Setup verified successfully!\n")
                break

        except Exception as e:
            if attempt < max_attempts:
                print(f"   ⏳ Exception (will retry): {e}")
                await asyncio.sleep(2)
            else:
                print(f"   ❌ Verification exception after {max_attempts} attempts: {e}")

    # Step 6: Save configuration
    config_file = "api_key_config.json"
    config = {
        "baseUrl": BASE_URL,
        "accountIndex": account_index,
        "privateKeys": {str(k): v for k, v in private_keys.items()}
    }

    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"💾 Configuration saved to: {config_file}")
    print("\n📝 Update your .env file with:")
    print(f"LIGHTER_ACCOUNT_INDEX={account_index}")
    print(f"LIGHTER_API_KEY_INDEX={API_KEY_INDEX}")
    print(f"LIGHTER_API_PRIVATE_KEY={private_keys[API_KEY_INDEX]}")

    print("\n" + "=" * 70)
    print("SETUP COMPLETE")
    print("=" * 70)
    print("\n✅ You can now run test_open_position.py to create orders")

if __name__ == "__main__":
    asyncio.run(main())
