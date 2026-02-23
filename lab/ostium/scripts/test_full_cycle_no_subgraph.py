#!/usr/bin/env python3
"""
Ostium Full Cycle WITHOUT Subgraph
Uses transaction receipt events to get trade info, then closes with SDK.

Flow:
1. Open position with SDK → get receipt
2. Parse receipt events to extract pair_id and trade_index
3. Close position with SDK using those values
4. NO subgraph queries needed!
"""

import asyncio
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv
from ostium_python_sdk import OstiumSDK, NetworkConfig
from eth_account import Account
from web3 import Web3

def _load_trading_storage_abi():
    """Load getOpenTrade ABI from lab/ostium/abi (Trade struct from IOstiumTradingStorage)."""
    abi_path = Path(__file__).resolve().parent.parent / "abi" / "tradingStorage_getOpenTrade.json"
    if abi_path.exists():
        with open(abi_path, encoding="utf-8") as f:
            return json.load(f)
    # Fallback: minimal ABI with correct Trade struct order
    return [{
        "inputs": [
            {"name": "_trader", "type": "address"},
            {"name": "_pairIndex", "type": "uint16"},
            {"name": "_index", "type": "uint8"}
        ],
        "name": "getOpenTrade",
        "outputs": [{
            "type": "tuple",
            "components": [
                {"name": "collateral", "type": "uint256"},
                {"name": "openPrice", "type": "uint192"},
                {"name": "tp", "type": "uint192"},
                {"name": "sl", "type": "uint192"},
                {"name": "trader", "type": "address"},
                {"name": "leverage", "type": "uint32"},
                {"name": "pairIndex", "type": "uint16"},
                {"name": "index", "type": "uint8"},
                {"name": "buy", "type": "bool"}
            ]
        }],
        "stateMutability": "view",
        "type": "function"
    }]

# OrderOpened event signature
ORDER_OPENED_TOPIC = Web3.keccak(text='OrderOpened(uint256,address,uint8)').hex()

def extract_trade_info_from_receipt(receipt):
    """
    Extract pair_id and trade_index from OrderOpened event in receipt.

    OrderOpened event format:
    - topic[0]: event signature
    - topic[1]: order_id (indexed)
    - topic[2]: trader (indexed)
    - topic[3]: pair_id (indexed)
    - data: additional non-indexed params
    """
    for log in receipt.get('logs', []):
        topics = log.get('topics', [])

        if len(topics) >= 4:
            # Check if this is OrderOpened event
            event_sig = topics[0].hex() if hasattr(topics[0], 'hex') else topics[0]

            if event_sig.lower() == ORDER_OPENED_TOPIC.lower():
                # Extract pair_id from topic[3]
                pair_id_hex = topics[3].hex() if hasattr(topics[3], 'hex') else topics[3]
                pair_id = int(pair_id_hex, 16)

                print(f"  ✅ Found OrderOpened event")
                print(f"     Pair ID: {pair_id}")

                # For trade_index, we need to check contract state
                # But we know from previous test: first trade in pair = index 0
                # For production: brute force 0-255 or use getOpenTrade

                return pair_id, None  # trade_index unknown from event

    return None, None

async def find_trade_index(sdk, pair_id, private_key, max_attempts=10):
    """
    Find trade_index by checking recent indexes (0-9).
    Most recent trades will have low indexes.
    Uses tradingStorage contract (getOpenTrade does not revert there).
    """
    max_attempts = int(os.getenv("PAIR_ID_MAX_ATTEMPTS", str(max_attempts)))
    from web3 import Web3
    from eth_account import Account
    from ostium_python_sdk import NetworkConfig

    rpc_url = os.getenv("RPC_URL", "https://sepolia-rollup.arbitrum.io/rpc")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = Account.from_key(private_key)
    trader = account.address

    trading_storage_abi = _load_trading_storage_abi()
    cfg = NetworkConfig.testnet()
    default_storage = cfg.contracts["tradingStorage"]
    trading_storage_contract = os.getenv("TRADING_STORAGE_CONTRACT", default_storage)
    contract = w3.eth.contract(address=Web3.to_checksum_address(trading_storage_contract), abi=trading_storage_abi)

    print(f"  getOpenTrade via tradingStorage={trading_storage_contract} rpc={rpc_url[:60]}..." if len(rpc_url) > 60 else f"  getOpenTrade via tradingStorage={trading_storage_contract} rpc={rpc_url}")
    print(f"  Searching for trade_index (checking 0-{max_attempts-1})...")

    # Trade struct: (collateral, openPrice, tp, sl, trader, leverage, pairIndex, index, buy)
    for index in range(max_attempts):
        try:
            result = contract.functions.getOpenTrade(
                Web3.to_checksum_address(trader),
                pair_id,
                index
            ).call()
            collateral = result[0]
            open_price = result[1]
            leverage = result[5]
            is_open = (open_price > 0 and collateral > 0)
            if is_open:
                print(f"  ✅ Found trade at index {index} openPrice={open_price} collateral={collateral} leverage={leverage}")
                return index
        except Exception:
            continue

    return None

