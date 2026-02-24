#!/usr/bin/env python3
"""
Lighter - Test accountActiveOrders with Auth Token

Tests accountActiveOrders endpoint with proper authentication,
trying both API keys (0 and 1) as seen in the UI.
"""
import os
import asyncio
import json
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

async def test_account_active_orders():
    print("=" * 80)
    print("TEST: accountActiveOrders amb Auth Token")
    print("=" * 80)
    print(f"Account Index: {ACCOUNT_INDEX}")
    print(f"Base URL: {BASE_URL}")
    print()
    
    # Provar amb API Key Index 1 (la que tenim configurada)
    print(f"--- Provant amb API Key Index {API_KEY_INDEX} ---")
    
    try:
        # Crear SignerClient
        signer = lighter.SignerClient(
            url=BASE_URL,
            api_private_keys={API_KEY_INDEX: API_PRIVATE_KEY},
            account_index=ACCOUNT_INDEX
        )
        print("✅ SignerClient creat")
        
        # Generar auth token
        print("\n1. Generant auth token...")
        auth_token, err = signer.create_auth_token_with_expiry(
            deadline=10 * 60,  # 10 minuts
            api_key_index=API_KEY_INDEX
        )
        
        if err:
            print(f"   ❌ Error generant auth token: {err}")
            return
        
        print(f"   ✅ Auth token generat!")
        print(f"   Token (primeres 50 chars): {auth_token[:50]}...")
        print()
        
        # Crear ApiClient i OrderApi
        api_client = lighter.ApiClient()
        orders_api = lighter.OrderApi(api_client)
        
        # Provar amb market_id=0 (ETH)
        print("2. Obtenint ordres actives per ETH (market_id=0)...")
        active_orders = await orders_api.account_active_orders(
            account_index=ACCOUNT_INDEX,
            market_id=0,  # ETH/USDC
            auth=auth_token  # Passar auth token
        )
        
        print("   ✅ Success!")
        print(f"   Type: {type(active_orders)}")
        
        if hasattr(active_orders, '__dict__'):
            print(f"   Fields: {list(active_orders.__dict__.keys())}")
            
            # Mostrar ordres
            if hasattr(active_orders, 'orders'):
                orders = active_orders.orders
                print(f"\n   📋 Ordres actives trobades: {len(orders) if orders else 0}")
                
                if orders:
                    for i, order in enumerate(orders[:10], 1):
                        print(f"\n   Ordre {i}:")
                        for key, value in order.__dict__.items():
                            if not key.startswith('_'):
                                print(f"      {key}: {value}")
                else:
                    print("   (No hi ha ordres actives)")
            
            # Mostrar altres camps interessants
            for key in ['positions', 'account', 'market']:
                if hasattr(active_orders, key):
                    value = getattr(active_orders, key)
                    print(f"\n   {key}: {value}")
        
        # Provar també amb altres markets per veure si hi ha posicions
        print("\n3. Provant altres markets per veure si hi ha posicions...")
        for market_id in [0, 1, 2]:  # ETH, BTC, SOL
            try:
                orders = await orders_api.account_active_orders(
                    account_index=ACCOUNT_INDEX,
                    market_id=market_id,
                    auth=auth_token
                )
                if hasattr(orders, 'orders') and orders.orders:
                    print(f"   Market {market_id}: {len(orders.orders)} ordres")
            except Exception as e:
                print(f"   Market {market_id}: Error - {str(e)[:100]}")
        
        await api_client.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_account_active_orders())
