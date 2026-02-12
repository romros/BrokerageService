#!/usr/bin/env python3
"""
Test MARKET order gas consumption and fees.
Execute 3 market orders to get average gas cost.

Since LIMIT orders seem unsupported in testnet, we'll measure MARKET order costs.
"""

import asyncio
import os
import time
from decimal import Decimal
from dotenv import load_dotenv
from ostium_python_sdk import OstiumSDK, NetworkConfig
from eth_account import Account
from web3 import Web3

# Known OrderOpened event signature (WITHOUT 0x prefix, as .hex() returns without it)
ORDER_OPENED_TOPIC = 'fb4a26aa34682aa753cb2aa37ef1bc38eee1af6719db3a8cfe892c50406ea0e0'

def extract_pair_id_from_receipt(receipt):
    """Extract pair_id from OrderOpened event."""
    # Access logs directly (not via .get())
    logs = receipt.logs if hasattr(receipt, 'logs') else receipt.get('logs', [])

    for log in logs:
        # Access topics directly
        topics = log.topics if hasattr(log, 'topics') else log.get('topics', [])

        if len(topics) >= 4:
            # Topics are HexBytes, convert to hex string (no 0x prefix)
            event_sig = topics[0].hex()

            if event_sig.lower() == ORDER_OPENED_TOPIC.lower():
                # Extract pair_id from topic[3]
                pair_id = int(topics[3].hex(), 16)
                return pair_id

    return None

