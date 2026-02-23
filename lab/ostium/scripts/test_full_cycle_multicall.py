#!/usr/bin/env python3
"""
Ostium Testnet - Full Cycle amb MULTICALL
1. Open trade
2. Wait 10s
3. Find trade amb multicall (optimitzat)
4. Close trade
"""

import asyncio
import json
import os
import time
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
    # Fallback: minimal ABI with correct Trade struct order (collateral, openPrice, tp, sl, trader, leverage, pairIndex, index, buy)
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

# getOpenTrade on "trading" reverts; use tradingStorage for reads (ABI = Trade struct from IOstiumTradingStorage)
TRADING_STORAGE_ABI = _load_trading_storage_abi()
DEFAULT_STORAGE = NetworkConfig.testnet().contracts["tradingStorage"]
TRADING_STORAGE_CONTRACT = os.getenv("TRADING_STORAGE_CONTRACT", DEFAULT_STORAGE)
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Trade struct layout (IOstiumTradingStorage): (uint256,uint192,uint192,uint192,address,uint32,uint16,uint8,bool)
TRADE_DECODE_TYPES = ["(uint256,uint192,uint192,uint192,address,uint32,uint16,uint8,bool)"]

# Paràmetres del trade que obrim a STEP 1 (per selecció determinista)
EXPECTED_LEVERAGE_STORAGE = 200   # 2x → PRECISION_2
EXPECTED_BUY = True               # LONG
MIN_COLLATERAL_USDC_UNITS = 3_000_000  # ~3 USDC (PRECISION_6) per tolerar fees

def find_trade_with_multicall(w3, trader, pair_id, max_attempts=10, index_base=0, sanity_check=False):
    """Troba trades oberts amb multicall. Retorna list[dict] amb index, collateral, open_price, leverage, buy."""
    end = index_base + max_attempts - 1
    print(f"\n⚡ Buscant trade amb MULTICALL (rang {index_base}..{end})...")
    
    start = time.time()
    trader_cs = Web3.to_checksum_address(trader) if isinstance(trader, str) else trader
    
    storage_contract = w3.eth.contract(
        address=Web3.to_checksum_address(TRADING_STORAGE_CONTRACT),
        abi=TRADING_STORAGE_ABI
    )
    multicall_contract = w3.eth.contract(
        address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
        abi=MULTICALL3_ABI
    )
    
    calls = []
    for offset in range(max_attempts):
        index = index_base + offset
        call_data = storage_contract.functions.getOpenTrade(trader_cs, pair_id, index)._encode_transaction_data()
        calls.append((TRADING_STORAGE_CONTRACT, call_data))
    
    results = multicall_contract.functions.tryAggregate(False, calls).call()
    n_calls = len(results)
    n_success = sum(1 for s, _ in results if s)
    print(f"  success={n_success}/{n_calls}")
    
    found_trades = []
    for offset, (success, data) in enumerate(results):
        if not success or len(data) == 0:
            continue
        index = index_base + offset
        try:
            raw = data if isinstance(data, bytes) else bytes(data)
            trade = w3.codec.decode(TRADE_DECODE_TYPES, raw)[0]
            collateral = trade[0]
            open_price = trade[1]
            t_trader = trade[4]
            t_pair = int(trade[6])
            t_index = int(trade[7])
            if Web3.to_checksum_address(t_trader) != trader_cs or t_pair != pair_id or t_index != index:
                continue
            is_open = (collateral > 0 and open_price > 0)
            if is_open:
                leverage = trade[5]
                buy = bool(trade[8])
                found_trades.append({
                    "index": index,
                    "collateral": collateral,
                    "open_price": open_price,
                    "leverage": leverage,
                    "buy": buy,
                })
                print(f"  ✅ Trobat index {index}: openPrice={open_price} collateral={collateral} leverage={leverage} buy={buy}")
        except Exception:
            continue
    
    if not found_trades and (sanity_check or max_attempts == 1):
        print(f"  DEBUG no open trade at idx={index_base} (collateral>0 and openPrice>0)")
    
    elapsed = time.time() - start
    print(f"  ⏱️  Temps: {elapsed:.3f}s (1 RPC call)")
    return found_trades

