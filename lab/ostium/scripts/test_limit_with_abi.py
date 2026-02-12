#!/usr/bin/env python3
"""
Test LIMIT order directly with ABI to understand what parameters it needs.
"""

import asyncio
import os
from decimal import Decimal
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from ostium_python_sdk import OstiumSDK, NetworkConfig
from ostium_python_sdk.abi.trading_abi import trading_abi
from ostium_python_sdk.abi.usdc_abi import usdc_abi

# Order types from SDK
MARKET = 0
LIMIT = 1
STOP = 2

PRECISION_10 = 10**10
PRECISION_2 = 10**2

async def main():
    print("\n" + "=" * 80)
    print("🧪 TEST LIMIT ORDER WITH ABI")
    print("=" * 80)
    print()

    load_dotenv()
    private_key = os.getenv('PRIVATE_KEY')

    if not private_key:
        print("❌ PRIVATE_KEY not set")
        return

    # Setup
    w3 = Web3(Web3.HTTPProvider('https://sepolia-rollup.arbitrum.io/rpc'))
    account = Account.from_key(private_key)

    # Contracts
    trading_address = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"
    usdc_address = "0xe73B11Fb1e3eeEe8AF2a23079A4410Fe1B370548"

    trading_contract = w3.eth.contract(
        address=Web3.to_checksum_address(trading_address),
        abi=trading_abi
    )

    usdc_contract = w3.eth.contract(
        address=Web3.to_checksum_address(usdc_address),
        abi=usdc_abi
    )

    print(f"Wallet: {account.address}")
    print(f"Trading: {trading_address}")
    print(f"USDC: {usdc_address}")
    print()

    # Get current price from SDK
    config = NetworkConfig.testnet()
    sdk = OstiumSDK(config, private_key)

    eur_price, _, _ = await sdk.price.get_price("EUR", "USD")
    print(f"EUR/USD Price: ${eur_price:.5f}")
    print()

    # Test parameters
    collateral_usdc = 0.5  # Small amount to test
    leverage = 10
    pair_index = 2  # EUR/USD
    is_long = True

    # Convert to contract format
    collateral_scaled = int(collateral_usdc * PRECISION_10)
    open_price_scaled = int(eur_price * PRECISION_10)

    print(f"Opening LIMIT order:")
    print(f"  Collateral: {collateral_usdc} USDC")
    print(f"  Leverage: {leverage}x")
    print(f"  Pair: EUR/USD (index {pair_index})")
    print(f"  Direction: {'LONG' if is_long else 'SHORT'}")
    print(f"  Price: ${eur_price:.5f}")
    print()

    # Check USDC balance and allowance
    balance = usdc_contract.functions.balanceOf(account.address).call()
    allowance = usdc_contract.functions.allowance(
        account.address,
        trading_address
    ).call()

    print(f"USDC Balance: {balance / PRECISION_10:.2f}")
    print(f"USDC Allowance: {allowance / PRECISION_10:.2f}")
    print()

    if allowance < collateral_scaled:
        print("⚠️  Insufficient allowance, approving...")
        approve_tx = usdc_contract.functions.approve(
            trading_address,
            2**256 - 1  # Max approval
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 100000
        })

        signed = account.sign_transaction(approve_tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"✅ Approved: {tx_hash.hex()}")
        print()

    # Build trade struct
    trade = (
        collateral_scaled,      # collateral
        open_price_scaled,      # openPrice
        0,                      # tp (0 = no TP)
        0,                      # sl (0 = no SL)
        account.address,        # trader
        leverage,               # leverage
        pair_index,             # pairIndex
        0,                      # index (will be assigned)
        is_long                 # buy (True = long, False = short)
    )

    # Builder fee (0 = no builder fee)
    builder_fee = (
        "0x0000000000000000000000000000000000000000",  # builder address
        0  # builderFee
    )

    # Order type: LIMIT = 1
    order_type = LIMIT

    # Slippage: 0.5%
    slippage = int(0.5 * PRECISION_2)

    print("Transaction parameters:")
    print(f"  Trade: {trade}")
    print(f"  Builder Fee: {builder_fee}")
    print(f"  Order Type: {order_type} (LIMIT)")
    print(f"  Slippage: {slippage / PRECISION_2}%")
    print()

    try:
        # Estimate gas first
        print("Estimating gas...")
        gas_estimate = trading_contract.functions.openTrade(
            trade,
            builder_fee,
            order_type,
            slippage
        ).estimate_gas({'from': account.address})

        print(f"✅ Gas estimate: {gas_estimate:,}")
        print()

        # Build transaction
        print("Building transaction...")
        tx = trading_contract.functions.openTrade(
            trade,
            builder_fee,
            order_type,
            slippage
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': int(gas_estimate * 1.2)  # 20% buffer
        })

        # Sign and send
        print("Signing and sending...")
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

        print(f"✅ Transaction sent: {tx_hash.hex()}")
        print(f"   Waiting for confirmation...")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        print(f"✅ Transaction confirmed!")
        print(f"   Block: {receipt['blockNumber']}")
        print(f"   Gas used: {receipt['gasUsed']:,}")
        print(f"   Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
        print(f"   Explorer: https://sepolia.arbiscan.io/tx/{tx_hash.hex()}")
        print()

        if receipt['status'] == 1:
            print("🎉 LIMIT ORDER OPENED SUCCESSFULLY!")
        else:
            print("❌ Transaction failed")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print()

        # Try to decode revert reason
        if "execution reverted" in str(e).lower():
            print("Contract reverted. Common reasons:")
            print("  1. Insufficient USDC balance")
            print("  2. Price too far from market (for LIMIT)")
            print("  3. Pair trading disabled")
            print("  4. Leverage too high")
            print("  5. Min collateral not met")

        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