async def find_trade_index(sdk, pair_id, private_key, max_attempts=20):
    """Find trade_index by checking contract."""
    w3 = Web3(Web3.HTTPProvider('https://sepolia-rollup.arbitrum.io/rpc'))
    account = Account.from_key(private_key)
    trader = account.address

    trading_abi = [{
        "inputs": [
            {"name": "trader", "type": "address"},
            {"name": "pairId", "type": "uint16"},
            {"name": "index", "type": "uint8"}
        ],
        "name": "getOpenTrade",
        "outputs": [
            {"name": "openPrice", "type": "uint192"},
            {"name": "tp", "type": "uint192"},
            {"name": "sl", "type": "uint192"},
            {"name": "collateral", "type": "uint192"},
            {"name": "leverage", "type": "uint32"},
            {"name": "isLong", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    }]

    trading_contract = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"
    contract = w3.eth.contract(address=Web3.to_checksum_address(trading_contract), abi=trading_abi)

    for index in range(max_attempts):
        try:
            result = contract.functions.getOpenTrade(
                Web3.to_checksum_address(trader),
                pair_id,
                index
            ).call()

            if result[3] > 0:  # collateral > 0
                return index
        except Exception:
            continue
    return None

async def execute_trade(sdk, private_key, run_num):
    """Execute one complete trade cycle."""
    print(f"\n{'=' * 80}")
    print(f"RUN #{run_num}")
    print(f"{'=' * 80}\n")

    # Get price
    eur_price, _, _ = await sdk.price.get_price("EUR", "USD")
    print(f"EUR/USD: ${eur_price:.5f}\n")

    # Open
    trade_params = {
        'collateral': 5.0,
        'leverage': 10,
        'asset_type': 2,  # EUR
        'direction': True,  # LONG
        'order_type': 'MARKET'
    }

    print("Opening MARKET order...")
    start = time.time()
    receipt = sdk.ostium.perform_trade(trade_params, at_price=eur_price)
    open_time = time.time() - start

    tx_receipt = receipt.get('receipt', receipt)
    tx_hash = tx_receipt.get('transactionHash')
    if hasattr(tx_hash, 'hex'):
        tx_hash = tx_hash.hex()

    open_gas = tx_receipt.get('gasUsed', 0)

    print(f"✅ Opened")
    print(f"   TX: {tx_hash}")
    print(f"   Gas: {open_gas:,}")
    print(f"   Time: {open_time:.2f}s\n")

    # Extract pair_id
    pair_id = extract_pair_id_from_receipt(tx_receipt)
    if not pair_id:
        print("❌ Could not extract pair_id\n")
        return None

    # Wait for trade to be indexed
    await asyncio.sleep(3)

    # Find trade_index
    trade_index = await find_trade_index(sdk, pair_id, private_key, max_attempts=30)
    if trade_index is None:
        print("❌ Could not find trade_index\n")
        return None

    # Wait a bit more
    await asyncio.sleep(2)

    # Close
    print("Closing position...")
    current_price, _, _ = await sdk.price.get_price("EUR", "USD")

    start = time.time()
    close_receipt = sdk.ostium.close_trade(pair_id, trade_index, current_price)
    close_time = time.time() - start

    close_tx = close_receipt.get('transactionHash')
    if hasattr(close_tx, 'hex'):
        close_tx = close_tx.hex()

    close_gas = close_receipt.get('gasUsed', 0)

    print(f"✅ Closed")
    print(f"   TX: {close_tx}")
    print(f"   Gas: {close_gas:,}")
    print(f"   Time: {close_time:.2f}s\n")

    # Calculate cost
    total_gas = open_gas + close_gas
    gas_price_gwei = 0.1  # Typical Arbitrum
    cost_eth = (total_gas * gas_price_gwei) / 1e9
    cost_usd = cost_eth * 2300  # ETH ~$2300

    return {
        'run': run_num,
        'open_tx': tx_hash,
        'close_tx': close_tx,
        'open_gas': open_gas,
        'close_gas': close_gas,
        'total_gas': total_gas,
        'cost_usd': cost_usd,
        'open_time': open_time,
        'close_time': close_time
    }

async def main():
    print("\n" + "=" * 80)
    print("🧪 OSTIUM: MARKET ORDER FEES ANALYSIS")
    print("=" * 80)
    print()

    load_dotenv()
    private_key = os.getenv('PRIVATE_KEY')

    if not private_key:
        print("❌ PRIVATE_KEY not set")
        return

    try:
        # Init SDK
        config = NetworkConfig.testnet()
        sdk = OstiumSDK(config, private_key)
        account = Account.from_key(private_key)

        print(f"Wallet: {account.address}")
        print(f"Network: Arbitrum Sepolia\n")

        # Execute 3 trades
        results = []
        for i in range(1, 4):
            result = await execute_trade(sdk, private_key, i)
            if result:
                results.append(result)

            if i < 3:
                print("⏳ Waiting 5s before next trade...\n")
                await asyncio.sleep(5)

        # === ANALYSIS ===
        if not results:
            print("❌ No successful trades")
            return

        print("\n" + "=" * 80)
        print("📊 RESULTS SUMMARY")
        print("=" * 80)
        print()

        print(f"{'Run':<6} {'Open Gas':<12} {'Close Gas':<12} {'Total Gas':<12} {'Cost (USD)':<12}")
        print("-" * 80)

        for r in results:
            print(f"{r['run']:<6} {r['open_gas']:>11,} {r['close_gas']:>11,} {r['total_gas']:>11,} ${r['cost_usd']:>10.4f}")

        print()

        # Calculate averages
        avg_open = sum(r['open_gas'] for r in results) / len(results)
        avg_close = sum(r['close_gas'] for r in results) / len(results)
        avg_total = sum(r['total_gas'] for r in results) / len(results)
        avg_cost = sum(r['cost_usd'] for r in results) / len(results)

        print("AVERAGES:")
        print(f"  Open gas:  {avg_open:>,.0f}")
        print(f"  Close gas: {avg_close:>,.0f}")
        print(f"  Total gas: {avg_total:>,.0f}")
        print(f"  Cost:      ${avg_cost:.4f} per round-trip")
        print()

        print("COMPARISON:")
        print(f"  Ostium:  ${avg_cost:.4f}")
        print(f"  gTrade:  ~$10.00")
        print(f"  Savings: ${10 - avg_cost:.4f} ({((10 - avg_cost) / 10 * 100):.1f}% cheaper)")
        print()

        # JSON output
        import json
        print("=" * 80)
        print("JSON OUTPUT")
        print("=" * 80)
        print(json.dumps({
            'trades': results,
            'averages': {
                'open_gas': avg_open,
                'close_gas': avg_close,
                'total_gas': avg_total,
                'cost_usd': avg_cost
            }
        }, indent=2))

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
