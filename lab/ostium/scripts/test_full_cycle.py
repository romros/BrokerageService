#!/usr/bin/env python3
"""
Complete trading cycle test: Open → Set SL/TP → Monitor → Close

Usage: python test_full_cycle.py
"""

import os
import asyncio
import time
from decimal import Decimal
from dotenv import load_dotenv
from ostium_python_sdk import OstiumSDK, NetworkConfig
from eth_account import Account

async def main():
    print("\n" + "=" * 80)
    print("🧪 FULL TRADING CYCLE TEST: EURUSD")
    print("=" * 80)
    print()

    # Config
    ASSET_TYPE = 2  # EUR
    COLLATERAL = 100
    LEVERAGE = 10
    IS_LONG = True

    # Safety checks
    load_dotenv()
    if os.getenv('E2E_TESTNET') != '1' or os.getenv('ENABLE_LIVE_TRADING') != '1':
        print("❌ Safety flags not set")
        return

    private_key = os.getenv('PRIVATE_KEY')
    if not private_key:
        print("❌ PRIVATE_KEY not set")
        return

    try:
        # Initialize SDK
        config = NetworkConfig.testnet()
        sdk = OstiumSDK(config, private_key)

        account = Account.from_key(private_key)
        address = account.address

        print(f"Wallet: {address}")
        print(f"Asset: EUR/USD")
        print(f"Direction: {'LONG ⬆️' if IS_LONG else 'SHORT ⬇️'}")
        print(f"Collateral: {COLLATERAL} USDC @ {LEVERAGE}x")
        print()

        # === PHASE 1: GET PRICE ===
        print("=" * 80)
        print("PHASE 1: GET CURRENT PRICE")
        print("=" * 80)
        print()

        eur_price, _, _ = await sdk.price.get_price("EUR", "USD")
        print(f"EUR/USD Price: ${eur_price:.5f}")
        print()

        # Calculate SL/TP (example: 1% TP, 0.5% SL)
        if IS_LONG:
            tp_price = eur_price * 1.01  # 1% profit
            sl_price = eur_price * 0.995  # 0.5% loss
        else:
            tp_price = eur_price * 0.99
            sl_price = eur_price * 1.005

        print(f"Target TP: ${tp_price:.5f} ({'+1%' if IS_LONG else '-1%'})")
        print(f"Target SL: ${sl_price:.5f} ({'-0.5%' if IS_LONG else '+0.5%'})")
        print()

        # === PHASE 2: OPEN POSITION ===
        print("=" * 80)
        print("PHASE 2: OPEN POSITION")
        print("=" * 80)
        print()

        sdk.ostium.set_slippage_percentage(Decimal('0.5'))  # 0.5% slippage

        trade_params = {
            'collateral': COLLATERAL,
            'leverage': LEVERAGE,
            'asset_type': ASSET_TYPE,
            'direction': IS_LONG,
            'order_type': 'MARKET'
        }

        print("Opening position...")
        start_time = time.time()

        try:
            receipt = sdk.ostium.perform_trade(trade_params, at_price=eur_price)
            open_time = time.time() - start_time

            print(f"✅ Position opened!")

            # Extract actual receipt
            tx_receipt = receipt.get('receipt', receipt)
            order_id = receipt.get('order_id', 'N/A')

            print(f"   Order ID: {order_id}")

            if isinstance(tx_receipt, dict):
                tx_hash = tx_receipt.get('transactionHash', tx_receipt.get('hash', 'N/A'))
                if hasattr(tx_hash, 'hex'):
                    tx_hash = tx_hash.hex()
                print(f"   TX: {tx_hash}")
                print(f"   Block: {tx_receipt.get('blockNumber', 'N/A')}")
                print(f"   Gas: {tx_receipt.get('gasUsed', 'N/A')}")
                print(f"   Explorer: https://sepolia.arbiscan.io/tx/{tx_hash}")
            else:
                print(f"   TX Receipt: {tx_receipt}")

            print(f"   Time: {open_time:.2f}s")
            print()

            # Wait for indexing (up to 120s)
            print("⏳ Waiting for subgraph indexing (may take 120s)...")
            print()

            max_wait = 120
            wait_interval = 10
            elapsed = 0
            open_trades = []

            # === PHASE 3: GET OPEN TRADES ===
            print("=" * 80)
            print("PHASE 3: QUERY OPEN POSITIONS")
            print("=" * 80)
            print()

            while elapsed < max_wait:
                await asyncio.sleep(wait_interval)
                elapsed += wait_interval

                print(f"[{elapsed}s] Checking subgraph...")
                open_trades = await sdk.subgraph.get_open_trades(address)

                if open_trades:
                    print(f"✅ Found {len(open_trades)} open trades!")
                    break
                else:
                    print(f"⏳ Not indexed yet...")

            print()

            if not open_trades:
                print("❌ Trade not found after 120s")
                print("⚠️  Subgraph too slow - use Web UI to close")
                print("   https://testnet.ostium.io/")
                return

            # Get latest trade
            latest_trade = open_trades[-1]
            pair_id = latest_trade.get('pairId')
            trade_index = latest_trade.get('index')

            print(f"Trade details:")
            print(f"  Pair ID: {pair_id}")
            print(f"  Trade Index: {trade_index}")
            print(f"  Direction: {'LONG ⬆️' if latest_trade.get('isLong') else 'SHORT ⬇️'}")
            print(f"  Collateral: {latest_trade.get('collateral')} USDC")
            print(f"  Leverage: {latest_trade.get('leverage')}x")
            print(f"  Open Price: ${latest_trade.get('openPrice')}")
            print()

            # === PHASE 4: SET SL/TP ===
            print("=" * 80)
            print("PHASE 4: SET STOP LOSS & TAKE PROFIT")
            print("=" * 80)
            print()

            try:
                print(f"Setting TP to ${tp_price:.5f}...")
                tp_receipt = sdk.ostium.update_tp(pair_id, trade_index, tp_price)
                print(f"✅ Take Profit set! TX: {tp_receipt['transactionHash'].hex()}")
                print()

                print(f"Setting SL to ${sl_price:.5f}...")
                sl_receipt = sdk.ostium.update_sl(pair_id, trade_index, sl_price)
                print(f"✅ Stop Loss set! TX: {sl_receipt['transactionHash'].hex()}")
                print()

            except Exception as e:
                print(f"⚠️  SL/TP update failed: {str(e)}")
                print("   (May not be supported on testnet or SDK version)")
                print()

            # === PHASE 5: MONITOR ===
            print("=" * 80)
            print("PHASE 5: MONITOR POSITION (15 seconds)")
            print("=" * 80)
            print()

            for i in range(5):
                await asyncio.sleep(3)

                try:
                    # Get current price
                    current_price, _, _ = await sdk.price.get_price("EUR", "USD")
                    price_change = ((current_price - eur_price) / eur_price) * 100

                    # Try to get metrics
                    try:
                        metrics = await sdk.get_open_trade_metrics(pair_id, trade_index)
                        pnl = metrics.get('unrealizedPnl', 0)
                        pnl_pct = metrics.get('unrealizedPnlPercentage', 0)
                        print(f"[{i*3}s] Price: ${current_price:.5f} ({price_change:+.2f}%) | P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
                    except:
                        print(f"[{i*3}s] Price: ${current_price:.5f} ({price_change:+.2f}%) | P&L: N/A")

                except Exception as e:
                    print(f"[{i*3}s] Monitoring error: {str(e)}")

            print()

            # === PHASE 6: CLOSE POSITION ===
            print("=" * 80)
            print("PHASE 6: CLOSE POSITION")
            print("=" * 80)
            print()

            print("Closing position...")
            start_time = time.time()

            close_receipt = sdk.ostium.close_trade(pair_id, trade_index)
            close_time = time.time() - start_time

            print(f"✅ Position closed!")
            print(f"   TX: {close_receipt['transactionHash'].hex()}")
            print(f"   Block: {close_receipt['blockNumber']}")
            print(f"   Gas: {close_receipt['gasUsed']}")
            print(f"   Time: {close_time:.2f}s")
            print(f"   Explorer: https://sepolia.arbiscan.io/tx/{close_receipt['transactionHash'].hex()}")
            print()

            # === SUMMARY ===
            print("=" * 80)
            print("✅ FULL CYCLE COMPLETED")
            print("=" * 80)
            print()
            print(f"Open TX:  {receipt['transactionHash'].hex()}")
            print(f"Close TX: {close_receipt['transactionHash'].hex()}")
            print(f"Total gas: {receipt['gasUsed'] + close_receipt['gasUsed']}")
            print()

            # Final output
            output = {
                'success': True,
                'asset': 'EURUSD',
                'direction': 'LONG' if IS_LONG else 'SHORT',
                'collateral': COLLATERAL,
                'leverage': LEVERAGE,
                'open_tx': receipt['transactionHash'].hex(),
                'close_tx': close_receipt['transactionHash'].hex(),
                'open_gas': receipt['gasUsed'],
                'close_gas': close_receipt['gasUsed'],
                'total_gas': receipt['gasUsed'] + close_receipt['gasUsed'],
                'pair_id': pair_id,
                'trade_index': trade_index
            }

            print("JSON Output:")
            import json
            print(json.dumps(output, indent=2))

        except Exception as trade_error:
            print(f"❌ Trade execution failed: {str(trade_error)}")
            import traceback
            traceback.print_exc()
            return

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