async def main():
    print("\n" + "="*80)
    print("🧪 OSTIUM TESTNET — FULL CYCLE AMB MULTICALL")
    print("="*80 + "\n")
    
    # Load env
    load_dotenv()
    rpc_url = (os.getenv("RPC_URL") or "https://sepolia-rollup.arbitrum.io/rpc").strip()
    if not rpc_url:
        print("❌ RPC_URL required")
        return

    private_key = (os.getenv("PRIVATE_KEY") or "").strip()
    scan_only = os.getenv("SCAN_ONLY", "1").strip() == "1"
    sanity_check = os.getenv("SANITY_CHECK", "0").strip() == "1"

    if not scan_only and not private_key:
        print("❌ PRIVATE_KEY not set (required when SCAN_ONLY=0)")
        return
    if scan_only and not private_key:
        trader_raw = (os.getenv("TRADER_ADDRESS") or "").strip()
        if not trader_raw:
            print("❌ SCAN_ONLY=1 requires RPC_URL and (PRIVATE_KEY or TRADER_ADDRESS)")
            return
        trader = Web3.to_checksum_address(trader_raw)
        account = None
        sdk = None
    else:
        account = Account.from_key(private_key)
        trader = account.address
        config = NetworkConfig.testnet()
        sdk = OstiumSDK(config, private_key, rpc_url)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    print(f"Wallet: {trader}")
    print(f"Network: Arbitrum Sepolia testnet")
    print()

    pair_id = int(os.getenv("PAIR_ID", "2"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "10"))
    index_base = int(os.getenv("INDEX_BASE", "0"))
    oracle_wait_s = int(os.getenv("ORACLE_WAIT_S", "30"))

    print("Config (env):")
    print(f"  PAIR_ID={pair_id}  MAX_ATTEMPTS={max_attempts}  INDEX_BASE={index_base}  SCAN_ONLY={scan_only}  SANITY_CHECK={sanity_check}  ORACLE_WAIT_S={oracle_wait_s}")
    print(f"  Rang efectiu: {index_base}..{index_base + max_attempts - 1}")
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
            tx_hash = receipt.get("transactionHash") or receipt.get("hash") if isinstance(receipt, dict) else None
            if tx_hash is not None and hasattr(tx_hash, "hex"):
                tx_hash = tx_hash.hex()
            else:
                tx_hash = str(tx_hash) if tx_hash is not None else "unknown"
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

    if sanity_check:
        print("🧪 SANITY_CHECK=1 → direct call getOpenTrade(trader, pair_id, index_base)")
        storage_contract = w3.eth.contract(
            address=Web3.to_checksum_address(TRADING_STORAGE_CONTRACT),
            abi=TRADING_STORAGE_ABI
        )
        direct = storage_contract.functions.getOpenTrade(
            Web3.to_checksum_address(trader), pair_id, index_base
        ).call()
        # direct = (collateral, openPrice, tp, sl, trader, leverage, pairIndex, index, buy) from .call() decoded
        if isinstance(direct, (list, tuple)) and len(direct) >= 9:
            print(f"  collateral={direct[0]}  openPrice={direct[1]}  tp={direct[2]}  sl={direct[3]}")
            print(f"  trader={direct[4]}  leverage={direct[5]}  pairIndex={direct[6]}  index={direct[7]}  buy={direct[8]}")
        else:
            print(f"  raw={direct}")
        print()
    
    print(f"  PAIR_ID={pair_id}  MAX_ATTEMPTS={max_attempts}  INDEX_BASE={index_base} (rang {index_base}..{index_base + max_attempts - 1})")
    found_trades = find_trade_with_multicall(
        w3, trader, pair_id, max_attempts=max_attempts, index_base=index_base, sanity_check=sanity_check
    )
    print(f"  Indexes trobats: {[t['index'] for t in found_trades]}")
    print()
    
    if not found_trades:
        print(f"\n❌ No s'ha trobat cap trade obert!")
        print(f"   Potser el trade es va tancar automàticament?")
        if scan_only:
            print("  (SCAN_ONLY: no s'ha obert cap trade)")
        return
    
    # Selecció determinista: trade nou (2x LONG, collateral ~5 USDC) o el d’index més alt
    matches = [
        t for t in found_trades
        if t["buy"] == EXPECTED_BUY
        and t["leverage"] == EXPECTED_LEVERAGE_STORAGE
        and t["collateral"] >= MIN_COLLATERAL_USDC_UNITS
    ]
    if matches:
        selected = max(matches, key=lambda t: t["index"])
    else:
        selected = max(found_trades, key=lambda t: t["index"])
    trade_index = selected["index"]
    print(f"\n✅ Trade seleccionat per tancar: index={trade_index} leverage={selected['leverage']} buy={selected['buy']} collateral={selected['collateral']}")
    print()
    
    if scan_only:
        print("ℹ SCAN_ONLY=1 → no es tanca cap trade")
        print("="*80)
        print("✅ SCAN COMPLET")
        print("="*80 + "\n")
        return
    
    # STEP 4: Close trade (requereix market_price)
    print("="*80)
    print("STEP 4: TANCAR TRADE")
    print("="*80 + "\n")
    
    try:
        market_price, _, _ = await sdk.price.get_price("EUR", "USD")
        print(f"  Preu actual EUR/USD: ${market_price:.5f}")
        receipt = sdk.ostium.close_trade(pair_id, trade_index, market_price)
        tx_hash = receipt.get("transactionHash") or receipt.get("hash")
        if tx_hash is not None and hasattr(tx_hash, "hex"):
            tx_hash = tx_hash.hex()
        else:
            tx_hash = str(tx_hash) if tx_hash is not None else "unknown"
        gas_used = receipt.get("gasUsed")
        gas_str = f"  gasUsed: {gas_used}" if gas_used is not None else ""
        print(f"✅ Trade tancat!")
        print(f"   TX: {tx_hash}")
        if gas_str:
            print(gas_str)
        print()
    except Exception as e:
        print(f"❌ Error tancant trade: {e}")
        return
    
    # Post-check: re-scan i comprovar que l’index tancat ja no hi és
    print("Post-check: verificant que l’index tancat ja no apareix...")
    await asyncio.sleep(2)
    for attempt in range(2):
        check_trades = find_trade_with_multicall(
            w3, trader, pair_id, max_attempts=max_attempts, index_base=index_base
        )
        still_open = [t for t in check_trades if t["index"] == trade_index]
        if not still_open:
            print(f"  ✅ L’index {trade_index} ja no apareix (tancat correctament)")
            break
        if attempt == 0:
            await asyncio.sleep(2)
        else:
            print(f"  ⚠ L’index {trade_index} encara apareix després de 2 intents (pot ser retard chain)")
    print()
    
    # Summary
    print("="*80)
    print("✅ TEST COMPLET!")
    print("="*80 + "\n")
    
    print(f"Flux executat correctament:")
    print(f"  1. ✅ Trade obert")
    print(f"  2. ✅ Esperat {oracle_wait_s}s")
    print(f"  3. ✅ Trobat amb MULTICALL (1 RPC call)")
    print(f"  4. ✅ Trade tancat (market_price passat)")
    print()
    
    print(f"🎯 Multicall va trobar el trade en 1 sola crida!")
    print()

if __name__ == '__main__':
    asyncio.run(main())
