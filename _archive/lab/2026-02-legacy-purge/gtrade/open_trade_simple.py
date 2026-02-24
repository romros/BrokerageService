#!/usr/bin/env python3
"""
Lab Script: Open Trade Simple (Testnet)

Versió simplificada que NO depèn de infrastructure/*.
Ús directe de web3.py + websockets per price feed.

Aplica descobriments SDK:
- maxSlippage = MULTIPLICADOR (1.10 = 10% slippage)
- openPrice = oracle × 1.05 (buffer 5%)

Usage:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
    WALLET_PRIVATE_KEY=0x... \
    RPC_URL=https://sepolia-rollup.arbitrum.io/rpc \
    python lab/gtrade/open_trade_simple.py
"""

import asyncio
import json
import os
import sys
from decimal import Decimal

try:
    from web3 import Web3
    from eth_account import Account
    import websockets
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print()
    print("Install:")
    print("  pip install web3 eth-account websockets")
    sys.exit(1)

# Config
SYMBOL = "BTCUSD"
COLLATERAL = 150.0  # USDC
LEVERAGE = 10
IS_LONG = True

# Addresses (Arbitrum Sepolia)
DIAMOND_ADDRESS = "0x4E796d9c5ca682fD37912D01d09EBed394f1B2d4"
USDC_ADDRESS = "0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d"

# WS Price Feed
WS_URL = "wss://feed-gtrade-arb.gainsnetwork.io/ws"


async def get_price_from_ws(symbol: str, timeout: float = 10.0) -> float:
    """Get current price from WebSocket feed"""
    print(f"📡 Connecting to WebSocket: {WS_URL}")

    async with websockets.connect(WS_URL) as ws:
        # Subscribe
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": ["!ticker@arr"],
            "id": 1
        }
        await ws.send(json.dumps(subscribe_msg))

        print(f"   Waiting for {symbol} price...")

        start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start) < timeout:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                # Parse ticker updates
                if isinstance(data, list):
                    for item in data:
                        if item.get('s') == symbol:
                            price = float(item.get('c', 0))
                            if price > 0:
                                print(f"   ✅ {symbol}: ${price:,.2f}")
                                return price

            except asyncio.TimeoutError:
                continue

        raise ValueError(f"Timeout waiting for {symbol} price")