async def main():
    print("\n" + "=" * 80)
    print("🧪 OSTIUM FULL CYCLE - NO SUBGRAPH")
    print("=" * 80)
    print()

    load_dotenv()
    private_key = os.getenv('PRIVATE_KEY')

    if not private_key:
        print("❌ PRIVATE_KEY not set")
        return

    try:
        # Init SDK
        print("Initializing Ostium SDK...")
        config = NetworkConfig.testnet()
        sdk = OstiumSDK(config, private_key)

        account = Account.from_key(private_key)
        address = account.address

        print(f"✅ Connected to Arbitrum Sepolia")
        print(f"Wallet: {address}")
        print()

        # Get current price
        print("=" * 80)
        print("STEP 1: GET PRICE")
        print("=" * 80)
        print()

        eur_price, _, _ = await sdk.price.get_price("EUR", "USD")
        print(f"EUR/USD: ${eur_price:.5f}")
        print()

        # Open position
        print("=" * 80)
        print("STEP 2: OPEN POSITION")
        print("=" * 80)
        print()

        collateral = 5.0
        leverage = 10
        is_long = True

        print(f"Opening EUR/USD {'LONG' if is_long else 'SHORT'}:")
        print(f"  Collateral: {collateral} USDC @ {leverage}x")
        print()

        start_open = time.time()

        trade_params = {
            'collateral': collateral,
            'leverage': leverage,
            'asset_type': 2,  # EUR
            'direction': is_long,
            'order_type': 'MARKET'
        }

        receipt = sdk.ostium.perform_trade(trade_params, at_price=eur_price)
        elapsed_open = time.time() - start_open

        # Extract receipt
        tx_receipt = receipt.get('receipt', receipt)
        tx_hash = tx_receipt.get('transactionHash')
        if hasattr(tx_hash, 'hex'):
            tx_hash = tx_hash.hex()

        print(f"✅ Position opened!")
        print(f"   TX: {tx_hash}")
        print(f"   Time: {elapsed_open:.2f}s")
        print()

        # Extract trade info from receipt
        print("=" * 80)
        print("STEP 3: EXTRACT TRADE INFO FROM RECEIPT")
        print("=" * 80)
        print()

        pair_id, _ = extract_trade_info_from_receipt(tx_receipt)

        if not pair_id:
            pair_id = int(os.getenv("PAIR_ID", "0"))
            print(f"⚠ OrderOpened event not found → fallback PAIR_ID={pair_id}")
        print()

        # Find trade_index
        print("=" * 80)
        print("STEP 4: FIND TRADE INDEX")
        print("=" * 80)
        print()

        trade_index = await find_trade_index(sdk, pair_id, private_key)

        if trade_index is None:
            print("❌ Could not find trade_index")
            return

        print()

        # Close position
        print("=" * 80)
        print("STEP 5: CLOSE POSITION WITH SDK")
        print("=" * 80)
        print()

        current_price, _, _ = await sdk.price.get_price("EUR", "USD")
        print(f"Current price: ${current_price:.5f}")
        print(f"Closing with SDK: close_trade(pair_id={pair_id}, trade_index={trade_index}, price={current_price})")
        print()

        start_close = time.time()
        close_receipt = sdk.ostium.close_trade(pair_id, trade_index, current_price)
        elapsed_close = time.time() - start_close

        close_tx_hash = close_receipt.get('transactionHash')
        if hasattr(close_tx_hash, 'hex'):
            close_tx_hash = close_tx_hash.hex()

        print(f"✅ Position closed!")
        print(f"   TX: {close_tx_hash}")
        print(f"   Time: {elapsed_close:.2f}s")
        print()

        # Summary
        print("=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print()
        print("✅ Full cycle completed WITHOUT subgraph:")
        print(f"   • Open: {elapsed_open:.2f}s")
        print(f"   • Extract info: from TX receipt")
        print(f"   • Find index: contract call")
        print(f"   • Close: {elapsed_close:.2f}s (using SDK)")
        print()
        print("🎯 This approach is ROBUST:")
        print("   ✅ No subgraph dependency")
        print("   ✅ Uses SDK (clean code)")
        print("   ✅ Extracts info from blockchain directly")
        print()
        print("Open TX:  https://sepolia.arbiscan.io/tx/" + tx_hash)
        print("Close TX: https://sepolia.arbiscan.io/tx/" + close_tx_hash)

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
