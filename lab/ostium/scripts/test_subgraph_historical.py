#!/usr/bin/env python3
"""
Ostium Mainnet Subgraph — Historical Data Explorer (READ-ONLY, no wallet needed)

Aquest script explora el subgraph de mainnet d'Ostium per determinar si:
1. Conté dades històriques de preus
2. Pot servir com a font alternativa al REST polling
3. Té timestamps/events útils per backtest

NO REQUEREIX WALLET — Només queries de lectura GraphQL.
"""

import time
import requests
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

MAINNET_SUBGRAPH = "https://api.studio.thegraph.com/query/53927/ostium-arbitrum-one/v0.1.0"

# Colors for output
class Color:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Color.BOLD}{Color.HEADER}{'='*80}{Color.END}")
    print(f"{Color.BOLD}{Color.HEADER}{text}{Color.END}")
    print(f"{Color.BOLD}{Color.HEADER}{'='*80}{Color.END}\n")

def print_section(text: str):
    print(f"\n{Color.BOLD}{Color.BLUE}{'─'*80}{Color.END}")
    print(f"{Color.BOLD}{Color.BLUE}📊 {text}{Color.END}")
    print(f"{Color.BOLD}{Color.BLUE}{'─'*80}{Color.END}\n")

def query_subgraph(query: str, variables: Optional[Dict] = None) -> Optional[Dict]:
    """Execute GraphQL query against subgraph"""
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
                print(f"{Color.RED}❌ GraphQL errors: {data['errors']}{Color.END}")
                return None
            return data.get("data", {})
        else:
            print(f"{Color.RED}❌ HTTP {response.status_code}: {response.text}{Color.END}")
            return None

    except requests.Timeout:
        print(f"{Color.RED}❌ Timeout after 30s{Color.END}")
        return None
    except Exception as e:
        print(f"{Color.RED}❌ Error: {str(e)}{Color.END}")
        return None

def test_schema_introspection():
    """Discover available types/fields in the subgraph"""
    print_section("SCHEMA INTROSPECTION")

    query = """
    {
      __schema {
        types {
          name
          kind
          fields {
            name
            type {
              name
              kind
            }
          }
        }
      }
    }
    """

    print("🔍 Discovering available entities...")
    data = query_subgraph(query)

    if not data:
        return []

    # Filter out built-in GraphQL types
    types = [t for t in data.get("__schema", {}).get("types", [])
             if t["kind"] == "OBJECT" and not t["name"].startswith("_")]

    print(f"{Color.GREEN}✅ Found {len(types)} entity types:{Color.END}\n")

    relevant_types = []
    for t in types:
        fields = t.get("fields") or []
        field_names = [f["name"] for f in fields]

        # Check if potentially useful for price data
        has_price = any("price" in f.lower() for f in field_names)
        has_timestamp = any("time" in f.lower() or "timestamp" in f.lower() for f in field_names)

        if has_price or has_timestamp or t["name"] in ["Trade", "Position", "PriceUpdate"]:
            relevant_types.append(t["name"])
            marker = "⭐" if (has_price and has_timestamp) else "📋"
            print(f"  {marker} {Color.BOLD}{t['name']}{Color.END}")
            print(f"      Fields: {', '.join(field_names[:8])}")
            if len(field_names) > 8:
                print(f"      ... and {len(field_names) - 8} more")
            print()

    return relevant_types

