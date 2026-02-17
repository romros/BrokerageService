#!/usr/bin/env python3
"""
Check Ostium data quality (no external dependencies)
"""

import json
from datetime import datetime, timezone

def load_candles(filepath):
    """Load candles from JSONL"""
    candles = []
    with open(filepath, 'r') as f:
        for line in f:
            candle = json.loads(line.strip())
            candles.append(candle)
    return candles

def analyze_candles(candles, symbol):
    """Analyze candle quality"""
    if not candles:
        print(f"❌ No candles found")
        return
    
    print(f"\n{'='*80}")
    print(f"📊 ANÀLISI DADES {symbol}")
    print(f"{'='*80}\n")
    
    # Basic stats
    count = len(candles)
    ts_start = candles[0]['ts']
    ts_end = candles[-1]['ts']
    
    dt_start = datetime.fromtimestamp(ts_start, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(ts_end, tz=timezone.utc)
    
    duration_min = (ts_end - ts_start) // 60
    expected_candles = duration_min + 1
    
    print(f"📈 Cobertura:")
    print(f"   Inici:    {dt_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Fi:       {dt_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Duració:  {duration_min} minuts ({duration_min/60:.1f}h)")
    print(f"   Candles:  {count} / {expected_candles} esperats")
    print(f"   Missing:  {expected_candles - count} candles")
    print()
    
    # Price stats
    closes = [c['c'] for c in candles]
    price_min = min(closes)
    price_max = max(closes)
    price_mean = sum(closes) / len(closes)
    
    print(f"💵 Preus:")
    print(f"   Mínim:    ${price_min:.5f}")
    print(f"   Màxim:    ${price_max:.5f}")
    print(f"   Mitjana:  ${price_mean:.5f}")
    print(f"   Rang:     ${price_max - price_min:.5f} ({((price_max - price_min)/price_mean)*100:.2f}%)")
    print()
    
    # Check gaps
    gaps = []
    for i in range(1, len(candles)):
        expected_ts = candles[i-1]['ts'] + 60
        actual_ts = candles[i]['ts']
        if actual_ts != expected_ts:
            gap_min = (actual_ts - expected_ts) // 60
            gaps.append((i, gap_min))
    
    print(f"🔍 Qualitat:")
    print(f"   Gaps:     {len(gaps)}")
    if gaps:
        print(f"   Biggest:  {max(g[1] for g in gaps)} minuts")
    
    # Check zero range
    zero_range = sum(1 for c in candles if c['h'] == c['l'])
    zero_range_pct = (zero_range / count) * 100
    print(f"   Zero range: {zero_range} ({zero_range_pct:.1f}%)")
    print()
    
    # Verdict
    print(f"🎯 Veredicte:")
    
    issues = []
    if expected_candles - count > 2:
        issues.append(f"Falten {expected_candles - count} candles")
    if len(gaps) > 0:
        issues.append(f"{len(gaps)} gaps detectats")
    if zero_range_pct > 30:
        issues.append(f"Massa zero-range ({zero_range_pct:.1f}%)")
    
    if not issues:
        print(f"   ✅ QUALITAT EXCEL·LENT")
    elif len(issues) == 1:
        print(f"   ⚠️  QUALITAT ACCEPTABLE: {issues[0]}")
    else:
        print(f"   ⚠️  QUALITAT MITJANA:")
        for issue in issues:
            print(f"      • {issue}")
    
    print()
    
    # Show last 5 candles
    print(f"📈 Últimes 5 candles:")
    for candle in candles[-5:]:
        dt = datetime.fromtimestamp(candle['ts'], tz=timezone.utc)
        print(f"   {dt.strftime('%H:%M:%S')} | O:{candle['o']:.5f} H:{candle['h']:.5f} L:{candle['l']:.5f} C:{candle['c']:.5f}")
    print()

def main():
    import sys
    import os
    
    if len(sys.argv) < 2:
        # Default to current run
        run_dir = "lab/out/ostium_prices/20260217_080232"
        symbols = ["EURUSD", "XAUUSD", "GBPUSD"]
    else:
        run_dir = sys.argv[1]
        symbols = sys.argv[2:] if len(sys.argv) > 2 else ["EURUSD"]
    
    print("\n" + "="*80)
    print("🔬 OSTIUM DATA QUALITY CHECK")
    print("="*80)
    
    for symbol in symbols:
        filepath = os.path.join(run_dir, f"{symbol}.jsonl")
        
        if not os.path.exists(filepath):
            print(f"\n⚠️  {symbol}: File not found: {filepath}")
            continue
        
        candles = load_candles(filepath)
        analyze_candles(candles, symbol)

if __name__ == '__main__':
    main()
