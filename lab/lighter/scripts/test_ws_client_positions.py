#!/usr/bin/env python3
"""
Lighter - Test WsClient for Positions

Uses the SDK's WsClient to subscribe to account updates.
"""
import os
import asyncio
import json
from dotenv import load_dotenv
import lighter

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))

# Handler per account updates
def on_account_update(account_id, account_state):
    """Callback quan arriba una actualització d'account"""
    print("\n" + "="*80)
    print(f"📊 ACCOUNT UPDATE RECEBUT! (Account ID: {account_id})")
    print("="*80)
    print(f"Account State type: {type(account_state)}")
    
    if isinstance(account_state, dict):
        print(f"Keys: {list(account_state.keys())}")
        print(f"\nFull account state:")
        print(json.dumps(account_state, indent=2, default=str))
        
        # Buscar posicions
        if 'positions' in str(account_state):
            print("\n✅ TROBAT 'positions' al account_state!")
        if 'orders' in str(account_state):
            print("\n✅ TROBAT 'orders' al account_state!")
    else:
        print(f"Account State: {account_state}")
    print("="*80 + "\n")

async def test_ws_client():
    print("=" * 80)
    print("TEST: WsClient per Positions")
    print("=" * 80)
    print(f"Account Index: {ACCOUNT_INDEX}")
    print(f"Base URL: {BASE_URL}")
    print()
    
    # Convertir HTTPS a WSS
    ws_host = BASE_URL.replace("https://", "").replace("http://", "")
    ws_url = f"wss://{ws_host}/stream"
    
    print(f"WebSocket URL: {ws_url}")
    print()
    
    try:
        # Crear WsClient amb account_ids
        print("1. Creant WsClient...")
        ws_client = lighter.WsClient(
            host=ws_host,
            path="/stream",
            account_ids=[ACCOUNT_INDEX],  # ⚠️ Subscriure a aquest account
            on_account_update=on_account_update
        )
        print("   ✅ WsClient creat!")
        print()
        
        # Executar en background
        print("2. Iniciant WebSocket en background...")
        print("   (Esperant 10 segons per rebre updates...)\n")
        
        # Executar async
        ws_task = asyncio.create_task(ws_client.run_async())
        
        # Esperar una mica
        await asyncio.sleep(10)
        
        # Cancel·lar
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        
        print("\n✅ Test completat!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ws_client())
