#!/usr/bin/env python3
"""
Verificació completa de Sepolia testnet setup
Comprova: connexió, wallet, balance GNS_USDC, contractes gTrade
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web3 import AsyncWeb3

# ERC20 ABI minimal
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


async def main():
    print("=" * 70)
    print("🧪 SEPOLIA TESTNET READINESS CHECK")
    print("=" * 70)

    # Configuració
    rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
    wallet_address = "0xD9fC17C093614D20976EFb1535A7142081A031b2"
    gns_usdc_address = "0x4cC7EbEeD5EA3adf3978F19833d2E1f3e8980cD6"
    diamond_address = "0xd659a15812064C79E189fd950A189b15c75d3186"

    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    # 1. Connexió blockchain
    print("\n1️⃣  Blockchain Connection")
    print("-" * 70)
    chain_id = await w3.eth.chain_id
    block_number = await w3.eth.block_number
    print(f"✅ Connected to Arbitrum Sepolia")
    print(f"   Chain ID: {chain_id}")
    print(f"   Latest Block: {block_number:,}")

    # 2. Wallet ETH balance
    print("\n2️⃣  Wallet Status")
    print("-" * 70)
    eth_balance_wei = await w3.eth.get_balance(wallet_address)
    eth_balance = w3.from_wei(eth_balance_wei, "ether")
    print(f"Address: {wallet_address}")
    print(f"ETH Balance: {eth_balance:.6f} ETH")

    if eth_balance < 0.001:
        print(f"⚠️  Low ETH balance (need at least 0.001 ETH for gas)")
    else:
        print(f"✅ Sufficient ETH for transactions")

    # 3. GNS_USDC balance
    print("\n3️⃣  GNS_USDC Token Balance")
    print("-" * 70)
    gns_usdc_contract = w3.eth.contract(address=gns_usdc_address, abi=ERC20_ABI)

    symbol = await gns_usdc_contract.functions.symbol().call()
    decimals = await gns_usdc_contract.functions.decimals().call()
    balance_raw = await gns_usdc_contract.functions.balanceOf(wallet_address).call()
    balance = balance_raw / (10**decimals)

    print(f"Token: {symbol}")
    print(f"Contract: {gns_usdc_address}")
    print(f"Balance: {balance:,.2f} {symbol}")

    if balance < 100:
        print(f"⚠️  Low balance (need at least 100 {symbol} for trading)")
        print(f"   → Go to https://gains.trade/ and claim practice tokens")
    else:
        print(f"✅ Ready to trade!")

    # 4. gTrade Diamond contract
    print("\n4️⃣  gTrade Contracts")
    print("-" * 70)
    diamond_code = await w3.eth.get_code(diamond_address)

    if len(diamond_code) > 2:
        print(f"✅ gTrade Diamond: {diamond_address}")
        print(f"   Contract size: {len(diamond_code):,} bytes")
    else:
        print(f"❌ gTrade Diamond not found at {diamond_address}")

    # 5. Resum final
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)

    all_ready = (
        chain_id == 421614
        and eth_balance >= 0.001
        and balance >= 100
        and len(diamond_code) > 2
    )

    if all_ready:
        print("✅ All systems ready for testnet trading!")
        print(f"\n💡 You have {balance:,.2f} {symbol} available")
        print(f"💡 You can open positions up to ~{balance * 10:,.0f} {symbol} (10x leverage)")
    else:
        print("⚠️  Some checks failed. Please review above.")

    return all_ready


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
