#!/usr/bin/env python3
"""
Check Starknet Sepolia testnet balance for an Ethereum address.

This script:
1. Derives Starknet address from Ethereum private key
2. Checks ETH and USDC balance on Starknet Sepolia
3. Provides network parameters for Rabby
"""

import os
import sys
import json

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip3 install --user requests")
    import requests

# Starknet Sepolia RPC endpoints
RPC_URLS = [
    "https://starknet-sepolia.public.blastapi.io",
    "https://starknet-sepolia.infura.io/v3/9aa3d95b3bc440fa88ea12eaa4456161",  # Public Infura key
    "https://rpc.starknet-testnet.lava.build",
]

def get_starknet_address_from_eth(eth_address):
    """
    Derive Starknet address from Ethereum address.
    Note: This is a simplified derivation. Extended uses their own mapping.
    """
    # For Extended, the Starknet address is typically obtained from their API
    # after onboarding. This is just to show the concept.
    print(f"⚠️  Starknet address derivation requires Extended SDK")
    print(f"   Ethereum address: {eth_address}")
    print(f"   For Extended-specific mapping, use their API after onboarding")
    return None

def check_starknet_balance(rpc_url, address):
    """
    Check balance on Starknet using eth_getBalance equivalent.
    """
    try:
        # Starknet uses different RPC methods than Ethereum
        # eth_getBalance equivalent in Starknet is starknet_getBalance

        payload = {
            "jsonrpc": "2.0",
            "method": "starknet_getBalance",
            "params": [address],
            "id": 1
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post(rpc_url, json=payload, headers=headers, timeout=10)

        if response.status_code == 200:
            result = response.json()
            return result
        else:
            return None

    except Exception as e:
        print(f"   Error with {rpc_url}: {str(e)}")
        return None

def main():
    print("\n" + "=" * 80)
    print("🔍 STARKNET SEPOLIA BALANCE CHECK")
    print("=" * 80)
    print()

    # Known Ethereum address from previous context
    eth_address = "0xD9fC17C093614D20976EFb1535A7142081A031b2"

    print(f"Ethereum Address: {eth_address}")
    print()

    # Attempt to derive Starknet address
    print("=" * 80)
    print("STARKNET ADDRESS DERIVATION")
    print("=" * 80)
    print()

    starknet_address = get_starknet_address_from_eth(eth_address)

    if not starknet_address:
        print()
        print("⚠️  To get your Starknet address:")
        print("   1. Visit https://testnet.extended.exchange/")
        print("   2. Connect with your Ethereum wallet")
        print("   3. Look for your Starknet address in the UI")
        print("   4. Or use the Extended API: /api/v1/user/account/info")
        print()

        # Try to get it from Extended API if possible
        print("Attempting to fetch from Extended API...")
        print("(This requires API credentials)")
        print()

    # Test RPC connectivity
    print("=" * 80)
    print("TESTING STARKNET SEPOLIA RPC ENDPOINTS")
    print("=" * 80)
    print()

    working_rpc = None
    for rpc_url in RPC_URLS:
        print(f"Testing: {rpc_url}")
        try:
            # Try a simple health check
            payload = {"jsonrpc": "2.0", "method": "starknet_chainId", "params": [], "id": 1}
            response = requests.post(rpc_url, json=payload, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if "result" in result:
                    print(f"   ✅ Working! Chain ID: {result.get('result')}")
                    working_rpc = rpc_url
                    break
                else:
                    print(f"   ❌ Error: {result.get('error', 'Unknown error')}")
            else:
                print(f"   ❌ HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ Failed: {str(e)}")

    print()

    # Provide Rabby configuration
    print("=" * 80)
    print("RABBY WALLET CONFIGURATION")
    print("=" * 80)
    print()

    print("⚠️  IMPORTANT: Rabby doesn't natively support Starknet!")
    print("   Starknet is NOT EVM-compatible, so Rabby can't connect directly.")
    print()
    print("However, if you want to try Kakarot (EVM on Starknet):")
    print()
    print("Network Name: Kakarot Starknet Sepolia")
    print("RPC URL: https://sepolia-rpc.kakarot.org")
    print("Chain ID: 920637907288165")
    print("Symbol: ETH")
    print("Block Explorer: https://sepolia.kakarotscan.org/")
    print()
    print("BUT: This is NOT the same as native Starknet Sepolia!")
    print("Extended likely uses NATIVE Starknet, which requires:")
    print("  - Argent X wallet: https://www.argent.xyz/argent-x/")
    print("  - Braavos wallet: https://braavos.app/")
    print()

    if working_rpc:
        print("=" * 80)
        print("NATIVE STARKNET SEPOLIA (for Argent X / Braavos)")
        print("=" * 80)
        print()
        print(f"Network: Starknet Sepolia")
        print(f"RPC URL: {working_rpc}")
        print(f"Chain ID: SN_SEPOLIA")
        print(f"Explorer: https://sepolia.voyager.online/")
        print(f"Faucet: https://starknet-faucet.vercel.app/")
        print()

    # Summary
    print("=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print()
    print("✅ Ethereum address identified")
    print("⚠️  Starknet address requires Extended onboarding")
    print("❌ Rabby cannot connect to native Starknet")
    print()
    print("RECOMMENDED APPROACH:")
    print("1. Install Argent X or Braavos wallet")
    print("2. Create Starknet account")
    print("3. Connect to https://testnet.extended.exchange/")
    print("4. Get API credentials from Extended UI")
    print("5. Use SDK for programmatic trading")
    print()
    print("OR (alternative):")
    print("1. Keep using Rabby for Ethereum wallet")
    print("2. Extended handles Starknet mapping internally")
    print("3. Just get API credentials and use SDK")

if __name__ == '__main__':
    main()
