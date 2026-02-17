#!/usr/bin/env python3
"""
Test exhaustiu del subgraph de MAINNET d'Ostium
Busca TOTS els trades (no només d'una adreça), per validar si realment està buit o no
"""

import requests
import json
from datetime import datetime, timezone

MAINNET_SUBGRAPH = "https://api.studio.thegraph.com/query/53927/ostium-arbitrum-one/v0.1.0"

def query_subgraph(query: str, variables: dict = None):
    """Execute GraphQL query"""
    try:
        response = requests.post(
            MAINNET_SUBGRAPH,
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                return None
            return data.get("data", {})
        else:
            print(f"❌ HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_global_trades():
    """Query ALL trades (not just one address)"""
    print("\n" + "="*80)
    print("🔍 TEST 1: GLOBAL RECENT TRADES (any address)")
    print("="*80 + "\n")
    
    query = """
    query GetRecentTrades {
      trades(first: 10, orderBy: blockTimestamp, orderDirection: desc) {
        id
        trader
        pairId
        index
        isLong
        collateral
        leverage
        openPrice
        blockTimestamp
        transactionHash
      }
    }
    """
    
    data = query_subgraph(query)
    
    if not data:
        return False
    
    trades = data.get("trades", [])
    
    if not trades:
        print("❌ No trades found (subgraph might be empty)")
        return False
    
    print(f"✅ Found {len(trades)} recent trades!\n")
    
    for i, trade in enumerate(trades[:5], 1):
        ts = int(trade.get("blockTimestamp", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        print(f"  {i}. Pair {trade['pairId']} | {'LONG' if trade.get('isLong') else 'SHORT'}")
        print(f"     Trader: {trade['trader'][:10]}...{trade['trader'][-8:]}")
        print(f"     Price: {trade.get('openPrice', 'N/A')}")
        print(f"     Collateral: {trade.get('collateral', 'N/A')}")
        print(f"     Leverage: {trade.get('leverage', 'N/A')}x")
        print(f"     Time: {dt}")
        print(f"     TX: {trade.get('transactionHash', 'N/A')[:20]}...")
        print()
    
    return True

def test_open_trades():
    """Query open positions (not closed yet)"""
    print("\n" + "="*80)
    print("🔍 TEST 2: OPEN TRADES (active positions)")
    print("="*80 + "\n")
    
    query = """
    query GetOpenTrades {
      openTrades(first: 10, orderBy: blockTimestamp, orderDirection: desc) {
        id
        trader
        pairId
        index
        isLong
        collateral
        leverage
        openPrice
        tp
        sl
      }
    }
    """
    
    data = query_subgraph(query)
    
    if not data:
        return False
    
    open_trades = data.get("openTrades", [])
    
    if not open_trades:
        print("⚠️  No open trades found (might be all closed currently)")
        return False
    
    print(f"✅ Found {len(open_trades)} open positions!\n")
    
    for i, trade in enumerate(open_trades[:5], 1):
        print(f"  {i}. Pair {trade['pairId']} | {'LONG' if trade.get('isLong') else 'SHORT'}")
        print(f"     Trader: {trade['trader'][:10]}...{trade['trader'][-8:]}")
        print(f"     Price: {trade.get('openPrice', 'N/A')}")
        print(f"     TP: {trade.get('tp', 'N/A')} | SL: {trade.get('sl', 'N/A')}")
        print()
    
    return True

def test_traders_count():
    """Check how many unique traders exist"""
    print("\n" + "="*80)
    print("🔍 TEST 3: TRADERS COUNT")
    print("="*80 + "\n")
    
    query = """
    query GetTraders {
      traders(first: 10) {
        id
      }
    }
    """
    
    data = query_subgraph(query)
    
    if not data:
        return False
    
    traders = data.get("traders", [])
    
    if not traders:
        print("❌ No traders found")
        return False
    
    print(f"✅ Found at least {len(traders)} traders in subgraph\n")
    
    for i, trader in enumerate(traders[:5], 1):
        print(f"  {i}. {trader['id'][:10]}...{trader['id'][-8:]}")
    
    return True

def test_pairs():
    """Check available pairs"""
    print("\n" + "="*80)
    print("🔍 TEST 4: AVAILABLE PAIRS")
    print("="*80 + "\n")
    
    query = """
    query GetPairs {
      pairs(first: 10) {
        id
        name
      }
    }
    """
    
    data = query_subgraph(query)
    
    if not data:
        return False
    
    pairs = data.get("pairs", [])
    
    if not pairs:
        print("❌ No pairs found")
        return False
    
    print(f"✅ Found {len(pairs)} pairs:\n")
    
    for pair in pairs:
        print(f"  • Pair {pair['id']}: {pair.get('name', 'Unknown')}")
    
    return True

def main():
    print("\n" + "="*80)
    print("🧪 OSTIUM MAINNET SUBGRAPH — DEEP TEST")
    print("="*80)
    print(f"\nURL: {MAINNET_SUBGRAPH}")
    print("Testing if subgraph actually has data...\n")
    
    results = {
        "Global trades": test_global_trades(),
        "Open trades": test_open_trades(),
        "Traders": test_traders_count(),
        "Pairs": test_pairs()
    }
    
    # Summary
    print("\n" + "="*80)
    print("📊 SUMMARY")
    print("="*80 + "\n")
    
    for test_name, result in results.items():
        status = "✅ HAS DATA" if result else "❌ EMPTY"
        print(f"  {test_name:20s} {status}")
    
    print()
    
    if any(results.values()):
        print("🎉 MAINNET SUBGRAPH FUNCIONA!")
        print("   Té dades indexades i es pot utilitzar.")
        print()
        print("   ✅ sdk.subgraph.get_open_trades() hauria de funcionar")
        print("   ✅ NO cal fer brute force trade_index")
        print("   ✅ Mètode convencional del SDK és viable")
    else:
        print("❌ MAINNET SUBGRAPH BUIT")
        print("   No conté dades (unexpected!)")
        print()
        print("   ⚠️ Cal usar workaround (brute force)")
    
    print()

if __name__ == '__main__':
    main()
