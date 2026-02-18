#!/usr/bin/env python3
"""
Ostium REST Price Probe — Validate collected candle data quality

Validates coverage, gaps, duplicates, timestamp integrity of collected candles.
Trading hours aware (RWA markets closed weekends).

Usage:
    python3 rest_price_probe.py --symbol EURUSD --indir lab/out/ostium_prices/<run_id>
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ============================================================================
# Trading Hours Config (RWA)
# ============================================================================

# EUR/USD trading hours: Mo-Fr 04:00-20:00 ET (America/New_York)
# For simplicity, we assume UTC+0 and approximate:
# - Weekends (Sat/Sun) are OFF
# - Holidays are NOT checked (would need calendar API)

def is_trading_hour(ts: int, symbol: str) -> bool:
    """
    Check if timestamp is within trading hours for RWA symbol.
    
    Simplified: Only checks weekends. Holidays NOT included.
    """
    if symbol not in ["EURUSD", "XAUUSD", "GBPUSD", "GBPJPY"]:
        # Crypto pairs are 24/7
        return True
    
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    
    # Weekend check (Sat=5, Sun=6)
    if dt.weekday() >= 5:
        return False
    
    # TODO: Add holiday calendar check if needed
    # For MVP, weekend check is sufficient
    
    return True


# ============================================================================
# Probe Logic
# ============================================================================

def load_candles(jsonl_file: Path) -> List[Dict]:
    """Load candles from JSONL file"""
    candles = []
    
    if not jsonl_file.exists():
        print(f"❌ File not found: {jsonl_file}")
        return []
    
    with open(jsonl_file, "r") as f:
        for line in f:
            try:
                candle = json.loads(line)
                candles.append(candle)
            except json.JSONDecodeError as e:
                print(f"⚠️  Skipping invalid JSON line: {line[:50]}... ({e})")
    
    return candles


def probe_candles(
    candles: List[Dict],
    symbol: str,
    check_trading_hours: bool
) -> Dict:
    """
    Probe candle quality metrics.
    
    Returns dict with:
    - candles_raw: total candles loaded
    - candles_unique: after dedup by ts
    - duplicates: count
    - missing_minutes: gaps in sequence
    - max_gap_s: largest gap
    - ts_step_errors: candles not at 60s intervals
    - zero_range_count: H==L
    - zero_range_ratio: % of candles with H==L
    - first_ts, last_ts: coverage range
    - expected_minutes: if check_trading_hours, exclude weekends
    """
    
    if not candles:
        return {"error": "No candles to probe"}
    
    # Sort by ts
    candles = sorted(candles, key=lambda c: c["ts"])
    
    candles_raw = len(candles)
    
    # Dedup by ts
    ts_set = set()
    candles_unique = []
    duplicates = 0
    
    for c in candles:
        if c["ts"] in ts_set:
            duplicates += 1
        else:
            ts_set.add(c["ts"])
            candles_unique.append(c)
    
    candles = candles_unique  # Work with deduplicated
    
    first_ts = candles[0]["ts"]
    last_ts = candles[-1]["ts"]
    
    # Expected minutes (60s intervals)
    expected_minutes_total = (last_ts - first_ts) // 60 + 1
    
    # If check_trading_hours, exclude weekends
    if check_trading_hours:
        expected_minutes = 0
        for i in range(expected_minutes_total):
            ts = first_ts + i * 60
            if is_trading_hour(ts, symbol):
                expected_minutes += 1
    else:
        expected_minutes = expected_minutes_total
    
    candles_unique_count = len(candles)
    missing_minutes = expected_minutes - candles_unique_count
    
    # Gap analysis
    gaps = []
    ts_step_errors = 0
    
    for i in range(1, len(candles)):
        prev_ts = candles[i - 1]["ts"]
        curr_ts = candles[i]["ts"]
        
        gap_s = curr_ts - prev_ts
        
        if gap_s != 60:
            ts_step_errors += 1
            gaps.append(gap_s)
    
    max_gap_s = max(gaps) if gaps else 0
    
    # Zero range check (H==L)
    zero_range_count = sum(1 for c in candles if c["h"] == c["l"])
    zero_range_ratio = zero_range_count / len(candles) if candles else 0
    
    # Timestamp distribution
    ts_counter = Counter(c["ts"] for c in candles)
    ts_duplicates = {ts: count for ts, count in ts_counter.items() if count > 1}
    
    return {
        "symbol": symbol,
        "candles_raw": candles_raw,
        "candles_unique": candles_unique_count,
        "duplicates": duplicates,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_ts_human": datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "last_ts_human": datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "expected_minutes": expected_minutes,
        "expected_minutes_total": expected_minutes_total,
        "missing_minutes": missing_minutes,
        "max_gap_s": max_gap_s,
        "ts_step_errors": ts_step_errors,
        "zero_range_count": zero_range_count,
        "zero_range_ratio": round(zero_range_ratio, 4),
        "check_trading_hours": check_trading_hours,
        "ts_duplicates": ts_duplicates if ts_duplicates else None
    }


# ============================================================================
# Output
# ============================================================================

def print_probe_results(results: Dict):
    """Print probe results to console"""
    
    print()
    print("=" * 80)
    print("📊 PROBE RESULTS")
    print("=" * 80)
    print()
    
    if "error" in results:
        print(f"❌ {results['error']}")
        return
    
    print(f"Symbol:             {results['symbol']}")
    print(f"Candles (raw):      {results['candles_raw']}")
    print(f"Candles (unique):   {results['candles_unique']}")
    print(f"Duplicates:         {results['duplicates']}")
    print()
    
    print(f"Coverage:")
    print(f"  First:            {results['first_ts_human']} ({results['first_ts']})")
    print(f"  Last:             {results['last_ts_human']} ({results['last_ts']})")
    print(f"  Duration:         {(results['last_ts'] - results['first_ts']) // 60} minutes")
    print()
    
    print(f"Expected minutes:   {results['expected_minutes']}")
    if results['check_trading_hours']:
        print(f"  (excluding weekends: {results['expected_minutes_total']} → {results['expected_minutes']})")
    print(f"Missing minutes:    {results['missing_minutes']}")
    print(f"Max gap:            {results['max_gap_s']}s")
    print(f"TS step errors:     {results['ts_step_errors']}")
    print()
    
    print(f"Quality:")
    print(f"  Zero range (H==L): {results['zero_range_count']} ({results['zero_range_ratio'] * 100:.1f}%)")
    print()
    
    # Health check
    print("=" * 80)
    print("🔍 HEALTH CHECK")
    print("=" * 80)
    print()
    
    checks = []
    
    # Duplicates
    if results['duplicates'] == 0:
        checks.append(("✅", "No duplicates"))
    else:
        checks.append(("❌", f"Duplicates found: {results['duplicates']}"))
    
    # Missing minutes
    if results['missing_minutes'] <= 2:
        checks.append(("✅", f"Missing minutes acceptable: {results['missing_minutes']} ≤2"))
    else:
        checks.append(("⚠️", f"Missing minutes high: {results['missing_minutes']} >2"))
    
    # TS step errors
    if results['ts_step_errors'] == 0:
        checks.append(("✅", "All candles at 60s intervals"))
    else:
        checks.append(("⚠️", f"TS step errors: {results['ts_step_errors']}"))
    
    # Max gap
    if results['max_gap_s'] <= 300:
        checks.append(("✅", f"Max gap acceptable: {results['max_gap_s']}s ≤300s"))
    else:
        checks.append(("⚠️", f"Max gap high: {results['max_gap_s']}s >300s"))
    
    # Zero range
    if results['zero_range_ratio'] < 0.3:
        checks.append(("✅", f"Zero range acceptable: {results['zero_range_ratio'] * 100:.1f}% <30%"))
    else:
        checks.append(("⚠️", f"Zero range high: {results['zero_range_ratio'] * 100:.1f}% ≥30%"))
    
    for icon, msg in checks:
        print(f"{icon} {msg}")
    
    print()
    
    # Overall verdict
    failed = sum(1 for icon, _ in checks if icon in ["❌", "⚠️"])
    
    if failed == 0:
        print("✅ PASS — Data quality is good")
    elif failed <= 2:
        print("⚠️  PARTIAL — Some issues found, review recommended")
    else:
        print("❌ FAIL — Multiple issues, data may not be suitable")
    
    print()


def save_probe_artifact(results: Dict, outfile: Path):
    """Save probe results to JSON artifact"""
    with open(outfile, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"📁 Artifact saved: {outfile}")
    print()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ostium REST Price Probe — Validate candle data quality"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Symbol to probe (e.g. EURUSD)"
    )
    parser.add_argument(
        "--indir",
        required=True,
        help="Input directory (e.g. lab/out/ostium_prices/20260217_120000)"
    )
    parser.add_argument(
        "--check-trading-hours",
        action="store_true",
        help="Exclude weekends/holidays from expected_minutes (RWA only)"
    )
    parser.add_argument(
        "--outfile",
        help="Output JSON file (default: lab/out/ostium_price_probe_<symbol>.json)"
    )
    
    args = parser.parse_args()
    
    indir = Path(args.indir)
    jsonl_file = indir / f"{args.symbol}.jsonl"
    
    print()
    print("=" * 80)
    print("🔍 OSTIUM REST PRICE PROBE")
    print("=" * 80)
    print()
    print(f"Symbol:             {args.symbol}")
    print(f"Input dir:          {indir}")
    print(f"JSONL file:         {jsonl_file}")
    print(f"Check trading hrs:  {args.check_trading_hours}")
    print()
    
    # Load candles
    print("📂 Loading candles...")
    candles = load_candles(jsonl_file)
    
    if not candles:
        print("❌ No candles loaded. Exiting.")
        sys.exit(1)
    
    print(f"✅ Loaded {len(candles)} candles")
    
    # Probe
    print("🔍 Running probe...")
    results = probe_candles(
        candles=candles,
        symbol=args.symbol,
        check_trading_hours=args.check_trading_hours
    )
    
    # Print results
    print_probe_results(results)
    
    # Save artifact
    if args.outfile:
        outfile = Path(args.outfile)
    else:
        outfile = Path(f"lab/out/ostium_price_probe_{args.symbol}.json")
    
    outfile.parent.mkdir(parents=True, exist_ok=True)
    save_probe_artifact(results, outfile)


if __name__ == "__main__":
    main()
