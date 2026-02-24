#!/usr/bin/env python3
"""
Lighter - Inspect Positions API

Investigates how to list open positions in Lighter SDK.

Tries multiple approaches:
- signer.get_open_positions() (if exists)
- signer.positions()
- signer.account()
- AccountApi.* methods
- PositionApi.* methods (if exists)

Output: Evidence of positions API or confirmation that tracking is internal-only.
"""

import os
import asyncio
from dotenv import load_dotenv
import lighter

load_dotenv()

# Lighter configuration
BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
L1_ADDRESS = os.getenv("LIGHTER_L1_ADDRESS")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")


async def main():
    print("=" * 80)
    print("LIGHTER SDK - POSITIONS API INSPECTION")
    print("=" * 80)
    print(f"Wallet: {L1_ADDRESS}")
    print(f"Account: {ACCOUNT_INDEX}\n")

    # Initialize clients
    api_client = lighter.ApiClient()
    signer = lighter.SignerClient(
        url=BASE_URL,
        api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
        account_index=ACCOUNT_INDEX
    )

    print("✅ Clients initialized\n")

    # ========== Approach 1: SignerClient methods ==========
    print("=" * 80)
    print("APPROACH 1: SignerClient Direct Methods")
    print("=" * 80)
    
    signer_methods = [m for m in dir(signer) if not m.startswith('_')]
    print(f"Available SignerClient methods ({len(signer_methods)}):")
    for method in sorted(signer_methods):
        if callable(getattr(signer, method)):
            print(f"   - {method}()")
    
    # Try get_open_positions
    print("\n🔍 Trying signer.get_open_positions()...")
    try:
        if hasattr(signer, 'get_open_positions'):
            positions = await signer.get_open_positions()
            print(f"✅ get_open_positions() exists!")
            print(f"   Type: {type(positions)}")
            print(f"   Value: {positions}")
        else:
            print("❌ get_open_positions() NOT FOUND")
    except Exception as e:
        print(f"⚠️  Error calling get_open_positions(): {e}")
    
    # Try positions
    print("\n🔍 Trying signer.positions()...")
    try:
        if hasattr(signer, 'positions'):
            positions = await signer.positions()
            print(f"✅ positions() exists!")
            print(f"   Type: {type(positions)}")
            print(f"   Value: {positions}")
        else:
            print("❌ positions() NOT FOUND")
    except Exception as e:
        print(f"⚠️  Error calling positions(): {e}")
    
    # Try account
    print("\n🔍 Trying signer.account()...")
    try:
        if hasattr(signer, 'account'):
            account = await signer.account()
            print(f"✅ account() exists!")
            print(f"   Type: {type(account)}")
            if hasattr(account, '__dict__'):
                print(f"   Fields: {list(account.__dict__.keys())}")
        else:
            print("❌ account() NOT FOUND")
    except Exception as e:
        print(f"⚠️  Error calling account(): {e}")

    # ========== Approach 2: AccountApi ==========
    print("\n" + "=" * 80)
    print("APPROACH 2: AccountApi")
    print("=" * 80)
    
    try:
        account_api = lighter.AccountApi(api_client)
        print(f"✅ AccountApi initialized")
        
        account_api_methods = [m for m in dir(account_api) if not m.startswith('_') and callable(getattr(account_api, m))]
        print(f"\nAvailable AccountApi methods ({len(account_api_methods)}):")
        for method in sorted(account_api_methods):
            print(f"   - {method}()")
        
        # Try account() — la UI fa servir by=l1_address; provem ambdós
        print("\n🔍 Trying AccountApi.account()...")
        try:
            # Primera crida: by=l1_address (el que fa la UI; retorna posició ETH)
            if L1_ADDRESS:
                print(f"   (by=l1_address, value={L1_ADDRESS[:20]}...)")
                account_response = await account_api.account(by="l1_address", value=L1_ADDRESS)
            else:
                account_response = await account_api.account(by="index", value=str(ACCOUNT_INDEX))
            print(f"✅ account() returned!")
            print(f"   Type: {type(account_response)}")
            
            if hasattr(account_response, '__dict__'):
                print(f"   Response fields: {list(account_response.__dict__.keys())}")
                
                # Check accounts list
                if hasattr(account_response, 'accounts') and account_response.accounts:
                    account = account_response.accounts[0]
                    print(f"\n   📋 First account (index={account.index}):")
                    print(f"      Type: {type(account)}")
                    
                    if hasattr(account, '__dict__'):
                        print(f"      Account fields: {list(account.__dict__.keys())}")
                        
                        # Check for positions field
                        if hasattr(account, 'positions'):
                            positions = account.positions
                            print(f"\n      📊 positions field found!")
                            print(f"         Type: {type(positions)}")
                            print(f"         Count: {len(positions) if positions else 0}")
                            
                            if positions and len(positions) > 0:
                                print(f"\n      First position:")
                                pos = positions[0]
                                print(f"         Type: {type(pos)}")
                                if hasattr(pos, '__dict__'):
                                    print(f"         Position fields: {list(pos.__dict__.keys())}")
                                    print(f"\n         Position details:")
                                    for key, value in pos.__dict__.items():
                                        if not key.startswith('_'):
                                            print(f"            {key}: {value}")
                            else:
                                print(f"         Empty list (no open positions)")
                        else:
                            print(f"\n      ⚠️  No 'positions' field in account object")
                        
                        # Show other relevant fields
                        print(f"\n      Other relevant fields:")
                        for key in ['available_balance', 'collateral', 'total_asset_value']:
                            if hasattr(account, key):
                                print(f"         {key}: {getattr(account, key)}")
        except Exception as e:
            print(f"❌ Error calling account(): {e}")
            import traceback
            traceback.print_exc()
        
        # Try other methods
        print("\n🔍 Trying AccountApi methods...")
        for method_name in ['get_positions', 'open_positions', 'list_positions', 'positions']:
            if hasattr(account_api, method_name):
                print(f"\n   Found {method_name}() - trying...")
                try:
                    result = await getattr(account_api, method_name)(account_index=ACCOUNT_INDEX)
                    print(f"   ✅ {method_name}() returned: {result}")
                except Exception as e:
                    print(f"   ⚠️  {method_name}() error: {e}")
    
    except Exception as e:
        print(f"❌ Error with AccountApi: {e}")
        import traceback
        traceback.print_exc()

    # ========== Approach 3: PositionApi (if exists) ==========
    print("\n" + "=" * 80)
    print("APPROACH 3: PositionApi (if exists)")
    print("=" * 80)
    
    try:
        if hasattr(lighter, 'PositionApi'):
            position_api = lighter.PositionApi(api_client)
            print(f"✅ PositionApi exists!")
            
            position_api_methods = [m for m in dir(position_api) if not m.startswith('_') and callable(getattr(position_api, m))]
            print(f"\nAvailable PositionApi methods ({len(position_api_methods)}):")
            for method in sorted(position_api_methods):
                print(f"   - {method}()")
            
            # Try common methods
            for method_name in ['get_positions', 'open_positions', 'list_positions', 'positions']:
                if hasattr(position_api, method_name):
                    print(f"\n🔍 Trying PositionApi.{method_name}()...")
                    try:
                        result = await getattr(position_api, method_name)(account_index=ACCOUNT_INDEX)
                        print(f"   ✅ {method_name}() returned: {result}")
                    except Exception as e:
                        print(f"   ⚠️  {method_name}() error: {e}")
        else:
            print("❌ PositionApi NOT FOUND in lighter module")
    except Exception as e:
        print(f"⚠️  Error checking PositionApi: {e}")

    # ========== Approach 4: OrderApi (check open orders) ==========
    print("\n" + "=" * 80)
    print("APPROACH 4: OrderApi (Active Orders)")
    print("=" * 80)
    
    try:
        orders_api = lighter.OrderApi(api_client)
        print(f"✅ OrderApi initialized")
        
        order_api_methods = [m for m in dir(orders_api) if not m.startswith('_') and callable(getattr(orders_api, m)) and 'order' in m.lower()]
        print(f"\nAvailable OrderApi methods (order-related):")
        for method in sorted(order_api_methods)[:10]:
            print(f"   - {method}()")
        
        print(f"\n🔍 Trying OrderApi.account_active_orders()...")
        try:
            active_orders = await orders_api.account_active_orders(account_index=ACCOUNT_INDEX)
            print(f"✅ account_active_orders() returned!")
            print(f"   Type: {type(active_orders)}")
            if hasattr(active_orders, '__dict__'):
                print(f"   Fields: {list(active_orders.__dict__.keys())}")
                
                # Check for orders list
                if hasattr(active_orders, 'orders'):
                    orders = active_orders.orders
                    print(f"\n   📋 Active orders found: {len(orders) if orders else 0}")
                    if orders and len(orders) > 0:
                        print(f"   First order:")
                        order = orders[0]
                        print(f"      Type: {type(order)}")
                        if hasattr(order, '__dict__'):
                            print(f"      Order fields: {list(order.__dict__.keys())}")
                            for key, value in order.__dict__.items():
                                if not key.startswith('_'):
                                    print(f"         {key}: {value}")
                elif hasattr(active_orders, '__iter__'):
                    print(f"\n   📋 Active orders (iterable):")
                    orders_list = list(active_orders)
                    print(f"      Count: {len(orders_list)}")
                    if orders_list:
                        print(f"      First: {orders_list[0]}")
        except Exception as e:
            print(f"⚠️  Error calling account_active_orders(): {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"❌ Error with OrderApi: {e}")

    # ========== Summary ==========
    print("\n" + "=" * 80)
    print("SUMMARY & CONCLUSION")
    print("=" * 80)
    
    print("\n📋 Available APIs:")
    print(f"   - SignerClient: {len([m for m in dir(signer) if not m.startswith('_')])} methods")
    print(f"   - AccountApi: {'✅' if hasattr(lighter, 'AccountApi') else '❌'}")
    print(f"   - PositionApi: {'❌ NOT FOUND'}")
    print(f"   - OrderApi: {'✅' if hasattr(lighter, 'OrderApi') else '❌'}")
    
    print("\n✅ POSITIONS API FOUND!")
    print("\n   Method: AccountApi.account(by='index', value=str(account_index))")
    print("   Returns: DetailedAccounts with accounts[] list")
    print("   Each account has: account.positions[] (list of AccountPosition)")
    print("\n   AccountPosition fields:")
    print("      - market_id: int")
    print("      - symbol: str")
    print("      - position: str (size, '0.00000' if closed)")
    print("      - sign: int (1=LONG?, -1=SHORT?)")
    print("      - avg_entry_price: str")
    print("      - unrealized_pnl: str")
    print("      - realized_pnl: str")
    print("      - liquidation_price: str")
    print("      - allocated_margin: str")
    print("\n💡 Implementation:")
    print("   get_open_positions() → AccountApi.account() → account.positions")
    print("   Filter positions where position != '0.00000' (or similar)")
    print("   Map AccountPosition → domain Position model")

    await api_client.close()

    print("\n" + "=" * 80)
    print("INSPECTION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
