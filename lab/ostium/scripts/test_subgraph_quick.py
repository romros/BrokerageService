#!/usr/bin/env python3
"""
Quick test to check if Ostium testnet subgraph is working.
Tests both testnet and mainnet subgraph response times.
"""

import time
import requests

TESTNET_SUBGRAPH = "https://api.studio.thegraph.com/query/53927/ostium-arbitrum-sepolia/v0.1.0"
MAINNET_SUBGRAPH = "https://api.studio.thegraph.com/query/53927/ostium-arbitrum-one/v0.1.0"

# Test wallet address (replace with actual if needed)
TEST_ADDRESS = "0xD9fC17C093614D20976EFb1535A7142081A031b2"

def test_subgraph(name, url, address):
    """Test subgraph response time and functionality"""
    print(f"\n{'='*80}")
    print(f"🔍 TESTING {name}")
    print(f"{'='*80}\n")

    query = """
    query GetOpenTrades($trader: String!) {
      openTrades(where: { trader: $trader }) {
        id
        pairId
        index
        trader
        isLong
        collateral
        leverage
        openPrice
        tp
        sl
      }
    }
    """

    variables = {"trader": address.lower()}

    print(f"Subgraph URL: {url}")
    print(f"Querying for address: {address}")
    print()

    try:
        start = time.time()

        response = requests.post(
            url,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        elapsed = time.time() - start

        if response.status_code == 200:
            data = response.json()

            if "errors" in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                return False

            trades = data.get("data", {}).get("openTrades", [])

            print(f"✅ Query successful!")
            print(f"⏱️  Response time: {elapsed:.2f}s")
            print(f"📊 Open trades found: {len(trades)}")

            if trades:
                print(f"\nTrades:")
                for i, trade in enumerate(trades[:3], 1):  # Show max 3
                    print(f"  {i}. Pair {trade['pairId']}, Index {trade['index']}")
                    print(f"     {'LONG' if trade['isLong'] else 'SHORT'} | "
                          f"{trade['collateral']} USDC @ {trade['leverage']}x")

            # Evaluate performance
            print()
            if elapsed < 3:
                print("🎯 EXCELLENT: Very fast response (<3s)")
                return True
            elif elapsed < 10:
                print("✅ GOOD: Acceptable response (3-10s)")
                return True
            elif elapsed < 30:
                print("⚠️  SLOW: Degraded performance (10-30s)")
                return True
            else:
                print("❌ TIMEOUT: Too slow (>30s)")
                return False

        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False

    except requests.Timeout:
        print(f"❌ Timeout after 30s - subgraph not responding")
        return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

def main():
    print("\n" + "="*80)
    print("🧪 OSTIUM SUBGRAPH HEALTH CHECK")
    print("="*80)

    # Test testnet
    testnet_ok = test_subgraph("TESTNET (Arbitrum Sepolia)", TESTNET_SUBGRAPH, TEST_ADDRESS)

    time.sleep(2)  # Brief pause between tests

    # Test mainnet
    mainnet_ok = test_subgraph("MAINNET (Arbitrum One)", MAINNET_SUBGRAPH, TEST_ADDRESS)

    # Summary
    print("\n" + "="*80)
    print("📊 SUMMARY")
    print("="*80)
    print()
    print(f"Testnet: {'✅ WORKING' if testnet_ok else '❌ NOT WORKING'}")
    print(f"Mainnet: {'✅ WORKING' if mainnet_ok else '❌ NOT WORKING'}")
    print()

    if testnet_ok and mainnet_ok:
        print("🎉 Both subgraphs are operational!")
        print("   Ostium can be used for programmatic trading.")
    elif mainnet_ok and not testnet_ok:
        print("⚠️  Only mainnet is working.")
        print("   Testnet still broken - cannot validate without real funds.")
    elif testnet_ok and not mainnet_ok:
        print("⚠️  Only testnet is working (unusual).")
        print("   Check mainnet status before production use.")
    else:
        print("❌ Both subgraphs failing.")
        print("   Ostium not viable for programmatic trading at this time.")

if __name__ == '__main__':
    main()
