#!/usr/bin/env python3
"""
Ostium Testnet - Optimitzat amb MULTICALL
Compara brute force vs multicall per trobar trade_index
"""

import asyncio
import os
import time
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

# Minimal ABI per getOpenTrade
TRADING_ABI = [{
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

# Multicall3 ABI (deployed on most chains)
MULTICALL3_ABI = [{
    "inputs": [
        {"name": "requireSuccess", "type": "bool"},
        {
            "components": [
                {"name": "target", "type": "address"},
                {"name": "callData", "type": "bytes"}
            ],
            "name": "calls",
            "type": "tuple[]"
        }
    ],
    "name": "tryAggregate",
    "outputs": [
        {
            "components": [
                {"name": "success", "type": "bool"},
                {"name": "returnData", "type": "bytes"}
            ],
            "name": "returnData",
            "type": "tuple[]"
        }
    ],
    "stateMutability": "view",
    "type": "function"
}]

# Contract addresses
TRADING_CONTRACT = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"  # Testnet
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"  # Universal

def find_trades_brute_force(w3, trading_contract, trader, pair_id, max_attempts=10):
    """Mètode original: 1 call per index"""
    print(f"\n{'='*80}")
    print("🐌 MÈTODE 1: BRUTE FORCE (sequencial)")
    print(f"{'='*80}\n")
    
    start = time.time()
    found_indexes = []
    
    for index in range(max_attempts):
        try:
            result = trading_contract.functions.getOpenTrade(
                Web3.to_checksum_address(trader),
                pair_id,
                index
            ).call()
            
            collateral = result[3]  # index 3 = collateral
            
            if collateral > 0:
                found_indexes.append(index)
                print(f"  ✅ Index {index}: collateral={collateral}")
        except Exception as e:
            continue
    
    elapsed = time.time() - start
    
    print(f"\n  📊 Resultats:")
    print(f"     Trades trobats: {len(found_indexes)}")
    print(f"     Indexes: {found_indexes}")
    print(f"     RPC calls: {max_attempts}")
    print(f"     Temps: {elapsed:.3f}s")
    
    return found_indexes, elapsed

def find_trades_multicall(w3, trading_contract, multicall_contract, trader, pair_id, max_attempts=10):
    """Mètode optimitzat: 1 multicall amb tots els indexes"""
    print(f"\n{'='*80}")
    print("⚡ MÈTODE 2: MULTICALL (batch)")
    print(f"{'='*80}\n")
    
    start = time.time()
    
    # Preparar calls per multicall
    calls = []
    for index in range(max_attempts):
        # Encode getOpenTrade call
        call_data = trading_contract.functions.getOpenTrade(
            Web3.to_checksum_address(trader),
            pair_id,
            index
        )._encode_transaction_data()
        calls.append((TRADING_CONTRACT, call_data))
    
    # Execute multicall (requireSuccess=False to allow individual failures)
    try:
        results = multicall_contract.functions.tryAggregate(False, calls).call()
        
        # Decode results
        found_indexes = []
        for index, (success, data) in enumerate(results):
            if not success or len(data) == 0:
                continue
                
            try:
                # Decode trade struct
                # Returns: (openPrice, tp, sl, collateral, leverage, isLong)
                decoded = w3.codec.decode(['uint192', 'uint192', 'uint192', 'uint192', 'uint32', 'bool'], data)
                collateral = decoded[3]
                
                if collateral > 0:
                    found_indexes.append(index)
                    print(f"  ✅ Index {index}: collateral={collateral}")
            except Exception:
                continue
        
        elapsed = time.time() - start
        
        print(f"\n  📊 Resultats:")
        print(f"     Trades trobats: {len(found_indexes)}")
        print(f"     Indexes: {found_indexes}")
        print(f"     RPC calls: 1 (multicall)")
        print(f"     Temps: {elapsed:.3f}s")
        
        return found_indexes, elapsed
        
    except Exception as e:
        print(f"  ❌ Error multicall: {e}")
        return [], 0

def main():
    print("\n" + "="*80)
    print("🧪 OSTIUM TESTNET — MULTICALL OPTIMIZATION TEST")
    print("="*80 + "\n")
    
    # Load env
    load_dotenv()
    private_key = os.getenv('PRIVATE_KEY')
    rpc_url = os.getenv('RPC_URL', 'https://sepolia-rollup.arbitrum.io/rpc')
    
    if not private_key:
        print("❌ PRIVATE_KEY not set in .env")
        return
    
    # Setup
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = Account.from_key(private_key)
    trader = account.address
    
    print(f"Wallet: {trader}")
    print(f"RPC: {rpc_url}")
    print(f"Testing pair_id: 0 (EURUSD)")
    print()
    
    # Create contract instances
    trading_contract = w3.eth.contract(
        address=Web3.to_checksum_address(TRADING_CONTRACT),
        abi=TRADING_ABI
    )
    
    multicall_contract = w3.eth.contract(
        address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
        abi=MULTICALL3_ABI
    )
    
    pair_id = 0  # EURUSD
    max_trades = 10  # maxTradesPerPair
    
    # Test 1: Brute force
    indexes_bf, time_bf = find_trades_brute_force(
        w3, trading_contract, trader, pair_id, max_trades
    )
    
    # Test 2: Multicall
    indexes_mc, time_mc = find_trades_multicall(
        w3, trading_contract, multicall_contract, trader, pair_id, max_trades
    )
    
    # Comparison
    print(f"\n{'='*80}")
    print("📊 COMPARATIVA FINAL")
    print(f"{'='*80}\n")
    
    print(f"  Brute Force:")
    print(f"     Trades: {len(indexes_bf)}")
    print(f"     RPC calls: {max_trades}")
    print(f"     Temps: {time_bf:.3f}s")
    print()
    
    print(f"  Multicall:")
    print(f"     Trades: {len(indexes_mc)}")
    print(f"     RPC calls: 1")
    print(f"     Temps: {time_mc:.3f}s")
    print()
    
    if time_bf > 0 and time_mc > 0:
        speedup = time_bf / time_mc
        print(f"  ⚡ Speedup: {speedup:.1f}x més ràpid")
        print(f"  💾 Estalvi RPC: {max_trades - 1} calls menys")
    
    # Verify results match
    if set(indexes_bf) == set(indexes_mc):
        print(f"\n  ✅ Resultats coincidents: {indexes_bf}")
    else:
        print(f"\n  ⚠️  Resultats diferents!")
        print(f"     Brute force: {indexes_bf}")
        print(f"     Multicall:   {indexes_mc}")
    
    print()

if __name__ == '__main__':
    main()
