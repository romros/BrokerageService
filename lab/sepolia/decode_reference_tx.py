#!/usr/bin/env python3
"""
Lab Script: Decode Reference Transaction

Descarrega i decodifica una transacció exitosa de referència per entendre
els paràmetres exactes que funcionen.

Usage:
    ./test.sh lab/sepolia/decode_reference_tx.py

Output:
    lab/sepolia/artifacts/reference_tx.json
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from pprint import pprint

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web3 import AsyncWeb3
from loguru import logger

# Reference transaction (user's successful openTrade)
REFERENCE_TX_HASH = "0xced130245364a21c052cd913a95138dca230356a5c52dd485ffe1cd6b47f1d3c"
RPC_URL = os.getenv("ARBITRUM_RPC_URL", "https://sepolia-rollup.arbitrum.io/rpc")

# Load ABI
ABI_PATH = project_root / "infrastructure" / "venues" / "gtrade" / "abi" / "GNSMultiCollatDiamond.json"


async def main():
    print("\n" + "=" * 80)
    print("🔬 LAB: Decode Reference Transaction")
    print("=" * 80)
    print()
    print(f"TxHash: {REFERENCE_TX_HASH}")
    print(f"RPC: {RPC_URL}")
    print()

    # Connect to RPC
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(RPC_URL))

    # Get transaction
    print("📥 Fetching transaction...")
    tx = await w3.eth.get_transaction(REFERENCE_TX_HASH)

    if not tx:
        print(f"❌ Transaction not found: {REFERENCE_TX_HASH}")
        return 1

    print(f"✅ Transaction found")
    print(f"   Block: {tx['blockNumber']}")
    print(f"   From: {tx['from']}")
    print(f"   To: {tx['to']}")
    print(f"   Value: {tx['value']} wei")
    print(f"   Gas: {tx['gas']}")
    print()

    # Get receipt
    print("📥 Fetching receipt...")
    receipt = await w3.eth.get_transaction_receipt(REFERENCE_TX_HASH)

    print(f"✅ Receipt found")
    print(f"   Status: {'SUCCESS' if receipt['status'] == 1 else 'FAILED'}")
    print(f"   Gas Used: {receipt['gasUsed']}")
    print()

    # Load ABI and decode input
    print("🔍 Decoding input data...")

    with open(ABI_PATH) as f:
        abi_json = json.load(f)

    # Extract ABI array (hardhat artifact format)
    if isinstance(abi_json, dict) and 'abi' in abi_json:
        abi = abi_json['abi']
    else:
        abi = abi_json

    # Create contract instance
    contract = w3.eth.contract(address=tx['to'], abi=abi)

    # Decode input
    try:
        func_obj, func_params = contract.decode_function_input(tx['input'])

        print(f"✅ Function: {func_obj.fn_name}")
        print()
        print("📋 Parameters:")
        print()

        # Pretty print parameters
        for key, value in func_params.items():
            print(f"   {key}: {value}")

            # If it's the Trade struct, decode it
            if key == 't' and hasattr(value, '_asdict'):
                print()
                print("   📦 Trade Struct (decoded):")
                trade_dict = value._asdict() if hasattr(value, '_asdict') else dict(value)
                for field, val in trade_dict.items():
                    print(f"      {field}: {val}")

        print()

        # Convert to human-readable values
        if 't' in func_params:
            trade = func_params['t']
            print("🔢 Human-Readable Values:")
            print()

            # Handle both tuple and dict
            if hasattr(trade, '_asdict'):
                t = trade._asdict()
            else:
                t = dict(trade)

            print(f"   Pair Index: {t.get('pairIndex', 'N/A')}")

            # Leverage (scaled 1e3)
            leverage_raw = t.get('leverage', 0)
            leverage = leverage_raw / 1000 if leverage_raw else 0
            print(f"   Leverage: {leverage}x (raw: {leverage_raw})")

            # Open Price (scaled 1e10)
            open_price_raw = t.get('openPrice', 0)
            open_price = open_price_raw / 1e10 if open_price_raw else 0
            print(f"   Open Price: ${open_price:,.4f} (raw: {open_price_raw})")

            # TP (scaled 1e10)
            tp_raw = t.get('tp', 0)
            tp = tp_raw / 1e10 if tp_raw else 0
            print(f"   Take Profit: ${tp:,.4f} (raw: {tp_raw})" if tp else "   Take Profit: None")

            # SL (scaled 1e10)
            sl_raw = t.get('sl', 0)
            sl = sl_raw / 1e10 if sl_raw else 0
            print(f"   Stop Loss: ${sl:,.4f} (raw: {sl_raw})" if sl else "   Stop Loss: None")

            # Collateral (scaled 1e6 for USDC)
            collateral_raw = t.get('collateralAmount', 0)
            collateral = collateral_raw / 1e6 if collateral_raw else 0
            print(f"   Collateral: {collateral:,.2f} USDC (raw: {collateral_raw})")

            # Position size
            position_size = collateral * leverage
            print(f"   Position Size: ${position_size:,.2f} USD")

            # Other fields
            print(f"   Collateral Index: {t.get('collateralIndex', 'N/A')}")
            print(f"   Long: {t.get('long', 'N/A')}")

            # MaxSlippageP (basis points)
            max_slippage_raw = t.get('maxSlippageP', 0)
            max_slippage_pct = max_slippage_raw / 100 if max_slippage_raw else 0
            print(f"   Max Slippage: {max_slippage_pct:.2f}% (raw: {max_slippage_raw} bps)")

            print(f"   Trade Index: {t.get('index', 'N/A')}")
            print(f"   User: {t.get('user', 'N/A')}")

        # Save to artifacts
        output_path = Path(__file__).parent / "artifacts" / "reference_tx.json"
        output_data = {
            "tx_hash": REFERENCE_TX_HASH,
            "block_number": tx['blockNumber'],
            "from": tx['from'],
            "to": tx['to'],
            "function": func_obj.fn_name,
            "parameters": {
                key: (
                    value._asdict() if hasattr(value, '_asdict')
                    else dict(value) if isinstance(value, (tuple, list))
                    else str(value)
                )
                for key, value in func_params.items()
            },
            "gas_used": receipt['gasUsed'],
            "status": receipt['status'],
        }

        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)

        print()
        print(f"✅ Saved to: {output_path}")

        return 0

    except Exception as e:
        print(f"❌ Failed to decode: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
