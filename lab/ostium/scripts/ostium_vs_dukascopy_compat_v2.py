#!/usr/bin/env python3
"""
Ostium vs Dukascopy Compatibility Probe v2

Compara candles d'Ostium (capturades via REST polling) amb Dukascopy.
Similar al compat_report Lighter vs Dukascopy (P8).

Usage:
    python3 ostium_vs_dukascopy_compat_v2.py \
        --symbol EURUSD \
        --ostium-dir lab/out/ostium_prices/20260217_080232 \
        --candles 388
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
from application.services.compat_report_service import build_compat_report, save_compat_report
from domain.models import Candle


def load_ostium_candles(jsonl_file: Path) -> List[Dict]:
    """Load candles from Ostium JSONL file"""
    candles = []
    
    if not jsonl_file.exists():
        raise FileNotFoundError(f"Ostium JSONL not found: {jsonl_file}")
    
    with open(jsonl_file, "r") as f:
        for line in f:
            try:
                candle = json.loads(line)
                candles.append(candle)
            except json.JSONDecodeError as e:
                print(f"⚠️  Skipping invalid JSON line: {line[:50]}... ({e})")
    
    return candles


def convert_to_candle_objects(candles: List, symbol: str) -> List[Candle]:
    """Convert candles to Candle domain objects (handles both dict and Candle objects)"""
    result = []
    for c in candles:
        # Check if already a Candle object
        if isinstance(c, Candle):
            result.append(c)
        elif isinstance(c, dict):
            # Convert dict to Candle
            ts = c.get("ts") or c.get("timestamp")
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc) if isinstance(ts, int) else ts
            
            candle = Candle(
                symbol=symbol,
                timestamp=timestamp,
                open=c.get("o") or c.get("open"),
                high=c.get("h") or c.get("high"),
                low=c.get("l") or c.get("low"),
                close=c.get("c") or c.get("close"),
                volume=c.get("v") or c.get("volume", 0),
                is_closed=True
            )
            result.append(candle)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compare Ostium vs Dukascopy candles (P9.1 compat probe) v2"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Symbol to compare (e.g. EURUSD, XAUUSD)"
    )
    parser.add_argument(
        "--ostium-dir",
        required=True,
        help="Ostium data directory (e.g. lab/out/ostium_prices/20260217_080232)"
    )
    parser.add_argument(
        "--candles",
        type=int,
        help="Number of candles to use (takes last N from Ostium data)"
    )
    parser.add_argument(
        "--minutes",
        type=int,
        help="Number of minutes to use (takes last N minutes from Ostium data)"
    )
    parser.add_argument(
        "--outfile",
        help="Output JSON file (default: lab/out/ostium_compat_<symbol>_<N>c.json)"
    )
    
    args = parser.parse_args()
    
    if not args.candles and not args.minutes:
        parser.error("Especifica --candles o --minutes")
    
    symbol = args.symbol.upper()
    ostium_dir = Path(args.ostium_dir)
    
    print()
    print("=" * 80)
    print("🔍 OSTIUM VS DUKASCOPY COMPAT PROBE V2 (P9.1)")
    print("=" * 80)
    print()
    print(f"Symbol:       {symbol}")
    print(f"Ostium dir:   {ostium_dir}")
    if args.candles:
        print(f"Candles:      last {args.candles}")
    else:
        print(f"Minutes:      last {args.minutes}")
    print()
    
    # Load Ostium candles
    print("📂 Loading Ostium candles...")
    ostium_jsonl = ostium_dir / f"{symbol}.jsonl"
    
    try:
        ostium_candles_raw = load_ostium_candles(ostium_jsonl)
        print(f"✅ Loaded {len(ostium_candles_raw)} Ostium candles total")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    if not ostium_candles_raw:
        print("❌ No Ostium candles found")
        sys.exit(1)
    
    # Sort by timestamp
    ostium_candles_raw.sort(key=lambda c: c["ts"])
    
    # Filter to last N candles or minutes
    if args.candles:
        ostium_candles_raw = ostium_candles_raw[-args.candles:]
        print(f"📊 Using last {len(ostium_candles_raw)} candles")
    elif args.minutes:
        last_ts = ostium_candles_raw[-1]["ts"]
        first_ts = last_ts - (args.minutes * 60)
        ostium_candles_raw = [c for c in ostium_candles_raw if c["ts"] >= first_ts]
        print(f"📊 Using last {args.minutes} minutes → {len(ostium_candles_raw)} candles")
    
    first_ts = ostium_candles_raw[0]["ts"]
    last_ts = ostium_candles_raw[-1]["ts"]
    
    print(f"   From: {datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   To:   {datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    
    # Fetch Dukascopy candles for same range
    print("📥 Fetching Dukascopy candles for same range...")
    print("   (Pot trigar ~30-60s segons mida...)")
    
    try:
        provider = DukascopyBackfillProvider(cache_root="datafiles")
        start_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(last_ts + 60, tz=timezone.utc)  # +1 min
        
        import asyncio
        dukascopy_candles_raw = asyncio.run(provider.fetch_ohlcv(symbol, start_dt, end_dt))
        print(f"✅ Fetched {len(dukascopy_candles_raw)} Dukascopy candles")
    except Exception as e:
        print(f"❌ Error fetching Dukascopy: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    if not dukascopy_candles_raw:
        print("❌ No Dukascopy candles found for this range")
        print("⚠️  Possible reasons:")
        print("   • Dukascopy delay: data not yet available (~1-4h typical)")
        print("   • Weekend / market closed")
        print("   • Symbol not supported by Dukascopy")
        sys.exit(1)
    
    print()
    
    # Convert to Candle domain objects
    ostium_candles = convert_to_candle_objects(ostium_candles_raw, symbol)
    dukascopy_candles = convert_to_candle_objects(dukascopy_candles_raw, symbol)
    
    # Run compat report
    print("🔬 Running compat analysis...")
    print()
    
    report = build_compat_report(
        candles_a=ostium_candles,
        candles_b=dukascopy_candles,
        symbol=symbol,
        source_a="ostium_rest",
        source_b="dukascopy_backfill"
    )
    
    # Print summary
    print("=" * 80)
    print("📊 COMPAT REPORT SUMMARY")
    print("=" * 80)
    print()
    
    print(f"Symbol:           {report['symbol']}")
    print(f"Source A:         {report['source_a']} (Ostium)")
    print(f"Source B:         {report['source_b']} (Dukascopy)")
    print(f"Window:           {report['window_minutes']} min")
    print(f"N candles:        {report['n_candles']}")
    print(f"Aligned count:    {report['aligned_count']}")
    print()
    
    print("Coverage:")
    integrity_a = report.get('integrity_a', {})
    integrity_b = report.get('integrity_b', {})
    print(f"  Ostium:    missing={integrity_a.get('missing_minutes', 0)}, dup={1 if integrity_a.get('has_duplicates') else 0}, step_err={integrity_a.get('ts_step_err', 0)}")
    print(f"  Dukascopy: missing={integrity_b.get('missing_minutes', 0)}, dup={1 if integrity_b.get('has_duplicates') else 0}, step_err={integrity_b.get('ts_step_err', 0)}")
    print()
    
    print("Correlation:")
    returns = report.get('returns', {})
    print(f"  Returns corr (lag 0):  {returns.get('corr_at_lag0', 0):.4f}")
    lag_scan = report.get('lag_scan', {})
    print(f"  Best lag:              {lag_scan.get('best_lag_minutes', 0)} min")
    print(f"  Corr at best lag:      {lag_scan.get('corr_at_best_lag', 0):.4f}")
    proxy = report.get('proxy_strategy', {})
    print(f"  Direction agree:       {proxy.get('dir_agree_pct', 0):.1f}%")
    print()
    
    print("Quality:")
    quality = report.get('candle_quality', {})
    print(f"  Zero range A (Ostium):    {quality.get('zero_range_ratio_a', 0) * 100:.1f}%")
    print(f"  Zero range B (Dukascopy): {quality.get('zero_range_ratio_b', 0) * 100:.1f}%")
    print()
    
    print("Price diffs (A-B):")
    ohlc = report.get('ohlc_diffs', {}).get('close', {})
    print(f"  Mean close:  ${ohlc.get('mean', 0):.5f}")
    print(f"  P95 |close|: ${ohlc.get('p95', 0):.5f}")
    print(f"  Max |close|: ${ohlc.get('max_abs', 0):.5f}")
    print()
    
    # Verdict
    print("=" * 80)
    print("🎯 VERDICT")
    print("=" * 80)
    print()
    
    corr_val = returns.get('corr_at_lag0', 0)
    dir_val = proxy.get('dir_agree_pct', 0)
    zero_val = quality.get('zero_range_ratio_a', 0)
    
    corr_pass = corr_val > 0.7
    dir_pass = dir_val > 65
    zero_range_ok = zero_val < 0.3
    
    if corr_pass and dir_pass and zero_range_ok:
        print("✅ PASS — Dukascopy és compatible per backtest d'Ostium")
        print(f"   Correlació: {corr_val:.2f} >0.7 ✅")
        print(f"   Dir agree: {dir_val:.1f}% >65% ✅")
        print(f"   Zero range: {zero_val*100:.1f}% <30% ✅")
    elif corr_pass and dir_pass:
        print("⚠️  PARTIAL — Compatible amb precaució")
        print(f"   Correlació: {corr_val:.2f} ✅")
        print(f"   Dir agree: {dir_val:.1f}% ✅")
        print(f"   Zero range: {zero_val*100:.1f}% ⚠️")
    else:
        print("❌ FAIL — Massa diferències, revisar fonts")
        print(f"   Correlació: {corr_val:.2f} {'✅' if corr_pass else '❌'}")
        print(f"   Dir agree: {dir_val:.1f}% {'✅' if dir_pass else '❌'}")
    
    print()
    
    # Save report
    if args.outfile:
        outfile = Path(args.outfile)
    else:
        suffix = f"{args.candles}c" if args.candles else f"{args.minutes}m"
        outfile = Path(f"lab/out/ostium_compat_{symbol}_{suffix}.json")
    
    save_compat_report(report, str(outfile))
    
    print(f"📁 Report saved: {outfile}")
    print()


if __name__ == "__main__":
    main()
