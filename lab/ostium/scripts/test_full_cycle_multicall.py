#!/usr/bin/env python3
"""
Ostium Testnet - Full Cycle amb MULTICALL
1. Open trade
2. Wait 10s
3. Find trade amb multicall (optimitzat)
4. Close trade
"""

import asyncio
import os
import time
from dotenv import load_dotenv
from ostium_python_sdk import OstiumSDK, NetworkConfig
from eth_account import Account
from web3 import Web3

# Multicall3 ABI
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

# Trading contract ABI
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

# getOpenTrade on "trading" reverts; use tradingStorage for reads
DEFAULT_STORAGE = NetworkConfig.testnet().contracts["tradingStorage"]
TRADING_STORAGE_CONTRACT = os.getenv("TRADING_STORAGE_CONTRACT", DEFAULT_STORAGE)
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

def find_trade_with_multicall(w3, trader, pair_id, max_attempts=10):
    """Troba trade index amb multicall (1 RPC call). Uses tradingStorage (getOpenTrade does not revert)."""
    print(f"\n⚡ Buscant trade amb MULTICALL...")
    
    start = time.time()
    
    # Setup contracts (tradingStorage for getOpenTrade reads)
    storage_contract = w3.eth.contract(
        address=Web3.to_checksum_address(TRADING_STORAGE_CONTRACT),
        abi=TRADING_ABI
    )
    
    multicall_contract = w3.eth.contract(
        address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
        abi=MULTICALL3_ABI
    )
    
    # Prepare multicall
    calls = []
    for index in range(max_attempts):
        call_data = storage_contract.functions.getOpenTrade(
            Web3.to_checksum_address(trader),
            pair_id,
            index
        )._encode_transaction_data()
        calls.append((TRADING_STORAGE_CONTRACT, call_data))
    
    # Execute
    results = multicall_contract.functions.tryAggregate(False, calls).call()
    n_calls = len(results)
    n_success = sum(1 for success, _ in results if success)
    print(f"  success={n_success}/{n_calls}")
    
    # Find trades
    found_indexes = []
    for index, (success, data) in enumerate(results):
        if not success or len(data) == 0:
            continue
            
        try:
            decoded = w3.codec.decode(['uint192', 'uint192', 'uint192', 'uint192', 'uint32', 'bool'], data)
            collateral = decoded[3]
            
            if collateral > 0:
                found_indexes.append(index)
                print(f"  ✅ Trobat index {index}: collateral={collateral}")
        except Exception:
            continue
    
    elapsed = time.time() - start
    print(f"  ⏱️  Temps: {elapsed:.3f}s (1 RPC call)")
    
    return found_indexes

