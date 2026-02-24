#!/usr/bin/env python3
"""
Lighter - Inspect Write Operation Responses

Investigates SDK response structures for:
- create_market_order() (open)
- create_market_order() (close with reduce_only)
- create_order() (limit POST_ONLY)
- cancel_order()

Saves JSON outputs to lab/out/*.json for production reference.
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import lighter

load_dotenv()

# Lighter configuration
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

# Output directory
OUT_DIR = Path(__file__).parent.parent.parent / "out"
OUT_DIR.mkdir(exist_ok=True)


def obj_to_dict(obj):
    """Convert object to dict (handles nested objects)"""
    if obj is None:
        return None
    
    if hasattr(obj, '__dict__'):
        result = {}
        for key, value in obj.__dict__.items():
            if not key.startswith('_'):
                # Recursively convert nested objects
                if hasattr(value, '__dict__'):
                    result[key] = obj_to_dict(value)
                elif isinstance(value, (list, tuple)):
                    result[key] = [obj_to_dict(item) if hasattr(item, '__dict__') else item for item in value]
                else:
                    result[key] = value
        return result
    
    return str(obj)


def save_response(name: str, create_order, tx_resp, err):
    """Save response to JSON file"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "operation": name,
        "create_order": obj_to_dict(create_order),
        "tx_response": obj_to_dict(tx_resp),
        "error": str(err) if err else None,
    }
    
    # Extract key fields for quick reference
    if create_order:
        output["create_order_type"] = str(type(create_order))
        if hasattr(create_order, '__dict__'):
            output["create_order_fields"] = list(create_order.__dict__.keys())
    
    if tx_resp:
        output["tx_response_type"] = str(type(tx_resp))
        if hasattr(tx_resp, '__dict__'):
            output["tx_response_fields"] = list(tx_resp.__dict__.keys())
            # Extract tx_hash if exists
            if hasattr(tx_resp, 'tx_hash'):
                output["tx_hash"] = tx_resp.tx_hash
    
    filepath = OUT_DIR / f"{name}.json"
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"   💾 Saved to: {filepath}")
    return output


