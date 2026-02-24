#!/usr/bin/env python3
"""
Lighter - Test WebSocket for Positions and Orders

Tests if we can get positions and orders via WebSocket subscription.
"""
import os
import asyncio
import json
from dotenv import load_dotenv
import lighter
import websockets

load_dotenv()

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "210"))
API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY")

async def test_ws_positions():
    print("=" * 80)
    print("TEST: WebSocket Positions & Orders")
    print("=" * 80)
    print(f"Account Index: {ACCOUNT_INDEX}")
    print(f"Base URL: {BASE_URL}")
    print()
    
    # Convertir HTTPS a WSS
    ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/stream"
    print(f"WebSocket URL: {ws_url}")
    print()
    
    try:
        # Connexió WebSocket
        print("1. Connectant a WebSocket...")
        async with websockets.connect(ws_url) as ws:
            print("   ✅ Connectat!")
            
            # Esperar missatge inicial
            initial_msg = await ws.recv()
            print(f"   Missatge inicial: {initial_msg[:200]}")
            print()
            
            # Subscriure a account updates
            print("2. Subscrivint a account updates...")
            subscribe_msg = {
                "type": "subscribe",
                "channel": f"account:{ACCOUNT_INDEX}"
            }
            await ws.send(json.dumps(subscribe_msg))
            print(f"   Enviat: {json.dumps(subscribe_msg)}")
            print()
            
            # Esperar confirmació i dades
            print("3. Esperant missatges...")
            for i in range(5):  # Esperar fins a 5 missatges
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)
                    print(f"   Missatge {i+1}:")
                    print(f"      Type: {data.get('type', 'unknown')}")
                    print(f"      Channel: {data.get('channel', 'unknown')}")
                    
                    # Mostrar dades si hi ha
                    if 'data' in data:
                        print(f"      Data keys: {list(data['data'].keys())[:10]}")
                        # Buscar posicions
                        if 'positions' in str(data['data']):
                            print("      ✅ TROBAT 'positions' al missatge!")
                        if 'orders' in str(data['data']):
                            print("      ✅ TROBAT 'orders' al missatge!")
                    
                    # Mostrar una mica del missatge complet
                    msg_str = json.dumps(data, indent=2)
                    if len(msg_str) > 500:
                        print(f"      Preview: {msg_str[:500]}...")
                    else:
                        print(f"      Full: {msg_str}")
                    print()
                    
                except asyncio.TimeoutError:
                    print(f"   ⏱️  Timeout esperant missatge {i+1}")
                    break
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_ws_positions())