def main():
    print("\n" + "=" * 80)
    print("🧪 LAB: Open Trade Simple (Testnet)")
    print("=" * 80)
    print()

    # Safety checks
    if os.getenv("E2E_TESTNET") != "1":
        print("❌ E2E_TESTNET not set")
        print("   Set E2E_TESTNET=1 to confirm testnet execution")
        return 1

    if os.getenv("ENABLE_LIVE_TRADING") != "1":
        print("❌ ENABLE_LIVE_TRADING not set")
        return 1

    # Support both private key and mnemonic
    private_key = os.getenv("WALLET_PRIVATE_KEY")
    mnemonic = os.getenv("WALLET_MNEMONIC")

    if not private_key and not mnemonic:
        print("❌ Neither WALLET_PRIVATE_KEY nor WALLET_MNEMONIC set")
        print("   Set one of:")
        print("     WALLET_PRIVATE_KEY=0x...")
        print("     WALLET_MNEMONIC=\"word1 word2 ... word12\"")
        return 1

    rpc_url = os.getenv("RPC_URL", "https://sepolia-rollup.arbitrum.io/rpc")

    print(f"📋 Configuration:")
    print(f"   Symbol: {SYMBOL}")
    print(f"   Direction: {'LONG' if IS_LONG else 'SHORT'}")
    print(f"   Collateral: {COLLATERAL} USDC")
    print(f"   Leverage: {LEVERAGE}x")
    print(f"   Position Size: ${COLLATERAL * LEVERAGE:,.0f} USD")
    print(f"   RPC: {rpc_url}")
    print()

    # Get price from WebSocket
    oracle_price = asyncio.run(get_price_from_ws(SYMBOL))
    print()

    # Calculate openPrice (DESCOBRIMENT SDK)
    buffer = 1.05 if IS_LONG else 0.95
    open_price = oracle_price * buffer
    open_price_scaled = int(open_price * 1e10)

    print(f"💡 Calculated openPrice (LIMIT PRICE):")
    print(f"   Oracle: ${oracle_price:,.2f}")
    print(f"   Buffer: {buffer:.2%}")
    print(f"   openPrice: ${open_price:,.2f}")
    print(f"   Scaled (1e10): {open_price_scaled}")
    print()

    # Calculate maxSlippage (DESCOBRIMENT CRÍTIC!)
    max_slippage_multiplier = 1.10 if IS_LONG else 0.90
    max_slippage_scaled = int(max_slippage_multiplier * 1000)

    print(f"💡 Calculated maxSlippage (MULTIPLICADOR):")
    print(f"   Multiplier: {max_slippage_multiplier:.2f}")
    print(f"   Slippage %: {abs(max_slippage_multiplier - 1.0) * 100:.0f}%")
    print(f"   Scaled (1e3): {max_slippage_scaled}")
    print()

    # Connect to RPC
    print("🔧 Connecting to RPC...")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        print("❌ Failed to connect to RPC")
        return 1

    chain_id = w3.eth.chain_id
    print(f"   ✅ Connected to chain: {chain_id}")

    if chain_id != 421614:
        print(f"   ⚠️  WARNING: Chain ID {chain_id} is NOT Sepolia (421614)!")
        response = input("   Continue anyway? [y/N]: ")
        if response.lower() != 'y':
            return 1

    # Load account
    if private_key:
        account = Account.from_key(private_key)
        print(f"   Wallet: {account.address} (from private key)")
    else:
        # Derive from mnemonic
        Account.enable_unaudited_hdwallet_features()
        account = Account.from_mnemonic(mnemonic)
        print(f"   Wallet: {account.address} (from mnemonic)")
    print()

    # Check balances
    print("🏥 Checking balances...")
    eth_balance = w3.eth.get_balance(account.address) / 1e18
    print(f"   ETH: {eth_balance:.6f}")

    if eth_balance < 0.01:
        print("   ❌ Insufficient ETH for gas (need >= 0.01 ETH)")
        return 1

    # Check USDC
    usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=usdc_abi)
    usdc_balance = usdc.functions.balanceOf(account.address).call() / 1e6

    print(f"   USDC: {usdc_balance:.2f}")

    if usdc_balance < COLLATERAL:
        print(f"   ❌ Insufficient USDC (need >= {COLLATERAL})")
        return 1

    print("   ✅ Balances OK")
    print()

    # Confirm
    print("⚠️  READY TO EXECUTE REAL TRANSACTION")
    print()
    print(f"   Will open {SYMBOL} {'LONG' if IS_LONG else 'SHORT'}")
    print(f"   openPrice: ${open_price:,.2f} (scaled: {open_price_scaled})")
    print(f"   maxSlippage: {max_slippage_multiplier} ({abs(max_slippage_multiplier - 1.0) * 100:.0f}%, scaled: {max_slippage_scaled})")
    print()
    response = input("Continue? [y/N]: ")
    if response.lower() != 'y':
        print("❌ Aborted")
        return 1

    print()

    # Build transaction
    print("📝 Building transaction...")

    trading_abi = [{
        "inputs": [
            {
                "components": [
                    {"name": "user", "type": "address"},
                    {"name": "index", "type": "uint32"},
                    {"name": "pairIndex", "type": "uint16"},
                    {"name": "leverage", "type": "uint24"},
                    {"name": "long", "type": "bool"},
                    {"name": "isOpen", "type": "bool"},
                    {"name": "collateralIndex", "type": "uint8"},
                    {"name": "tradeType", "type": "uint8"},
                    {"name": "collateralAmount", "type": "uint120"},
                    {"name": "openPrice", "type": "uint64"},
                    {"name": "tp", "type": "uint64"},
                    {"name": "sl", "type": "uint64"},
                    {"name": "__placeholder", "type": "uint256"}
                ],
                "name": "t",
                "type": "tuple"
            },
            {"name": "maxSlippageP", "type": "uint16"},
            {"name": "referrer", "type": "address"}
        ],
        "name": "openTrade",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }]

    diamond = w3.eth.contract(
        address=Web3.to_checksum_address(DIAMOND_ADDRESS),
        abi=trading_abi
    )

    trade_struct = (
        account.address,
        0,  # index
        0,  # pairIndex (BTCUSD)
        LEVERAGE * 1000,  # leverage scaled 1e3
        IS_LONG,
        True,  # isOpen
        3,  # collateralIndex (GNS_USDC Sepolia)
        0,  # tradeType (TRADE)
        int(COLLATERAL * 1e6),  # collateralAmount (USDC 1e6)
        open_price_scaled,  # openPrice scaled 1e10
        0,  # tp
        0,  # sl
        0  # __placeholder
    )

    print(f"   Trade struct: {trade_struct}")
    print(f"   maxSlippageP: {max_slippage_scaled}")
    print()

    tx = diamond.functions.openTrade(
        trade_struct,
        max_slippage_scaled,
        "0x0000000000000000000000000000000000000000"
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 3000000,
        'maxFeePerGas': w3.eth.gas_price,
        'maxPriorityFeePerGas': w3.to_wei(0.01, 'gwei'),
        'chainId': chain_id
    })

    print("📤 Signing and sending...")
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    print(f"✅ Transaction sent!")
    print(f"   TxHash: {tx_hash.hex()}")
    print(f"   Explorer: https://sepolia.arbiscan.io/tx/{tx_hash.hex()}")
    print()
    print("⏳ Waiting for confirmation...")

    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] == 1:
            print()
            print("=" * 80)
            print("✅ SUCCESS!")
            print("=" * 80)
            print()
            print(f"   Gas Used: {receipt['gasUsed']:,}")
            print(f"   Block: {receipt['blockNumber']}")
            print()
            print("💡 Descobriment confirmats:")
            print("   - maxSlippage com MULTIPLICADOR funciona!")
            print("   - openPrice amb buffer adequat acceptat!")
            print()
            return 0
        else:
            print()
            print("=" * 80)
            print("❌ TRANSACTION FAILED")
            print("=" * 80)
            print()
            print(f"   Receipt: {receipt}")
            return 1

    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERROR")
        print("=" * 80)
        print()
        print(f"   {e}")

        error_str = str(e)
        if "0x10906acb" in error_str:
            print()
            print("💡 Still price validation error!")
            print("   Possible causes:")
            print("   - openPrice calculation still wrong")
            print("   - maxSlippage interpretation different")
            print("   - Need price impact calculation")

        return 1


if __name__ == "__main__":
    sys.exit(main())