async def main():
    print("=" * 80)
    print("LIGHTER SDK - WRITE OPERATIONS RESPONSE INSPECTION")
    print("=" * 80)
    print(f"Wallet: {L1_ADDRESS}")
    print(f"Account: {ACCOUNT_INDEX}")
    print(f"Output dir: {OUT_DIR}\n")

    # Initialize clients
    api_client = lighter.ApiClient()
    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX
    )

    print("✅ Clients initialized\n")

    # Get current price for reference
    print("=" * 80)
    print("STEP 0: GET CURRENT MARKET PRICE")
    print("=" * 80)
    
    try:
        orders_api = lighter.OrderApi(api_client)
        order_books = await orders_api.order_books()
        
        eth_market = None
        for ob in order_books.order_books:
            if ob.market_id == 0:  # ETH
                eth_market = ob
                break
        
        if eth_market:
            # Get orderbook for price
            orderbook = await orders_api.order_book_orders(market_id=0, limit=5)
            if orderbook.bids and orderbook.asks:
                bid = float(orderbook.bids[0].price)
                ask = float(orderbook.asks[0].price)
                mid = (bid + ask) / 2
                print(f"📊 ETH/USDC Market:")
                print(f"   Bid: ${bid:.2f}")
                print(f"   Ask: ${ask:.2f}")
                print(f"   Mid: ${mid:.2f}\n")
                current_price = mid
            else:
                current_price = 1950.0  # Fallback
                print(f"⚠️  No orderbook data, using fallback: ${current_price:.2f}\n")
        else:
            current_price = 1950.0
            print(f"⚠️  ETH market not found, using fallback: ${current_price:.2f}\n")
    except Exception as e:
        print(f"⚠️  Could not get market price: {e}")
        current_price = 1950.0
        print(f"   Using fallback: ${current_price:.2f}\n")

    # ========== A1: Market OPEN Order ==========
    print("=" * 80)
    print("A1: MARKET OPEN ORDER (Small Size)")
    print("=" * 80)
    
    try:
        order_size_eth = 0.01  # Small size
        price_usd = current_price
        
        print(f"Placing MARKET OPEN order...")
        print(f"   Market: ETH/USDC (market_index=0)")
        print(f"   Side: LONG (is_ask=False)")
        print(f"   Size: {order_size_eth} ETH")
        print(f"   Price: ${price_usd:.2f}")
        print(f"   reduce_only: False\n")

        create_order, send_tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=int(order_size_eth * 1_000_000),  # ×1e6
            avg_execution_price=int(price_usd * 1_000_000),  # ×1e6
            is_ask=False,  # LONG
            reduce_only=False
        )

        if err:
            print(f"❌ ORDER FAILED: {err}\n")
            save_response("market_open", create_order, send_tx_resp, err)
        else:
            print("✅ ORDER SUBMITTED!")
            print(f"\nCreate Order Type: {type(create_order)}")
            if create_order and hasattr(create_order, '__dict__'):
                print(f"Create Order Fields: {list(create_order.__dict__.keys())}")
                for key, value in create_order.__dict__.items():
                    if not key.startswith('_'):
                        print(f"   {key}: {value}")
            
            print(f"\nTX Response Type: {type(send_tx_resp)}")
            if send_tx_resp and hasattr(send_tx_resp, '__dict__'):
                print(f"TX Response Fields: {list(send_tx_resp.__dict__.keys())}")
                for key, value in send_tx_resp.__dict__.items():
                    if not key.startswith('_'):
                        print(f"   {key}: {value}")
            
            if send_tx_resp and hasattr(send_tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {send_tx_resp.tx_hash}")
            
            output = save_response("market_open", create_order, send_tx_resp, err)
            print(f"\n✅ MarketOrder response fields: {output.get('create_order_fields', [])}")
            print(f"✅ TX response fields: {output.get('tx_response_fields', [])}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    # Wait a bit
    print("\n⏳ Waiting 3 seconds...\n")
    await asyncio.sleep(3)

    # ========== A2: Market CLOSE Order (reduce_only) ==========
    print("=" * 80)
    print("A2: MARKET CLOSE ORDER (reduce_only=True)")
    print("=" * 80)
    
    try:
        order_size_eth = 0.01  # Same size
        price_usd = current_price
        
        print(f"Placing MARKET CLOSE order...")
        print(f"   Market: ETH/USDC (market_index=0)")
        print(f"   Side: SHORT/SELL (is_ask=True) - to close LONG")
        print(f"   Size: {order_size_eth} ETH")
        print(f"   Price: ${price_usd:.2f}")
        print(f"   reduce_only: True\n")

        create_order, send_tx_resp, err = await signer.create_market_order(
            market_index=0,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=int(order_size_eth * 1_000_000),  # ×1e6
            avg_execution_price=int(price_usd * 1_000_000),  # ×1e6
            is_ask=True,  # SELL to close LONG
            reduce_only=True  # CRITICAL
        )

        if err:
            print(f"❌ ORDER FAILED: {err}\n")
            save_response("market_close", create_order, send_tx_resp, err)
        else:
            print("✅ ORDER SUBMITTED!")
            print(f"\nCreate Order Type: {type(create_order)}")
            if create_order and hasattr(create_order, '__dict__'):
                print(f"Create Order Fields: {list(create_order.__dict__.keys())}")
            
            print(f"\nTX Response Type: {type(send_tx_resp)}")
            if send_tx_resp and hasattr(send_tx_resp, '__dict__'):
                print(f"TX Response Fields: {list(send_tx_resp.__dict__.keys())}")
            
            if send_tx_resp and hasattr(send_tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {send_tx_resp.tx_hash}")
            
            output = save_response("market_close", create_order, send_tx_resp, err)
            print(f"\n✅ MarketClose response fields: {output.get('create_order_fields', [])}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    # Wait a bit
    print("\n⏳ Waiting 3 seconds...\n")
    await asyncio.sleep(3)

    # ========== A3: Limit POST_ONLY Order (far from price) ==========
    print("=" * 80)
    print("A3: LIMIT POST_ONLY ORDER (Far from Market)")
    print("=" * 80)
    
    # Store client_order_index for cancellation (CRITICAL: cancel uses this!)
    client_order_index_limit = int(asyncio.get_event_loop().time() * 1000) % 1000000
    
    try:
        order_size_eth = 0.01
        limit_price_usd = current_price * 0.8  # 20% below market (won't fill)
        
        print(f"Placing LIMIT POST_ONLY order...")
        print(f"   Market: ETH/USDC (market_index=0)")
        print(f"   Side: BUY (is_ask=False)")
        print(f"   Size: {order_size_eth} ETH")
        print(f"   Limit Price: ${limit_price_usd:.2f} (below market)")
        print(f"   Type: POST_ONLY")
        print(f"   client_order_index: {client_order_index_limit}\n")

        create_order, tx_resp, err = await signer.create_order(
            market_index=0,
            client_order_index=client_order_index_limit,
            price=int(limit_price_usd * 100),  # ×100 for limit
            base_amount=int(order_size_eth * 10_000),  # ×1e4 for limit
            is_ask=False,  # BUY
            time_in_force=signer.ORDER_TIME_IN_FORCE_POST_ONLY,
            order_type=signer.ORDER_TYPE_LIMIT
        )

        if err:
            print(f"❌ ORDER FAILED: {err}\n")
            save_response("limit_place", create_order, tx_resp, err)
        else:
            print("✅ ORDER PLACED!")
            print(f"\nCreate Order Type: {type(create_order)}")
            if create_order and hasattr(create_order, '__dict__'):
                print(f"Create Order Fields: {list(create_order.__dict__.keys())}")
                for key, value in create_order.__dict__.items():
                    if not key.startswith('_'):
                        print(f"   {key}: {value}")
                        if key == 'order_id':
                            limit_order_id = value
            
            print(f"\nTX Response Type: {type(tx_resp)}")
            if tx_resp and hasattr(tx_resp, '__dict__'):
                print(f"TX Response Fields: {list(tx_resp.__dict__.keys())}")
            
            if tx_resp and hasattr(tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {tx_resp.tx_hash}")
            
            if limit_order_id:
                print(f"\n📋 Order ID: {limit_order_id}")
            
            output = save_response("limit_place", create_order, tx_resp, err)
            print(f"\n✅ LimitOrder response fields: {output.get('create_order_fields', [])}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

    # Wait a bit before cancel
    print("\n⏳ Waiting 3 seconds before cancel...\n")
    await asyncio.sleep(3)

    # ========== A4: Cancel Order ==========
    # CRITICAL FINDING from official examples (create_modify_cancel_order_http.py):
    #   - modify_order(market_index, order_index=123, ...) uses client_order_index
    #   - cancel_order(market_index, order_index=123, ...) uses client_order_index
    # So we can cancel using the same client_order_index we passed to create_order!
    
    print("=" * 80)
    print("A4: CANCEL ORDER (Using client_order_index)")
    print("=" * 80)
    
    # Use the same client_order_index we used to create the limit order
    print(f"Cancelling order with client_order_index={client_order_index_limit}...")
    print("   💡 CRITICAL: cancel_order() uses order_index=client_order_index")
    print("   (NOT order_id from server - use the same index you passed to create_order)\n")

    try:
        cancel_tx, tx_resp, err = await signer.cancel_order(
            market_index=0,  # ETH/USDC market
            order_index=client_order_index_limit  # Use the same client_order_index!
        )

        if err:
            print(f"⚠️  Cancel error: {err}\n")
            print("   This might be expected if:")
            print("   - Order was already filled")
            print("   - Order doesn't exist")
            print("   - Nonce issue (need to manage nonces properly)")
            save_response("limit_cancel", cancel_tx, tx_resp, err)
        else:
            print("✅ ORDER CANCELLED!")
            print(f"\nCancel TX Type: {type(cancel_tx)}")
            if cancel_tx and hasattr(cancel_tx, '__dict__'):
                print(f"Cancel TX Fields: {list(cancel_tx.__dict__.keys())}")
            
            print(f"\nTX Response Type: {type(tx_resp)}")
            if tx_resp and hasattr(tx_resp, '__dict__'):
                print(f"TX Response Fields: {list(tx_resp.__dict__.keys())}")
            
            if tx_resp and hasattr(tx_resp, 'tx_hash'):
                print(f"\n📝 TX Hash: {tx_resp.tx_hash}")
            
            output = save_response("limit_cancel", cancel_tx, tx_resp, err)
            print(f"\n✅ Cancel response fields documented")
            print("\n💡 CRITICAL FINDING CONFIRMED:")
            print("   cancel_order(market_index, order_index=client_order_index)")
            print("   modify_order(market_index, order_index=client_order_index)")
            print("   Both use client_order_index (NOT order_id from server)")

    except Exception as e:
        print(f"❌ Error cancelling: {e}")
        import traceback
        traceback.print_exc()
        print("\n💡 Note: cancel_order() signature:")
        print("   signer.cancel_order(market_index, order_index=client_order_index)")
        save_response("limit_cancel", None, None, f"Exception: {e}")

    await api_client.close()

    print("\n" + "=" * 80)
    print("INSPECTION COMPLETE")
    print("=" * 80)
    print(f"\n📁 Output files saved to: {OUT_DIR}")
    print("   - market_open.json")
    print("   - market_close.json")
    print("   - limit_place.json")
    print("   - limit_cancel.json")


if __name__ == "__main__":
    asyncio.run(main())
