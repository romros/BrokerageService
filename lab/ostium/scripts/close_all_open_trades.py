#!/usr/bin/env python3
"""
Ostium LAB — Tancar totes les posicions obertes (scan chain-based + close_trade).

- SCAN_ONLY=1: llista trades oberts sense tancar (accepta TRADER_ADDRESS sense PRIVATE_KEY).
- SCAN_ONLY=0: tanca fins a MAX_CLOSE trades (exigeix PRIVATE_KEY).
- Filtre opcional PAIR_ID; post-check re-scan i report final.

Ús (des de l'arrel del repo):
  docker compose -p lab_ostium run --rm -e RPC_URL -e TRADER_ADDRESS -e SCAN_ONLY=1 \\
    ostium-cli python3 scripts/close_all_open_trades.py
  docker compose -p lab_ostium run --rm -e RPC_URL -e PRIVATE_KEY -e SCAN_ONLY=0 -e MAX_CLOSE=3 \\
    ostium-cli python3 scripts/close_all_open_trades.py
"""

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

# ABI i contractes (mateix patró que test_full_cycle_multicall.py)
def _load_trading_storage_abi():
    abi_path = Path(__file__).resolve().parent.parent / "abi" / "tradingStorage_getOpenTrade.json"
    if abi_path.exists():
        with open(abi_path, encoding="utf-8") as f:
            return json.load(f)
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

TRADE_DECODE_TYPES = ["(uint256,uint192,uint192,uint192,address,uint32,uint16,uint8,bool)"]

MULTICALL3_ABI = [{
    "inputs": [
        {"name": "requireSuccess", "type": "bool"},
        {"components": [{"name": "target", "type": "address"}, {"name": "callData", "type": "bytes"}], "name": "calls", "type": "tuple[]"}
    ],
    "name": "tryAggregate",
    "outputs": [{"components": [{"name": "success", "type": "bool"}, {"name": "returnData", "type": "bytes"}], "name": "returnData", "type": "tuple[]"}],
    "stateMutability": "view",
    "type": "function"
}]

TRADING_STORAGE_ABI = _load_trading_storage_abi()
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"


def _get_storage_contract_address():
    from ostium_python_sdk import NetworkConfig
    return os.getenv("TRADING_STORAGE_CONTRACT", NetworkConfig.testnet().contracts["tradingStorage"])


def scan_open_trades(w3, trader, pair_id, index_base, max_attempts):
    """Escaneja trades oberts per (trader, pair_id) amb multicall. Retorna list[dict] amb pair_id, index, buy, leverage, collateral, open_price."""
    trader_cs = Web3.to_checksum_address(trader) if isinstance(trader, str) else trader
    storage_addr = _get_storage_contract_address()
    storage_contract = w3.eth.contract(address=Web3.to_checksum_address(storage_addr), abi=TRADING_STORAGE_ABI)
    multicall_contract = w3.eth.contract(address=Web3.to_checksum_address(MULTICALL3_ADDRESS), abi=MULTICALL3_ABI)

    calls = []
    for offset in range(max_attempts):
        index = index_base + offset
        call_data = storage_contract.functions.getOpenTrade(trader_cs, pair_id, index)._encode_transaction_data()
        calls.append((storage_addr, call_data))

    results = multicall_contract.functions.tryAggregate(False, calls).call()
    found = []
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
            if collateral > 0 and open_price > 0:
                found.append({
                    "pair_id": pair_id,
                    "index": index,
                    "buy": bool(trade[8]),
                    "leverage": trade[5],
                    "collateral": collateral,
                    "open_price": open_price,
                })
        except Exception:
            continue
    return found


