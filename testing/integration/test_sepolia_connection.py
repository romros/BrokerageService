#!/usr/bin/env python3
"""
Verify gTrade contracts exist on Arbitrum Sepolia
"""

import asyncio

from web3 import AsyncWeb3


async def main():
    # Arbitrum Sepolia RPC
    rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

    print("\n" + "="*60)
    print("Verificant Arbitrum Sepolia Testnet")
    print("="*60)

    # Verificar connexió
    chain_id = await w3.eth.chain_id
    block_number = await w3.eth.block_number
    print(f"\n✅ Connectat: Chain ID {chain_id}, Block {block_number}")

    if chain_id != 421614:
        print(f"   ⚠️  WARNING: Expected Chain ID 421614 (Arbitrum Sepolia)")

    # Verificar wallet
    wallet_address = "0xD9fC17C093614D20976EFb1535A7142081A031b2"
    balance_wei = await w3.eth.get_balance(wallet_address)
    balance_eth = w3.from_wei(balance_wei, 'ether')
    print(f"\n✅ Wallet: {wallet_address}")
    print(f"   Balance: {balance_eth} ETH")

    if balance_eth < 0.01:
        print(f"   ⚠️  Low ETH! Get more from: https://arbitrum.io/bridge")

    # Verificar USDC Sepolia
    usdc_sepolia = "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d"
    usdc_code = await w3.eth.get_code(usdc_sepolia)
    if len(usdc_code) > 2:
        print(f"\n✅ USDC Contract: {usdc_sepolia}")

        # Query USDC balance
        usdc_abi = [{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}]
        usdc_contract = w3.eth.contract(address=usdc_sepolia, abi=usdc_abi)
        usdc_balance = await usdc_contract.functions.balanceOf(wallet_address).call()
        usdc_decimals = await usdc_contract.functions.decimals().call()
        usdc_amount = usdc_balance / (10 ** usdc_decimals)
        print(f"   USDC Balance: {usdc_amount:,.2f} USDC")

        if usdc_amount < 100:
            print(f"   ⚠️  Low USDC! This is likely practice DAI from gTrade")
    else:
        print(f"\n❌ USDC Contract: {usdc_sepolia} (NOT FOUND)")

    # Verificar gTrade Diamond (SEPOLIA testnet address)
    diamond_sepolia = "0xd659a15812064C79E189fd950A189b15c75d3186"
    diamond_code = await w3.eth.get_code(diamond_sepolia)
    if len(diamond_code) > 2:
        print(f"\n✅ gTrade Diamond (Sepolia): {diamond_sepolia}")
        print(f"   Contract code: {len(diamond_code)} bytes")
    else:
        print(f"\n❌ gTrade Diamond: {diamond_sepolia} (NOT FOUND)")
        print(f"   ⚠️  This should exist according to gTrade docs!")
        return 1

    # També verificar el backend Sepolia
    print(f"\n📡 Backend Sepolia: https://backend-sepolia.gains.trade")
    print(f"   Check open trades: https://backend-sepolia.gains.trade/open-trades/{wallet_address}")

    print("\n" + "="*60)
    print("CONCLUSIÓ:")
    print("="*60)
    if len(diamond_code) > 2:
        print("✅ Tots els contractes disponibles a Sepolia!")
        print("\n📋 NEXT STEPS:")
        print("\n   1️⃣  Get Practice DAI")
        print("       → Go to https://gains.trade/")
        print("       → Switch to Practice Mode")
        print("       → Claim 10,000 DAI")
        print("\n   2️⃣  Configure .env file")
        print("       → cp .env.example .env")
        print("       → Add your 12-word seed phrase to WALLET_MNEMONIC")
        print("\n   3️⃣  Run first test")
        print("       → ./test.sh testing/integration/test_wallet_connection.py")
    else:
        print("❌ gTrade contract not found!")
        print("   Double-check the testnet address in gTrade docs.")
    print("="*60 + "\n")

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