async def main():
    print("\n" + "="*80)
    print("🧪 OSTIUM TESTNET — FULL CYCLE AMB MULTICALL")
    print("="*80 + "\n")
    
    # Load env
    load_dotenv()
    private_key = os.getenv('PRIVATE_KEY')
    rpc_url = os.getenv('RPC_URL', 'https://sepolia-rollup.arbitrum.io/rpc')
    
    if not private_key:
        print("❌ PRIVATE_KEY not set")
        return
    
    # Setup
    config = NetworkConfig.testnet()
    sdk = OstiumSDK(config, private_key, rpc_url)
    
    account = Account.from_key(private_key)
    trader = account.address
    
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    print(f"Wallet: {trader}")
    print(f"Network: Arbitrum Sepolia testnet")
    print()

    pair_id = int(os.getenv("PAIR_ID", "2"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "10"))
    scan_only = os.getenv("SCAN_ONLY", "1").strip() == "1"
    oracle_wait_s = int(os.getenv("ORACLE_WAIT_S", "30"))

    print("Config (env):")
    print(f"  PAIR_ID={pair_id}  MAX_ATTEMPTS={max_attempts}  SCAN_ONLY={scan_only}  ORACLE_WAIT_S={oracle_wait_s}")
    print(f"  TRADING_STORAGE_CONTRACT={TRADING_STORAGE_CONTRACT}")
    print(f"  MULTICALL3={MULTICALL3_ADDRESS}")
    print(f"  RPC_URL={rpc_url[:60]}..." if len(rpc_url) > 60 else f"  RPC_URL={rpc_url}")
    print()

    if scan_only:
        print("ℹ SCAN_ONLY=1 → no s'obre trade, només es busca trade existent")
        print()
    
    if not scan_only:
        print(f"⚠️  NOTA: Aquest test requereix fonds testnet:")
        print(f"   • USDC testnet: https://testnet.ostium.app/ (faucet)")
        print(f"   • ETH testnet: https://www.alchemy.com/faucets/arbitrum-sepolia")
        print(f"   Si no tens fonds, el trade fallarà")
        print()
    
    # STEP 1: Open trade
    if not scan_only:
        print("="*80)
        print("STEP 1: OBRIR TRADE")
        print("="*80 + "\n")
    
    if not scan_only:
        try:
            # Get latest price
            latest_price, _, _ = await sdk.price.get_price("EUR", "USD")
            print(f"💵 Preu EUR/USD: ${latest_price:.5f}")
            
            # Define trade
            trade_params = {
                'collateral': 5,           # 5 USDC (mínim)
                'leverage': 2,             # 2x (conservador)
                'asset_type': pair_id,     # EURUSD
                'direction': True,         # LONG
                'order_type': 'MARKET'
            }
            
            print(f"\n📊 Obrint trade:")
            print(f"   Collateral: {trade_params['collateral']} USDC")
            print(f"   Leverage: {trade_params['leverage']}x")
            print(f"   Direction: {'LONG' if trade_params['direction'] else 'SHORT'}")
            print(f"   Entry: ${latest_price:.5f}")
            print()
            
            # Open trade
            receipt = sdk.ostium.perform_trade(trade_params, at_price=latest_price)
            
            # Get TX hash
            if isinstance(receipt, dict):
                tx_hash = receipt.get('transactionHash', receipt.get('hash', 'unknown'))
                if hasattr(tx_hash, 'hex'):
                    tx_hash = tx_hash.hex()
            else:
                tx_hash = 'unknown'
            
            print(f"✅ Trade obert!")
            print(f"   TX: {tx_hash}")
            print()
            
        except Exception as e:
            print(f"❌ Error obrint trade: {e}")
            return
    
    # STEP 2: Wait (longer for oracle confirmation)
    if not scan_only:
        print("="*80)
        print(f"STEP 2: ESPERAR CONFIRMACIÓ ({oracle_wait_s}s)")
        print("="*80 + "\n")
        
        print("  ⏳ Esperant confirmació del trade amb oracle...")
        print("     (Ostium usa oracles per confirmar preus)")
        print()
        
        for i in range(oracle_wait_s, 0, -1):
            print(f"  ⏳ {i}s...", end='\r', flush=True)
            await asyncio.sleep(1)
        print(f"  ✅ Espera completada!      ")
        print()
    
    # STEP 3: Find trade with multicall
    print("="*80)
    print("STEP 3: TROBAR TRADE AMB MULTICALL")
    print("="*80 + "\n")
    
    print(f"  PAIR_ID={pair_id}  MAX_ATTEMPTS={max_attempts}")
    found_indexes = find_trade_with_multicall(w3, trader, pair_id, max_attempts=max_attempts)
    print(f"  Indexes trobats: {found_indexes}")
    print()
    
    if not found_indexes:
        print(f"\n❌ No s'ha trobat cap trade obert!")
        print(f"   Potser el trade es va tancar automàticament?")
        if scan_only:
            print("  (SCAN_ONLY: no s'ha obert cap trade)")
        return
    
    trade_index = found_indexes[0]
    print(f"\n✅ Trade trobat a index: {trade_index}")
    print()
    
    if scan_only:
        print("ℹ SCAN_ONLY=1 → no es tanca cap trade")
        print("="*80)
        print("✅ SCAN COMPLET")
        print("="*80 + "\n")
        return
    
    # STEP 4: Close trade
    print("="*80)
    print("STEP 4: TANCAR TRADE")
    print("="*80 + "\n")
    
    try:
        receipt = sdk.ostium.close_trade(pair_id, trade_index)
        tx_hash = receipt['transactionHash'].hex()
        
        print(f"✅ Trade tancat!")
        print(f"   TX: {tx_hash}")
        print()
        
    except Exception as e:
        print(f"❌ Error tancant trade: {e}")
        return
    
    # Summary
    print("="*80)
    print("✅ TEST COMPLET!")
    print("="*80 + "\n")
    
    print(f"Flux executat correctament:")
    print(f"  1. ✅ Trade obert")
    print(f"  2. ✅ Esperat {oracle_wait_s}s")
    print(f"  3. ✅ Trobat amb MULTICALL (1 RPC call)")
    print(f"  4. ✅ Trade tancat")
    print()
    
    print(f"🎯 Multicall va trobar el trade en 1 sola crida!")
    print()

if __name__ == '__main__':
    asyncio.run(main())