def test_trades_recent():
    """Query recent trades to see if they contain price/timestamp info"""
    print_section("RECENT TRADES")

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
        blockNumber
        blockTimestamp
        transactionHash
      }
    }
    """

    print("🔍 Fetching last 10 trades...")
    data = query_subgraph(query)

    if not data:
        return False

    trades = data.get("trades", [])

    if not trades:
        print(f"{Color.YELLOW}⚠️  No trades found (mainnet might have low activity){Color.END}")
        return False

    print(f"{Color.GREEN}✅ Found {len(trades)} trades:{Color.END}\n")

    for i, trade in enumerate(trades[:5], 1):
        ts = int(trade.get("blockTimestamp", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        print(f"  {i}. Pair {trade['pairId']} | {'LONG' if trade.get('isLong') else 'SHORT'}")
        print(f"     Price: {trade.get('openPrice', 'N/A')}")
        print(f"     Time:  {dt} (block #{trade.get('blockNumber', 'N/A')})")
        print(f"     Tx:    {trade.get('transactionHash', 'N/A')[:20]}...")
        print()

    return True

def test_price_updates():
    """Check if there's a PriceUpdate entity with historical prices"""
    print_section("PRICE UPDATES")

    query = """
    query GetPriceUpdates {
      priceUpdates(first: 10, orderBy: timestamp, orderDirection: desc) {
        id
        pairId
        price
        timestamp
        blockNumber
      }
    }
    """

    print("🔍 Looking for PriceUpdate entities...")
    data = query_subgraph(query)

    if data is None:
        print(f"{Color.YELLOW}⚠️  PriceUpdate entity not found in schema{Color.END}")
        return False

    updates = data.get("priceUpdates", [])

    if not updates:
        print(f"{Color.YELLOW}⚠️  No price updates found{Color.END}")
        return False

    print(f"{Color.GREEN}✅ Found {len(updates)} price updates!{Color.END}\n")

    for i, update in enumerate(updates[:5], 1):
        ts = int(update.get("timestamp", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        print(f"  {i}. Pair {update['pairId']}")
        print(f"     Price: {update['price']}")
        print(f"     Time:  {dt}")
        print()

    return True

def test_historical_range():
    """Check the time range of available data"""
    print_section("HISTORICAL DATA RANGE")

    query = """
    query GetHistoricalRange {
      earliest: trades(first: 1, orderBy: blockTimestamp, orderDirection: asc) {
        blockTimestamp
      }
      latest: trades(first: 1, orderBy: blockTimestamp, orderDirection: desc) {
        blockTimestamp
      }
    }
    """

    print("🔍 Checking historical data range...")
    data = query_subgraph(query)

    if not data:
        return

    earliest = data.get("earliest", [])
    latest = data.get("latest", [])

    if not earliest or not latest:
        print(f"{Color.YELLOW}⚠️  Not enough data to determine range{Color.END}")
        return

    ts_earliest = int(earliest[0]["blockTimestamp"])
    ts_latest = int(latest[0]["blockTimestamp"])

    dt_earliest = datetime.fromtimestamp(ts_earliest, tz=timezone.utc)
    dt_latest = datetime.fromtimestamp(ts_latest, tz=timezone.utc)

    days_coverage = (ts_latest - ts_earliest) / 86400

    print(f"{Color.GREEN}📅 Data coverage:{Color.END}\n")
    print(f"   Earliest: {dt_earliest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Latest:   {dt_latest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Duration: {days_coverage:.1f} days")
    print()

def test_eurusd_specific():
    """Test if we can get EURUSD-specific data"""
    print_section("EURUSD-SPECIFIC DATA")

    # EURUSD is typically pairId 0 in Ostium
    query = """
    query GetEURUSDTrades {
      trades(first: 10, where: {pairId: "0"}, orderBy: blockTimestamp, orderDirection: desc) {
        id
        trader
        pairId
        openPrice
        blockTimestamp
      }
    }
    """

    print("🔍 Fetching EURUSD (pairId=0) trades...")
    data = query_subgraph(query)

    if not data:
        return

    trades = data.get("trades", [])

    if not trades:
        print(f"{Color.YELLOW}⚠️  No EURUSD trades found (pairId=0){Color.END}")
        return

    print(f"{Color.GREEN}✅ Found {len(trades)} EURUSD trades:{Color.END}\n")

    for i, trade in enumerate(trades[:5], 1):
        ts = int(trade.get("blockTimestamp", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        print(f"  {i}. Price: {trade.get('openPrice', 'N/A')}")
        print(f"     Time:  {dt}")
        print()

def main():
    print_header("🧪 OSTIUM MAINNET SUBGRAPH — HISTORICAL DATA EXPLORER")

    print(f"{Color.BOLD}Subgraph URL:{Color.END} {MAINNET_SUBGRAPH}")
    print(f"{Color.BOLD}Mode:{Color.END} Read-only (no wallet needed)")
    print()

    # Test 1: Discover schema
    relevant_types = test_schema_introspection()

    # Test 2: Recent trades
    has_trades = test_trades_recent()

    # Test 3: Price updates (if entity exists)
    has_price_updates = test_price_updates()

    # Test 4: Historical range
    if has_trades:
        test_historical_range()

    # Test 5: EURUSD specific
    test_eurusd_specific()

    # Summary
    print_header("📊 SUMMARY & CONCLUSIONS")

    print(f"{Color.BOLD}Subgraph Status:{Color.END}")
    print(f"  • Connection:       {Color.GREEN}✅ Working{Color.END}")
    print(f"  • Trades entity:    {Color.GREEN if has_trades else Color.RED}{'✅ Available' if has_trades else '❌ Empty/Not found'}{Color.END}")
    print(f"  • PriceUpdate:      {Color.GREEN if has_price_updates else Color.YELLOW}{'✅ Available' if has_price_updates else '⚠️ Not found'}{Color.END}")
    print()

    print(f"{Color.BOLD}Conclusions:{Color.END}\n")

    if has_price_updates:
        print(f"  {Color.GREEN}✅ VIABLE:{Color.END} Subgraph té PriceUpdate entities")
        print(f"     → Pot ser útil per històric de preus")
        print(f"     → Recomanat: Provar query amb timestamp range")
        print()
    elif has_trades:
        print(f"  {Color.YELLOW}⚠️ PARCIAL:{Color.END} Només té trades (no PriceUpdate dedicat)")
        print(f"     → Pots extreure openPrice dels trades")
        print(f"     → Limitació: Només preus quan hi ha trades (no continu)")
        print(f"     → Millor opció: REST polling (ja implementat)")
        print()
    else:
        print(f"  {Color.RED}❌ NO VIABLE:{Color.END} Subgraph no conté dades útils per preus")
        print(f"     → Continuar amb REST polling (ja implementat)")
        print()

    print(f"{Color.BOLD}Recomanació:{Color.END}")
    if has_price_updates:
        print(f"  • Implementar subgraph_price_collector.py com alternativa")
    else:
        print(f"  • Mantenir REST polling (rest_price_collector.py)")
    print()

if __name__ == '__main__':
    main()
