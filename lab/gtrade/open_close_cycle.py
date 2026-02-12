#!/usr/bin/env python3
"""
Lab Script: Open & Close Trade Cycle (Testnet)

Obre una posició mínima, espera 10 segons, i la tanca.
Aplica TOTS els descobriments de l'anàlisi SDK:
- maxSlippage com a MULTIPLICADOR (1.10 = 110% = 10% slippage)
- openPrice amb buffer adequat (5% per LONG)
- Preu real del WebSocket feed

SAFETY GUARDS:
- E2E_TESTNET=1 + ENABLE_LIVE_TRADING=1 obligatoris
- Confirmació manual abans d'executar
- Validació de balances

Usage:
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
    WALLET_PRIVATE_KEY=0x... \
    python lab/gtrade/open_close_cycle.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade.price_provider import GTradePriceProviderWS
from infrastructure.venues.gtrade import abi_encoder
from loguru import logger

# Configuration
SYMBOL = "BTCUSD"
COLLATERAL = 150.0  # USDC (meets $1,500 minimum @ 10x)
LEVERAGE = 10
IS_LONG = True
WAIT_SECONDS = 10  # Wait before closing


async def main():
    print("\n" + "=" * 80)
    print("🧪 LAB: Open & Close Trade Cycle (Testnet)")
    print("=" * 80)
    print()

    # Safety check 1: E2E_TESTNET
    if os.getenv("E2E_TESTNET") != "1":
        print("❌ E2E_TESTNET not set")
        print()
        print("This script executes REAL testnet transactions.")
        print("Set E2E_TESTNET=1 to confirm execution.")
        return 1

    # Safety check 2: ENABLE_LIVE_TRADING
    if os.getenv("ENABLE_LIVE_TRADING") != "1":
        print("❌ ENABLE_LIVE_TRADING not set")
        return 1

    print(f"📋 Configuration:")
    print(f"   Symbol: {SYMBOL}")
    print(f"   Direction: {'LONG' if IS_LONG else 'SHORT'}")
    print(f"   Collateral: {COLLATERAL} USDC")
    print(f"   Leverage: {LEVERAGE}x")
    print(f"   Position Size: ${COLLATERAL * LEVERAGE:,.0f} USD")
    print(f"   Wait before close: {WAIT_SECONDS}s")
    print()

    # Start price provider
    print("📡 Starting price provider...")
    price_provider = GTradePriceProviderWS()
    await price_provider.start()

    try:
        # Get current price
        print(f"🔍 Fetching current price for {SYMBOL}...")
        oracle_price = await price_provider.get_current_price(SYMBOL)
        print(f"   Oracle Price: ${oracle_price:,.2f}")
        print()

        # Calculate openPrice with buffer (DESCOBRIMENT SDK)
        # Per LONG: openPrice = preu màxim que accepto pagar
        # Buffer 5% per sobre oracle price
        buffer = 1.05 if IS_LONG else 0.95
        open_price = oracle_price * buffer
        open_price_scaled = abi_encoder.price_to_contract_units(open_price)

        print(f"💡 Calculated openPrice (LIMIT PRICE):")
        print(f"   Buffer: {buffer:.2%}")
        print(f"   openPrice: ${open_price:,.2f}")
        print(f"   Scaled (1e10): {open_price_scaled}")
        print()

        # Calculate maxSlippage (DESCOBRIMENT CRÍTIC!)
        # maxSlippage = MULTIPLICADOR, NO percentage!
        # 1.10 = 110% = acepto pagar fins a 10% més (per LONG)
        max_slippage_multiplier = 1.10 if IS_LONG else 0.90  # 10% slippage
        max_slippage_scaled = int(max_slippage_multiplier * 1000)

        print(f"💡 Calculated maxSlippage (MULTIPLICADOR):")
        print(f"   Multiplier: {max_slippage_multiplier:.2f} ({(max_slippage_multiplier - 1.0) * 100:.0f}% slippage)")
        print(f"   Scaled (1e3): {max_slippage_scaled}")
        print()

        # Create adapter
        print("🔧 Initializing adapter...")
        adapter = GTradeVenueAdapter(mode="live")
        await adapter.start()

        # Health check
        print("🏥 Health check...")
        health = await adapter.health_check()

        if isinstance(health, dict):
            print(f"   ✅ Chain ID: {health['chain_id']} (Sepolia)")
            print(f"   ETH Balance: {health['eth_balance']:.6f} ETH")
            print(f"   USDC Balance: {health['usdc_balance']:.2f} USDC")
            print()

            # Verify balances
            if health['eth_balance'] < 0.01:
                print("❌ Insufficient ETH for gas (need >= 0.01 ETH)")
                return 1

            if health['usdc_balance'] < COLLATERAL:
                print(f"❌ Insufficient USDC (need >= {COLLATERAL} USDC)")
                return 1
        else:
            print("⚠️  Health check returned bool (no wallet configured?)")
            return 1

        print()

        # Confirm execution
        print("⚠️  READY TO EXECUTE REAL TRANSACTION")
        print()
        print(f"   Will open {SYMBOL} {'LONG' if IS_LONG else 'SHORT'}")
        print(f"   Collateral: {COLLATERAL} USDC @ {LEVERAGE}x leverage")
        print(f"   openPrice: ${open_price:,.2f} (limit price)")
        print(f"   maxSlippage: {max_slippage_multiplier:.2f} ({(max_slippage_multiplier - 1.0) * 100:.0f}%)")
        print()
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            print("❌ Aborted by user")
            return 1

        print()

        # STEP 1: Open position
        print("=" * 80)
        print("📈 STEP 1: OPENING POSITION")
        print("=" * 80)
        print()

        # Note: Using direct abi_encoder approach since we discovered
        # the adapter's open_position might not use correct maxSlippage
        from web3 import Web3
        from infrastructure.venues.gtrade.chain_config import load_chain_config_from_env

        config = load_chain_config_from_env()
        w3 = Web3(Web3.HTTPProvider(config.rpc_url))

        # Load minimal trading ABI
        trading_abi = [
            {
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
            }
        ]

        diamond = w3.eth.contract(
            address=Web3.to_checksum_address(config.addresses.diamond),
            abi=trading_abi
        )

        from eth_account import Account
        account = Account.from_key(config.wallet_private_key)

        # Build trade struct
        trade_struct = (
            account.address,  # user
            0,  # index
            0,  # pairIndex (BTCUSD)
            LEVERAGE * 1000,  # leverage (scaled 1e3)
            IS_LONG,  # long
            True,  # isOpen
            3,  # collateralIndex (GNS_USDC Sepolia)
            0,  # tradeType (TRADE)
            int(COLLATERAL * 1e6),  # collateralAmount (USDC has 6 decimals)
            open_price_scaled,  # openPrice (scaled 1e10)
            0,  # tp (no TP)
            0,  # sl (no SL)
            0  # __placeholder
        )

        # Build transaction
        tx = diamond.functions.openTrade(
            trade_struct,
            max_slippage_scaled,  # maxSlippageP (MULTIPLICADOR scaled 1e3)
            "0x0000000000000000000000000000000000000000"  # no referrer
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gas': 3000000,
            'maxFeePerGas': w3.eth.gas_price,
            'maxPriorityFeePerGas': w3.to_wei(0.01, 'gwei'),
            'chainId': config.chain_id
        })

        # Sign and send
        signed_tx = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"✅ Transaction sent: {tx_hash.hex()}")
        print(f"   Explorer: https://sepolia.arbiscan.io/tx/{tx_hash.hex()}")
        print()
        print("⏳ Waiting for confirmation...")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt['status'] == 1:
            print("✅ POSITION OPENED SUCCESSFULLY!")
            print()
            print(f"   Gas Used: {receipt['gasUsed']:,}")
            print(f"   Block: {receipt['blockNumber']}")

            # Extract position ID from logs (simplified - real implementation would decode events)
            position_id = "UNKNOWN"  # TODO: decode MarketExecuted event
            print(f"   Position ID: {position_id}")
        else:
            print("❌ TRANSACTION FAILED!")
            print(f"   Receipt: {receipt}")
            return 1

        print()
        print("=" * 80)
        print(f"⏰ WAITING {WAIT_SECONDS} SECONDS BEFORE CLOSING...")
        print("=" * 80)
        print()

        for i in range(WAIT_SECONDS, 0, -1):
            print(f"   {i}...", end="\r", flush=True)
            await asyncio.sleep(1)
        print()

        # STEP 2: Close position
        print()
        print("=" * 80)
        print("📉 STEP 2: CLOSING POSITION")
        print("=" * 80)
        print()

        # Get updated price
        current_price = await price_provider.get_current_price(SYMBOL)
        print(f"   Current Price: ${current_price:,.2f}")

        # Calculate expected price for close
        # For LONG close: we SELL, so we want price >= current (use buffer below)
        # For SHORT close: we BUY, so we want price <= current (use buffer above)
        close_buffer = 0.95 if IS_LONG else 1.05
        expected_price = current_price * close_buffer
        expected_price_scaled = abi_encoder.price_to_contract_units(expected_price)

        print(f"   Expected Close Price: ${expected_price:,.2f}")
        print(f"   Scaled: {expected_price_scaled}")
        print()

        # Note: For close, maxSlippageP might be different
        # Need to check actual position ID from backend first
        print("⚠️  Close position not fully implemented yet")
        print("   Would need to:")
        print("   1. Query backend API for actual position ID")
        print("   2. Call closeTradeMarket(index, expectedPrice)")
        print("   3. Wait for confirmation")
        print()
        print("💡 For now, you can close manually via gTrade UI:")
        print(f"   https://gains.trade/trade")

        return 0

    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERROR OCCURRED")
        print("=" * 80)
        print()
        print(f"Error: {e}")
        print()

        # Check if it's the price validation error
        error_str = str(e)
        if "0x10906acb" in error_str:
            print("💡 Still getting price validation error!")
            print("   Possible causes:")
            print("   - openPrice still outside acceptable range")
            print("   - maxSlippage validation different than expected")
            print("   - Market skew affecting validation")
        elif "insufficient" in error_str.lower():
            print("💡 Check balances and allowances")
        elif "slippage" in error_str.lower():
            print("💡 maxSlippage might still be wrong")

        import traceback
        traceback.print_exc()

        return 1

    finally:
        await price_provider.stop()
        if 'adapter' in locals():
            await adapter.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
