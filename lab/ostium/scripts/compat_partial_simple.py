#!/usr/bin/env python3
"""
Comparació parcial Ostium vs Dukascopy (standalone, dependencies mínimes)
Similar als tests de compat de Lighter però per lab d'Ostium
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

def load_ostium_candles(filepath):
    """Load Ostium candles from JSONL"""
    candles = []
    with open(filepath, 'r') as f:
        for line in f:
            c = json.loads(line.strip())
            candles.append({
                'ts': c['ts'],
                'o': c['o'],
                'h': c['h'],
                'l': c['l'],
                'c': c['c']
            })
    return candles

def fetch_dukascopy_simple(symbol, start_ts, end_ts):
    """Fetch Dukascopy data (requires dukascopy-python)"""
    try:
        from dukascopy.fetch import fetch_one_minute_data
    except ImportError:
        print("❌ dukascopy-python not installed")
        print("   Install: pip install dukascopy-python")
        return None
    
    start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    
    # Dukascopy format: EUR/USD
    duka_symbol = f"{symbol[:3]}/{symbol[3:]}" if len(symbol) == 6 else symbol
    
    try:
        df = fetch_one_minute_data(duka_symbol, start_dt, end_dt)
        
        if df is None or df.empty:
            return None
        
        # Convert to same format
        candles = []
        for idx, row in df.iterrows():
            candles.append({
                'ts': int(idx.timestamp()),
                'o': float(row['open']),
                'h': float(row['high']),
                'l': float(row['low']),
                'c': float(row['close'])
            })
        
        return candles
    except Exception as e:
        print(f"❌ Error Dukascopy: {e}")
        return None

def align_candles(candles_a, candles_b):
    """Inner join by timestamp"""
    by_ts_b = {c['ts']: c for c in candles_b}
    
    aligned = []
    for ca in candles_a:
        if ca['ts'] in by_ts_b:
            aligned.append((ca, by_ts_b[ca['ts']]))
    
    return aligned

def compute_stats(aligned):
    """Compute basic compatibility stats"""
    if not aligned:
        return None
    
    # Close price correlation (simple)
    closes_a = [pair[0]['c'] for pair in aligned]
    closes_b = [pair[1]['c'] for pair in aligned]
    
    mean_a = sum(closes_a) / len(closes_a)
    mean_b = sum(closes_b) / len(closes_b)
    
    # Covariance and correlation
    cov = sum((closes_a[i] - mean_a) * (closes_b[i] - mean_b) for i in range(len(closes_a))) / len(closes_a)
    std_a = (sum((x - mean_a)**2 for x in closes_a) / len(closes_a)) ** 0.5
    std_b = (sum((x - mean_b)**2 for x in closes_b) / len(closes_b)) ** 0.5
    
    corr = cov / (std_a * std_b) if std_a > 0 and std_b > 0 else 0
    
    # Close diffs
    diffs = [closes_a[i] - closes_b[i] for i in range(len(closes_a))]
    mean_diff = sum(diffs) / len(diffs)
    abs_diffs = [abs(d) for d in diffs]
    mean_abs_diff = sum(abs_diffs) / len(abs_diffs)
    max_abs_diff = max(abs_diffs)
    
    # Direction agreement
    changes_a = [closes_a[i+1] - closes_a[i] for i in range(len(closes_a)-1)]
    changes_b = [closes_b[i+1] - closes_b[i] for i in range(len(closes_b)-1)]
    same_dir = sum(1 for i in range(len(changes_a)) if (changes_a[i] > 0) == (changes_b[i] > 0))
    dir_agree_pct = (same_dir / len(changes_a)) * 100 if changes_a else 0
    
    return {
        'count': len(aligned),
        'corr': corr,
        'mean_diff': mean_diff,
        'mean_abs_diff': mean_abs_diff,
        'max_abs_diff': max_abs_diff,
        'dir_agree_pct': dir_agree_pct
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 compat_partial_simple.py <symbol> <ostium_dir>")
        print("Example: python3 compat_partial_simple.py EURUSD lab/out/ostium_prices/20260217_080232")
        return
    
    symbol = sys.argv[1]
    ostium_dir = Path(sys.argv[2])
    
    print(f"\n{'='*80}")
    print(f"🔬 OSTIUM vs DUKASCOPY — COMPARACIÓ PARCIAL ({symbol})")
    print(f"{'='*80}\n")
    
    # Load Ostium
    ostium_file = ostium_dir / f"{symbol}.jsonl"
    
    if not ostium_file.exists():
        print(f"❌ Ostium file not found: {ostium_file}")
        return
    
    print(f"📂 Carregant Ostium...")
    ostium_candles = load_ostium_candles(ostium_file)
    print(f"   ✅ {len(ostium_candles)} candles")
    
    if not ostium_candles:
        print(f"❌ No candles d'Ostium")
        return
    
    # Timestamps
    ts_start = ostium_candles[0]['ts']
    ts_end = ostium_candles[-1]['ts']
    dt_start = datetime.fromtimestamp(ts_start, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(ts_end, tz=timezone.utc)
    
    print(f"   📅 {dt_start.strftime('%Y-%m-%d %H:%M')} → {dt_end.strftime('%Y-%m-%d %H:%M')} UTC")
    duration_h = (ts_end - ts_start) / 3600
    print(f"   ⏱️  {duration_h:.1f}h")
    print()
    
    # Fetch Dukascopy
    print(f"📂 Descarregant Dukascopy...")
    print(f"   (Pot trigar ~30-60s per {len(ostium_candles)} candles)")
    
    duka_candles = fetch_dukascopy_simple(symbol, ts_start, ts_end)
    
    if not duka_candles:
        print(f"   ❌ No s'han pogut obtenir dades Dukascopy")
        print(f"   Possibles raons:")
        print(f"   • Dukascopy delay (~1-4h per dades recents)")
        print(f"   • Error de xarxa")
        print(f"   • Symbol no disponible")
        return
    
    print(f"   ✅ {len(duka_candles)} candles")
    print()
    
    # Align
    print(f"🔗 Alineant timestamps...")
    aligned = align_candles(ostium_candles, duka_candles)
    overlap_pct = (len(aligned) / len(ostium_candles)) * 100
    
    print(f"   ✅ {len(aligned)} candles coincidents ({overlap_pct:.1f}% overlap)")
    
    if len(aligned) < 10:
        print(f"   ❌ Massa pocs punts per comparar")
        return
    
    print()
    
    # Compute stats
    print(f"📊 Computant estadístiques...")
    stats = compute_stats(aligned)
    
    if not stats:
        print(f"   ❌ Error computant stats")
        return
    
    print()
    print(f"{'='*80}")
    print(f"📈 RESULTATS COMPATIBILITAT")
    print(f"{'='*80}\n")
    
    print(f"  Mètrica                    Valor       Llindar     Status")
    print(f"  {'─'*64}")
    
    # Correlation
    corr = stats['corr']
    corr_status = "✅ OK" if corr >= 0.7 else "❌ BAIX"
    print(f"  Correlation (close)        {corr:>6.3f}        >0.70      {corr_status}")
    
    # Direction agreement
    dir_agree = stats['dir_agree_pct']
    dir_status = "✅ OK" if dir_agree >= 65 else "❌ BAIX"
    print(f"  Direction agree            {dir_agree:>5.1f}%       >65%       {dir_status}")
    
    # Mean absolute diff
    mean_abs = stats['mean_abs_diff']
    max_abs = stats['max_abs_diff']
    print(f"  Mean abs diff (close)      {mean_abs:>7.5f}")
    print(f"  Max abs diff (close)       {max_abs:>7.5f}")
    
    print()
    
    # Verdict
    print(f"🎯 VEREDICTE PARCIAL:\n")
    
    if corr >= 0.95 and dir_agree >= 95:
        print(f"  ✅ MOLT COMPATIBLE")
        print(f"     Les fonts són molt similars")
    elif corr >= 0.7 and dir_agree >= 65:
        print(f"  ✅ COMPATIBLE")
        print(f"     Dukascopy viable per backtest Ostium")
    elif corr >= 0.5 and dir_agree >= 50:
        print(f"  ⚠️  PARCIALMENT COMPATIBLE")
        print(f"     Revisar offsets abans d'usar per backtest")
    else:
        print(f"  ❌ INCOMPATIBLE")
        print(f"     Fonts massa diferents")
    
    print()
    print(f"⏰ NOTA: Comparació parcial amb {duration_h:.1f}h de dades")
    print(f"   Per veredicte final: espera 24h + executar compat complet")
    print()

if __name__ == '__main__':
    main()
