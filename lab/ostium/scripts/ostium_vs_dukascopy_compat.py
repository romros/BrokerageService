#!/usr/bin/env python3
"""
Ostium vs Dukascopy Compatibility Probe

Compara candles d'Ostium (capturades via REST polling) amb Dukascopy.
Similar al compat_report Lighter vs Dukascopy (P8).

Usage:
    python3 ostium_vs_dukascopy_compat.py \
        --symbol EURUSD \
        --ostium-dir lab/out/ostium_prices/20260217_080232 \
        --minutes 1440
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
from application.services.compat_report_service import CompatReportService


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


def convert_to_compat_format(candles: List[Dict], source: str) -> List[Dict]:
    """Convert candles to format expected by compat service"""
    return [{
        "ts": c["ts"],
        "open": c["o"] if "o" in c else c["open"],
        "high": c["h"] if "h" in c else c["high"],
        "low": c["l"] if "l" in c else c["low"],
        "close": c["c"] if "c" in c else c["close"],
        "volume": c.get("v", c.get("volume", 0)),
        "source": source
    } for c in candles]


def main():
    parser = argparse.ArgumentParser(
        description="Compare Ostium vs Dukascopy candles (P9.1 compat probe)"
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
        "--minutes",
        type=int,
        default=1440,
        help="Number of minutes to compare (default: 1440 = 24h)"
    )
    parser.add_argument(
        "--outfile",
        help="Output JSON file (default: lab/out/ostium_compat_<symbol>_<Nm>m.json)"
    )
    
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    ostium_dir = Path(args.ostium_dir)
    
    print()
    print("=" * 80)
    print("🔍 OSTIUM VS DUKASCOPY COMPAT PROBE (P9.1)")
    print("=" * 80)
    print()
    print(f"Symbol:       {symbol}")
    print(f"Ostium dir:   {ostium_dir}")
    print(f"Minutes:      {args.minutes}")
    print()
    
    # Load Ostium candles
    print("📂 Loading Ostium candles...")
    ostium_jsonl = ostium_dir / f"{symbol}.jsonl"
    
    try:
        ostium_candles_raw = load_ostium_candles(ostium_jsonl)
        print(f"✅ Loaded {len(ostium_candles_raw)} Ostium candles")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    if not ostium_candles_raw:
        print("❌ No Ostium candles found")
        sys.exit(1)
    
    # Determine time range from Ostium candles
    ostium_candles_raw.sort(key=lambda c: c["ts"])
    
    if args.minutes:
        # Use last N minutes from Ostium data
        last_ts = ostium_candles_raw[-1]["ts"]
        first_ts = last_ts - (args.minutes * 60)
        ostium_candles_raw = [c for c in ostium_candles_raw if c["ts"] >= first_ts]
    
    first_ts = ostium_candles_raw[0]["ts"]
    last_ts = ostium_candles_raw[-1]["ts"]
    
    print(f"📊 Time range:")
    print(f"   From: {datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   To:   {datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    
    # Fetch Dukascopy candles for same range
    print("📥 Fetching Dukascopy candles for same range...")
    
    try:
        provider = DukascopyBackfillProvider(cache_root="datafiles")
        start_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(last_ts + 60, tz=timezone.utc)  # +1 min to ensure we get last candle
        
        dukascopy_candles_raw = provider.fetch(
            symbol=symbol,
            start=start_dt,
            end=end_dt
        )
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
    
    # Convert to compat format
    ostium_candles = convert_to_compat_format(ostium_candles_raw, "ostium_rest")
    dukascopy_candles = convert_to_compat_format(dukascopy_candles_raw, "dukascopy_backfill")
    
    # Run compat report
    print("🔬 Running compat analysis...")
    print()
    
    service = CompatReportService()
    
    report = service.compare_series(
        series_a=ostium_candles,
        series_b=dukascopy_candles,
        symbol=symbol,
        window_minutes_a=len(ostium_candles),
        window_minutes_b=len(dukascopy_candles)
    )
    
    # Print summary
    print("=" * 80)
    print("📊 COMPAT REPORT SUMMARY")
    print("=" * 80)
    print()
    
    print(f"Symbol:           {report['symbol']}")
    print(f"Window A (Ostium):     {report['window_minutes_a']} min")
    print(f"Window B (Dukascopy):  {report['window_minutes_b']} min")
    print(f"Overlap:          {report['overlap_minutes']} min")
    print()
    
    print("Coverage:")
    print(f"  Ostium:    missing={report['missing_a']}, dup={report['duplicates_a']}, step_err={report['ts_step_errors_a']}")
    print(f"  Dukascopy: missing={report['missing_b']}, dup={report['duplicates_b']}, step_err={report['ts_step_errors_b']}")
    print()
    
    print("Correlation:")
    print(f"  Returns corr (lag 0):  {report['corr_at_lag0']:.4f}")
    print(f"  Best lag:              {report['best_lag_minutes']} min")
    print(f"  Corr at best lag:      {report['corr_at_best_lag']:.4f}")
    print(f"  Direction agree:       {report['dir_agree_pct']:.1f}%")
    print()
    
    print("Quality:")
    print(f"  Zero range A (Ostium):    {report['zero_range_ratio_a'] * 100:.1f}%")
    print(f"  Zero range B (Dukascopy): {report['zero_range_ratio_b'] * 100:.1f}%")
    print()
    
    print("Price diffs (A-B):")
    print(f"  Mean close:  ${report['mean_diff_close']:.5f}")
    print(f"  P95 |close|: ${report['p95_abs_diff_close']:.5f}")
    print(f"  Max |close|: ${report['max_abs_diff_close']:.5f}")
    print()
    
    # Verdict
    print("=" * 80)
    print("🎯 VERDICT")
    print("=" * 80)
    print()
    
    corr_pass = report['corr_at_lag0'] > 0.7
    dir_pass = report['dir_agree_pct'] > 65
    zero_range_ok = report['zero_range_ratio_a'] < 0.3
    
    if corr_pass and dir_pass and zero_range_ok:
        print("✅ PASS — Dukascopy és compatible per backtest d'Ostium")
        print(f"   Correlació: {report['corr_at_lag0']:.2f} >0.7 ✅")
        print(f"   Dir agree: {report['dir_agree_pct']:.1f}% >65% ✅")
        print(f"   Zero range: {report['zero_range_ratio_a']*100:.1f}% <30% ✅")
    elif corr_pass and dir_pass:
        print("⚠️  PARTIAL — Compatible amb precaució")
        print(f"   Correlació: {report['corr_at_lag0']:.2f} ✅")
        print(f"   Dir agree: {report['dir_agree_pct']:.1f}% ✅")
        print(f"   Zero range: {report['zero_range_ratio_a']*100:.1f}% ⚠️")
    else:
        print("❌ FAIL — Massa diferències, revisar fonts")
        print(f"   Correlació: {report['corr_at_lag0']:.2f} {'✅' if corr_pass else '❌'}")
        print(f"   Dir agree: {report['dir_agree_pct']:.1f}% {'✅' if dir_pass else '❌'}")
    
    print()
    
    # Save report
    if args.outfile:
        outfile = Path(args.outfile)
    else:
        outfile = Path(f"lab/out/ostium_compat_{symbol}_{args.minutes}m.json")
    
    outfile.parent.mkdir(parents=True, exist_ok=True)
    
    with open(outfile, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"📁 Report saved: {outfile}")
    print()


if __name__ == "__main__":
    main()