async def main():
    load_dotenv()
    rpc_url = (os.getenv("RPC_URL") or "https://sepolia-rollup.arbitrum.io/rpc").strip()
    if not rpc_url:
        print("❌ RPC_URL required")
        return 1

    scan_only = os.getenv("SCAN_ONLY", "1").strip() == "1"
    private_key = (os.getenv("PRIVATE_KEY") or "").strip()
    trader_raw = (os.getenv("TRADER_ADDRESS") or "").strip()
    pair_id = int(os.getenv("PAIR_ID", "2"))
    index_base = int(os.getenv("INDEX_BASE", "0"))
    max_attempts = int(os.getenv("MAX_ATTEMPTS", "64"))
    max_close = int(os.getenv("MAX_CLOSE", "5"))
    market_base = os.getenv("MARKET_BASE", "EUR").strip()
    market_quote = os.getenv("MARKET_QUOTE", "USD").strip()

    if not scan_only and not private_key:
        print("❌ PRIVATE_KEY required when SCAN_ONLY=0")
        return 1
    if scan_only and not private_key and not trader_raw:
        print("❌ SCAN_ONLY=1 requires RPC_URL and (PRIVATE_KEY or TRADER_ADDRESS)")
        return 1

    if scan_only and not private_key:
        trader = Web3.to_checksum_address(trader_raw)
        sdk = None
    else:
        from eth_account import Account
        from ostium_python_sdk import OstiumSDK, NetworkConfig
        account = Account.from_key(private_key)
        trader = account.address
        sdk = OstiumSDK(NetworkConfig.testnet(), private_key, rpc_url)

    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if pair_id != 2:
        print(f"⚠ PAIR_ID={pair_id} (no és 2/EURUSD); preu obtingut amb MARKET_BASE={market_base} MARKET_QUOTE={market_quote}")
    print("=" * 60)
    print("🧹 Ostium LAB — Close all open trades")
    print("=" * 60)
    print(f"  RPC_URL=...  PAIR_ID={pair_id}  INDEX_BASE={index_base}  MAX_ATTEMPTS={max_attempts}")
    print(f"  SCAN_ONLY={scan_only}  MAX_CLOSE={max_close}")
    print()

    # Scan
    trades = scan_open_trades(w3, trader, pair_id, index_base, max_attempts)
    found_before = len(trades)

    if not trades:
        print("Cap trade obert trobat.")
        return 0

    # Ordenar desc per (pair_id, index) — tancar els més nous primer
    trades.sort(key=lambda t: (t["pair_id"], t["index"]), reverse=True)

    print(f"Trades oberts (found_before={found_before}):")
    for t in trades:
        print(f"  pairIndex={t['pair_id']}  index={t['index']}  buy={t['buy']}  leverage={t['leverage']}  collateral={t['collateral']}  openPrice={t['open_price']}")
    print()

    if scan_only:
        print("SCAN_ONLY=1 → no es tanca res.")
        return 0

    # Obtenir market_price (obligatori per tancar)
    try:
        market_price, _, _ = await sdk.price.get_price(market_base, market_quote)
        print(f"Preu de mercat {market_base}/{market_quote}: ${market_price:.5f}")
    except Exception as e:
        print(f"❌ No es pot obtenir preu: {e}. No es tanca res.")
        return 1

    to_close = trades[:max_close]
    print(f"Tancant fins a {len(to_close)} trades (MAX_CLOSE={max_close})...")
    closed_ok = 0
    for t in to_close:
        try:
            receipt = sdk.ostium.close_trade(t["pair_id"], t["index"], market_price)
            tx_hash = receipt.get("transactionHash") or receipt.get("hash")
            if tx_hash is not None and hasattr(tx_hash, "hex"):
                tx_hash = tx_hash.hex()
            else:
                tx_hash = str(tx_hash) if tx_hash else "unknown"
            print(f"  ✅ Tancat pair={t['pair_id']} index={t['index']}  TX: {tx_hash}")
            closed_ok += 1
        except Exception as e:
            print(f"  ❌ Error tancant pair={t['pair_id']} index={t['index']}: {e}")
        await asyncio.sleep(2)

    # Post-check: re-scan
    print()
    print("Post-check: re-scan...")
    await asyncio.sleep(2)
    after = scan_open_trades(w3, trader, pair_id, index_base, max_attempts)
    still_open_after = len(after)

    print()
    print("Resum:")
    print(f"  found_before={found_before}  closed_ok={closed_ok}  still_open_after={still_open_after}")
    if still_open_after > 0:
        print(f"  ⚠ Encara queden {still_open_after} trades oberts (re-executa amb MAX_CLOSE o comprova retard chain).")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
