#!/usr/bin/env python3
"""
Analitza les transaccions reals de Sepolia per trobar:
1. Adreça del token DAI/USDC que fas servir
2. Verificar open/close trade transactions
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web3 import AsyncWeb3

# ERC20 ABI minimal (balanceOf + decimals + symbol)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
]


async def analyze_transaction(w3: AsyncWeb3, tx_hash: str):
    """Analitza una transacció i extreu informació rellevant"""
    print(f"\n{'='*70}")
    print(f"TX: {tx_hash}")
    print(f"{'='*70}")

    # Get transaction
    tx = await w3.eth.get_transaction(tx_hash)
    receipt = await w3.eth.get_transaction_receipt(tx_hash)

    print(f"From: {tx['from']}")
    print(f"To: {tx['to']}")
    print(f"Value: {w3.from_wei(tx['value'], 'ether')} ETH")
    print(f"Status: {'✅ SUCCESS' if receipt['status'] == 1 else '❌ FAILED'}")
    print(f"Gas Used: {receipt['gasUsed']}")

    # Analitza logs (events)
    if receipt['logs']:
        print(f"\n📋 Events ({len(receipt['logs'])} logs):")
        for i, log in enumerate(receipt['logs'][:5], 1):  # First 5 logs
            print(f"  {i}. Contract: {log['address']}")
            print(f"     Topics: {len(log['topics'])} (first: {log['topics'][0].hex()[:10]}...)")

            # Si és un Transfer event (topic0 = keccak256("Transfer(address,address,uint256)"))
            if log['topics'][0].hex() == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef":
                # Decode Transfer event
                from_addr = "0x" + log['topics'][1].hex()[-40:]
                to_addr = "0x" + log['topics'][2].hex()[-40:]
                amount_hex = log['data'].hex()
                amount = int(amount_hex, 16)
                print(f"     🔄 TRANSFER: {amount} (raw) from {from_addr[:10]}... to {to_addr[:10]}...")

    return tx, receipt


async def check_token_balance(w3: AsyncWeb3, token_address: str, wallet_address: str):
    """Verifica balance d'un token ERC20"""
    print(f"\n{'='*70}")
    print(f"TOKEN: {token_address}")
    print(f"{'='*70}")

    contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)

    try:
        symbol = await contract.functions.symbol().call()
        decimals = await contract.functions.decimals().call()
        balance_raw = await contract.functions.balanceOf(wallet_address).call()
        balance = balance_raw / (10 ** decimals)

        print(f"Symbol: {symbol}")
        print(f"Decimals: {decimals}")
        print(f"Balance: {balance:,.2f} {symbol}")

        return {
            "symbol": symbol,
            "decimals": decimals,
            "balance": balance,
            "balance_raw": balance_raw,
        }
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


async def main():
    rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    wallet_address = "0xD9fC17C093614D20976EFb1535A7142081A031b2"

    print("🔍 Analitzant transaccions de Sepolia...")
    print(f"Wallet: {wallet_address}")

    # Transaccions proporcionades
    txs = [
        ("Transfer/Approve", "0x96b280b1d07aa44152d43015a0160da5c277d9da4c744516abb33b97045508be"),
        ("Open Trade", "0xced130245364a21c052cd913a95138dca230356a5c52dd485ffe1cd6b47f1d3c"),
        ("Close Trade", "0x686a3d540bb2fff557bed0cd1d58c625b9d9de121d2e52bd5f9fff5870576369"),
    ]

    token_addresses = set()

    for label, tx_hash in txs:
        print(f"\n\n{'#'*70}")
        print(f"# {label}")
        print(f"{'#'*70}")
        tx, receipt = await analyze_transaction(w3, tx_hash)

        # Recull adreces de contractes dels logs (possibles tokens)
        for log in receipt['logs']:
            token_addresses.add(log['address'])

    # Verifica balances de tots els tokens detectats
    print(f"\n\n{'#'*70}")
    print(f"# TOKEN BALANCES")
    print(f"{'#'*70}")

    print(f"\nTokens detectats als events: {len(token_addresses)}")
    for token_addr in sorted(token_addresses):
        await check_token_balance(w3, token_addr, wallet_address)

    # També verifica el token USDC conegut
    print(f"\n\n⭐ Token USDC oficial de .env.example:")
    await check_token_balance(w3, "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d", wallet_address)


if __name__ == "__main__":
    asyncio.run(main())
