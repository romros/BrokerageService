#!/usr/bin/env python3
"""
Approve USDC allowance for gTrade Diamond contract

This script approves unlimited USDC spending for the gTrade contract.
Required before opening positions.

Usage:
    python scripts/approve_usdc.py
"""

import asyncio
import os
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path (works from scripts/ or _archive/.../scripts/)
_project = Path(__file__).resolve()
project_root = _project.parent
for _ in range(5):
    if (project_root / "application").is_dir() or (project_root / "docker-compose.yml").exists():
        break
    project_root = project_root.parent
sys.path.insert(0, str(project_root))

from web3 import AsyncWeb3, Web3
from infrastructure.venues.gtrade.chain_config import load_chain_config_from_env
from loguru import logger

# ERC20 ABI (minimal - just approve)
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
]


async def main():
    print("\n" + "=" * 80)
    print("🔓 USDC ALLOWANCE APPROVAL")
    print("=" * 80)
    print()

    # Load config
    config = load_chain_config_from_env()

    if not config.has_wallet:
        print("❌ No wallet configured")
        return 1

    # Create Web3 instance
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(config.rpc_url))

    # Load account
    account = w3.eth.account.from_key(config.wallet_private_key)
    wallet_address = account.address

    print(f"Wallet: {wallet_address}")
    print(f"USDC Token: {config.addresses.usdc}")
    print(f"gTrade Diamond: {config.addresses.diamond}")
    print()

    # Create USDC contract instance
    usdc_contract = w3.eth.contract(
        address=Web3.to_checksum_address(config.addresses.usdc),
        abi=ERC20_ABI
    )

    # Check current allowance
    current_allowance = await usdc_contract.functions.allowance(
        wallet_address,
        Web3.to_checksum_address(config.addresses.diamond)
    ).call()

    print(f"Current allowance: {current_allowance}")

    if current_allowance > 0:
        print(f"✅ Allowance already approved: {current_allowance}")
        print(f"   (Enough for {current_allowance / (10**6):.2f} USDC)")
        return 0

    # Approve unlimited (max uint256)
    max_uint256 = 2**256 - 1

    print()
    print("⚠️  Approving unlimited USDC spending for gTrade contract...")
    print(f"   Amount: {max_uint256} (unlimited)")
    print()

    # Build approve transaction
    tx_data = usdc_contract.functions.approve(
        Web3.to_checksum_address(config.addresses.diamond),
        max_uint256
    ).build_transaction({
        'from': wallet_address,
        'nonce': await w3.eth.get_transaction_count(wallet_address),
        'gas': 100000,  # Standard approve gas
        'maxFeePerGas': await w3.eth.gas_price,
        'maxPriorityFeePerGas': Web3.to_wei(1, 'gwei'),
        'chainId': config.chain_id,
    })

    # Sign transaction
    signed_tx = account.sign_transaction(tx_data)

    # Send transaction
    print("📤 Sending transaction...")
    tx_hash = await w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"   TxHash: {tx_hash.hex()}")

    # Wait for confirmation
    print("⏳ Waiting for confirmation...")
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt['status'] == 1:
        print()
        print("✅ Allowance approved successfully!")
        print(f"   TxHash: {tx_hash.hex()}")
        print(f"   Block: {receipt['blockNumber']}")
        print(f"   Gas used: {receipt['gasUsed']}")
        return 0
    else:
        print()
        print("❌ Transaction failed")
        print(f"   TxHash: {tx_hash.hex()}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
