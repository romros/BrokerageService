#!/usr/bin/env python3
"""
Quick compatibility check: Ostium vs Dukascopy (parcial)
Només dependencies mínimes
"""

import json
from datetime import datetime, timezone, timedelta
import numpy as np

# Try to import dukascopy
try:
    from dukascopy.fetch import fetch_one_minute_data
    HAS_DUKASCOPY = True
except ImportError:
    HAS_DUKASCOPY = False
    print("⚠️  dukascopy-python not installed")
    print("   Install: pip install dukascopy-python")

def load_ostium_candles(filepath):
    """Load Ostium candles from JSONL"""
    candles = []
    with open(filepath, 'r') as f:
        for line in f:
            candle = json.loads(line.strip())
            candles.append(candle)
    return candles

def analyze_ostium_data(candles):
    """Quick analysis of Ostium data"""
    if not candles:
        return None
    
    ts_start = candles[0]['ts']
    ts_end = candles[-1]['ts']
    
    dt_start = datetime.fromtimestamp(ts_start, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(ts_end, tz=timezone.utc)
    
    closes = [c['c'] for c in candles]
    
    return {
        'count': len(candles),
        'start': dt_start,
        'end': dt_end,
        'duration_min': len(candles),
        'price_mean': np.mean(closes),
        'price_std': np.std(closes),
        'price_min': min(closes),
        'price_max': max(closes),
    }

def fetch_dukascopy_data(start_dt, end_dt):
    """Fetch Dukascopy data for comparison"""
    if not HAS_DUKASCOPY:
        return None
    
    try:
        # Dukascopy uses EUR/USD format
        df = fetch_one_minute_data(
            "EUR/USD",
            start_dt,
            end_dt
        )
        
        if df is None or df.empty:
            return None
        
        return {
            'count': len(df),
            'price_mean': df['close'].mean(),
            'price_std': df['close'].std(),
            'price_min': df['close'].min(),
            'price_max': df['close'].max(),
        }
    except Exception as e:
        print(f"⚠️  Error fetching Dukascopy: {e}")
        return None

def compare_stats(ostium, dukascopy):
    """Compare basic statistics"""
    print(f"\n{'='*80}")
    print(f"📊 COMPARACIÓ ESTADÍSTICA")
    print(f"{'='*80}\n")
    
    print(f"{'Mètrica':<20} {'Ostium':>12} {'Dukascopy':>12} {'Diff':>10}")
    print(f"{'-'*58}")
    
    # Count
    count_diff = abs(ostium['count'] - dukascopy['count'])
    print(f"{'Candles':<20} {ostium['count']:>12} {dukascopy['count']:>12} {count_diff:>10}")
    
    # Mean price
    mean_diff = abs(ostium['price_mean'] - dukascopy['price_mean'])
    mean_diff_pct = (mean_diff / ostium['price_mean']) * 100
    print(f"{'Mean price':<20} {ostium['price_mean']:>12.5f} {dukascopy['price_mean']:>12.5f} {mean_diff_pct:>9.3f}%")
    
    # Std
    std_diff = abs(ostium['price_std'] - dukascopy['price_std'])
    print(f"{'Std dev':<20} {ostium['price_std']:>12.5f} {dukascopy['price_std']:>12.5f} {std_diff:>10.5f}")
    
    # Min/Max
    min_diff = abs(ostium['price_min'] - dukascopy['price_min'])
    max_diff = abs(ostium['price_max'] - dukascopy['price_max'])
    print(f"{'Min price':<20} {ostium['price_min']:>12.5f} {dukascopy['price_min']:>12.5f} {min_diff:>10.5f}")
    print(f"{'Max price':<20} {ostium['price_max']:>12.5f} {dukascopy['price_max']:>12.5f} {max_diff:>10.5f}")
    
    print()
    
    # Verdict
    if mean_diff_pct < 0.1:
        print(f"  ✅ MOLT COMPATIBLE (diff < 0.1%)")
    elif mean_diff_pct < 0.5:
        print(f"  ✅ COMPATIBLE (diff < 0.5%)")
    elif mean_diff_pct < 1.0:
        print(f"  ⚠️  ACCEPTABLE (diff < 1.0%)")
    else:
        print(f"  ❌ DIFERÈNCIES SIGNIFICATIVES (diff > 1.0%)")
    
    print()

def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 quick_compat_check.py <ostium_eurusd.jsonl>")
        return
    
    filepath = sys.argv[1]
    
    print("\n" + "="*80)
    print("🔬 OSTIUM vs DUKASCOPY — QUICK COMPAT CHECK")
    print("="*80 + "\n")
    
    # Load Ostium data
    print("📂 Carregant dades Ostium...")
    candles = load_ostium_candles(filepath)
    ostium_stats = analyze_ostium_data(candles)
    
    print(f"   ✅ {ostium_stats['count']} candles")
    print(f"   📅 {ostium_stats['start'].strftime('%Y-%m-%d %H:%M')} → {ostium_stats['end'].strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"   ⏱️  {ostium_stats['duration_min']} minuts")
    print()
    
    # Fetch Dukascopy data
    if not HAS_DUKASCOPY:
        print("❌ No es pot comparar sense dukascopy-python")
        return
    
    print("📂 Descarregant dades Dukascopy...")
    print(f"   (Pot trigar ~30s per {ostium_stats['duration_min']} minuts)")
    
    dukascopy_stats = fetch_dukascopy_data(
        ostium_stats['start'],
        ostium_stats['end']
    )
    
    if not dukascopy_stats:
        print("   ❌ No s'han pogut obtenir dades Dukascopy")
        print("   Possibles raons:")
        print("   • Dukascopy delay (~1-4h per dades recents)")
        print("   • Error de xarxa")
        print("   • Rang de temps no disponible")
        return
    
    print(f"   ✅ {dukascopy_stats['count']} candles")
    print()
    
    # Compare
    compare_stats(ostium_stats, dukascopy_stats)

if __name__ == '__main__':
    main()
