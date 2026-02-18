#!/usr/bin/env python3
"""
Ostium REST Price Collector — Mainnet Price Monitoring

Captura preus via polling REST /latest-price i construeix candles 1m.
Restartable, multi-symbol, persisteix a JSONL.

Default: run indefinit (--forever), append a continuous/, símbols EURUSD,XAUUSD,GBPJPY.
Dukascopy només suporta EURUSD i XAUUSD per compat; GBPJPY per mostra addicional.

Usage:
    python3 rest_price_collector.py                    # indefinit (default)
    python3 rest_price_collector.py --hours 72         # limitat a 72h
    python3 rest_price_collector.py --symbols EURUSD,XAUUSD  # només compat

Similar a ws_candle_collector.py (Lighter) però per REST polling.
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests


# ============================================================================
# Config
# ============================================================================

OSTIUM_PRICE_API_BASE = os.getenv(
    "OSTIUM_PRICE_API_BASE",
    "https://metadata-backend.ostium.io"
)

DEFAULT_POLL_INTERVAL_S = int(os.getenv("OSTIUM_POLL_INTERVAL_S", "10"))
DEFAULT_OUTDIR = "lab/out/ostium_prices"
OSTIUM_LAB_RETENTION_DAYS_ENV = "OSTIUM_LAB_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 14

# Rate limit handling
MAX_RETRIES = 3
RETRY_BACKOFF_S = [1, 2, 4]  # Exponential backoff


# ============================================================================
# Data Models
# ============================================================================

class Tick:
    """Single price tick"""
    def __init__(self, ts: int, price: float):
        self.ts = ts  # epoch seconds UTC
        self.price = price

    def __repr__(self):
        return f"Tick(ts={self.ts}, price={self.price})"


class Candle:
    """1-minute OHLC candle"""
    def __init__(self, ts: int, o: float, h: float, l: float, c: float):
        self.ts = ts  # start-of-minute epoch UTC
        self.o = o
        self.h = h
        self.l = l
        self.c = c

    def to_dict(self):
        return {
            "ts": self.ts,
            "o": self.o,
            "h": self.h,
            "l": self.l,
            "c": self.c,
            "v": 0  # Volume N/A for polling
        }

    def __repr__(self):
        dt = datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        return f"Candle({dt} UTC | O={self.o:.5f} H={self.h:.5f} L={self.l:.5f} C={self.c:.5f})"


# ============================================================================
# REST Client
# ============================================================================

def fetch_latest_price(symbol: str) -> Optional[Dict]:
    """
    Fetch latest price from Ostium REST API.
    
    Returns:
        {"price": 1.12345, "timestamp": 1234567890} or None if error
    """
    url = f"{OSTIUM_PRICE_API_BASE}/PricePublish/latest-price"
    params = {"asset": symbol}
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Actual format: {"mid": 1.12345, "bid": 1.12340, "ask": 1.12350, "timestampSeconds": 1234567890, ...}
                price = float(data.get("mid", 0))
                
                # Timestamp is in seconds
                ts = int(data.get("timestampSeconds", time.time()))
                
                return {"price": price, "timestamp": ts}
                
            elif response.status_code == 429:
                # Rate limit
                backoff = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                print(f"⚠️  Rate limit 429 for {symbol}, retry in {backoff}s...")
                time.sleep(backoff)
                continue
                
            else:
                print(f"❌ HTTP {response.status_code} for {symbol}: {response.text[:100]}")
                return None
                
        except Exception as e:
            print(f"❌ Error fetching {symbol}: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_S[attempt])
            else:
                return None
    
    return None


# ============================================================================
# Candle Builder
# ============================================================================

class CandleBuilder:
    """Builds 1m candles from accumulated ticks"""
    
    def __init__(self):
        self.ticks: Dict[str, List[Tick]] = defaultdict(list)
        self.last_candle_ts: Dict[str, int] = {}
    
    def add_tick(self, symbol: str, tick: Tick):
        """Add tick to buffer"""
        self.ticks[symbol].append(tick)
    
    def flush_candles(self, symbol: str, now_ts: int) -> List[Candle]:
        """
        Flush completed candles (current minute not included).
        
        Returns list of candles ready to persist.
        """
        if symbol not in self.ticks or not self.ticks[symbol]:
            return []
        
        ticks = self.ticks[symbol]
        candles = []
        
        # Group ticks by minute
        minute_ticks: Dict[int, List[Tick]] = defaultdict(list)
        for tick in ticks:
            minute_start = (tick.ts // 60) * 60
            minute_ticks[minute_start].append(tick)
        
        # Build candles for completed minutes only
        current_minute = (now_ts // 60) * 60
        
        for minute_start in sorted(minute_ticks.keys()):
            if minute_start >= current_minute:
                # Current minute not yet complete
                continue
            
            minute_ticks_list = minute_ticks[minute_start]
            
            if not minute_ticks_list:
                continue
            
            # OHLC from ticks
            prices = [t.price for t in minute_ticks_list]
            o = minute_ticks_list[0].price  # first
            h = max(prices)
            l = min(prices)
            c = minute_ticks_list[-1].price  # last
            
            candle = Candle(ts=minute_start, o=o, h=h, l=l, c=c)
            candles.append(candle)
            
            self.last_candle_ts[symbol] = minute_start
        
        # Remove flushed ticks
        if candles:
            last_flushed_ts = candles[-1].ts + 59  # end of last minute
            self.ticks[symbol] = [t for t in ticks if t.ts > last_flushed_ts]
        
        return candles


# ============================================================================
# Persistence
# ============================================================================

class PersistenceManager:
    """Manages JSONL files + state.json + STATUS.md. Optional daily rotation + retention."""

    LATEST_RUN_FILENAME = "LATEST_RUN.txt"

    def __init__(
        self,
        outdir: Path,
        run_id: str,
        enable_daily_rotation: bool = False,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        self.base_outdir = Path(outdir)
        self.run_id = run_id
        self.outdir = self.base_outdir / run_id
        self.outdir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.outdir / "state.json"
        self.status_file = self.outdir / "STATUS.md"

        self.enable_daily_rotation = enable_daily_rotation
        self.retention_days = retention_days
        self.daily_base = self.base_outdir / "daily"
        self._current_daily_date: Optional[str] = None

        self.state = self.load_state()
        self.stats: Dict[str, Dict] = defaultdict(lambda: {
            "candles": 0,
            "last_ts": None,
            "gaps": 0,
            "duplicates": 0
        })
    
    def load_state(self) -> Dict:
        """Load state.json (for resume)"""
        if self.state_file.exists():
            with open(self.state_file, "r") as f:
                return json.load(f)
        return {}
    
    def save_state(self):
        """Save state.json"""
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)
    
    def _append_to_daily(self, symbol: str, candles: List[Candle], now_ts: int):
        """Append candles to daily/YYYYMMDD/ (only candles for current day)."""
        if not self.enable_daily_rotation or not candles:
            return
        today_str = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y%m%d")
        day_candles = [c for c in candles if datetime.fromtimestamp(c.ts, tz=timezone.utc).strftime("%Y%m%d") == today_str]
        if not day_candles:
            return
        daily_dir = self.daily_base / today_str
        daily_dir.mkdir(parents=True, exist_ok=True)
        jsonl_file = daily_dir / f"{symbol}.jsonl"
        existing_ts: set = set()
        if jsonl_file.exists():
            with open(jsonl_file, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        existing_ts.add(data["ts"])
                    except Exception:
                        pass
        with open(jsonl_file, "a") as f:
            for candle in day_candles:
                if candle.ts not in existing_ts:
                    f.write(json.dumps(candle.to_dict()) + "\n")
                    existing_ts.add(candle.ts)
        self._update_latest_run(today_str)
        self._run_retention(now_ts)

    def _update_latest_run(self, date_str: str):
        """Write daily/LATEST_RUN.txt with path to current day."""
        self.daily_base.mkdir(parents=True, exist_ok=True)
        pointer_file = self.daily_base / self.LATEST_RUN_FILENAME
        with open(pointer_file, "w") as f:
            f.write(f"daily/{date_str}\n")

    def _run_retention(self, now_ts: int):
        """Remove daily dirs older than retention_days."""
        if self.retention_days <= 0:
            return
        cutoff = now_ts - (self.retention_days * 86400)
        if not self.daily_base.exists():
            return
        for p in self.daily_base.iterdir():
            if p.name == self.LATEST_RUN_FILENAME:
                continue
            if not p.is_dir():
                continue
            try:
                # Parse YYYYMMDD from dir name
                dt = datetime.strptime(p.name, "%Y%m%d").replace(tzinfo=timezone.utc)
                if dt.timestamp() < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
            except ValueError:
                pass

    def append_candles(self, symbol: str, candles: List[Candle], now_ts: Optional[int] = None):
        """Append candles to JSONL file (continuous). Optionally to daily/YYYYMMDD/."""
        if not candles:
            return
        now_ts = now_ts or int(time.time())

        jsonl_file = self.outdir / f"{symbol}.jsonl"

        # Dedup check
        existing_ts = set()
        if jsonl_file.exists():
            with open(jsonl_file, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        existing_ts.add(data["ts"])
                    except Exception:
                        pass

        # Append new candles
        with open(jsonl_file, "a") as f:
            for candle in candles:
                if candle.ts in existing_ts:
                    self.stats[symbol]["duplicates"] += 1
                    continue

                f.write(json.dumps(candle.to_dict()) + "\n")
                self.stats[symbol]["candles"] += 1
                self.stats[symbol]["last_ts"] = candle.ts
                existing_ts.add(candle.ts)

        self._append_to_daily(symbol, candles, now_ts)

        # Update state
        self.state[symbol] = {
            "last_ts_written": max(c.ts for c in candles),
            "candles_total": self.stats[symbol]["candles"]
        }
        self.save_state()
    
    def update_status(self, symbols: List[str], elapsed_s: int, target_s: int, forever: bool = False):
        """Write STATUS.md with progress table"""
        if forever or target_s <= 0:
            elapsed_str = f"{elapsed_s}s (continuous)"
        else:
            elapsed_str = f"{elapsed_s}s / {target_s}s ({elapsed_s / target_s * 100:.1f}%)"
        lines = [
            "# Ostium REST Price Collector — Status",
            "",
            f"**Run ID:** {self.outdir.name}",
            f"**Started:** {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Elapsed:** {elapsed_str}",
            "",
            "## Progress",
            "",
            "| Symbol | Candles | Last TS | Last TS (human) | Gaps | Duplicates | Status |",
            "|--------|---------|---------|-----------------|------|------------|--------|"
        ]
        
        for symbol in sorted(symbols):
            stats = self.stats[symbol]
            last_ts = stats["last_ts"]
            last_ts_human = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if last_ts else "N/A"
            
            status = "✅ OK" if stats["candles"] > 0 else "⏳ Waiting"
            
            lines.append(
                f"| {symbol} | {stats['candles']} | {last_ts or 'N/A'} | {last_ts_human} | "
                f"{stats['gaps']} | {stats['duplicates']} | {status} |"
            )
        
        lines.append("")
        lines.append("---")
        lines.append(f"**Artifacts:** `{self.outdir}`")
        
        with open(self.status_file, "w") as f:
            f.write("\n".join(lines))


# ============================================================================
# Collector
# ============================================================================

async def run_collector(
    symbols: List[str],
    hours: float,
    poll_interval_s: int,
    outdir: str,
    resume: bool,
    forever: bool = False,
    enable_daily_rotation: bool = False,
    retention_days: int = DEFAULT_RETENTION_DAYS,
):
    """Main collector loop"""
    run_id = "continuous" if forever else datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    pm = PersistenceManager(
        Path(outdir),
        run_id,
        enable_daily_rotation=enable_daily_rotation and forever,
        retention_days=retention_days,
    )
    
    print("=" * 80)
    print("🧪 OSTIUM REST PRICE COLLECTOR")
    print("=" * 80)
    print()
    print(f"Symbols:        {', '.join(symbols)}")
    print(f"Duration:       {'continuous (--forever)' if forever else f'{hours}h ({hours * 3600}s)'}")
    print(f"Poll interval:  {poll_interval_s}s")
    print(f"Output dir:     {pm.outdir}")
    print(f"Resume:         {'Yes' if resume else 'No'}")
    print()
    
    if resume and pm.state:
        print("📂 Resuming from state:")
        for sym, state in pm.state.items():
            last_ts = state.get("last_ts_written", "N/A")
            last_ts_human = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if isinstance(last_ts, int) else "N/A"
            print(f"   {sym}: {state.get('candles_total', 0)} candles, last {last_ts_human}")
        print()
    
    builder = CandleBuilder()
    
    start_time = time.time()
    target_duration_s = hours * 3600 if not forever else 0
    last_status_update = time.time()
    status_update_interval = 30  # Update STATUS.md every 30s
    
    try:
        while True:
            elapsed = time.time() - start_time
            
            if not forever and elapsed >= target_duration_s:
                print(f"\n✅ Target duration {hours}h reached. Stopping.")
                break
            
            loop_start = time.time()
            
            # Poll all symbols
            for symbol in symbols:
                result = fetch_latest_price(symbol)
                
                if result:
                    tick = Tick(ts=result["timestamp"], price=result["price"])
                    builder.add_tick(symbol, tick)
                    
                    # NY time (UTC-5 EST)
                    ny_time = datetime.fromtimestamp(tick.ts, tz=timezone.utc) - timedelta(hours=5)
                    print(f"[{elapsed:.0f}s] {symbol}: ${result['price']:.5f} @ {ny_time.strftime('%H:%M:%S')} ET")
                else:
                    print(f"[{elapsed:.0f}s] {symbol}: ❌ Failed to fetch")
            
            # Flush completed candles
            now_ts = int(time.time())
            for symbol in symbols:
                candles = builder.flush_candles(symbol, now_ts)
                if candles:
                    pm.append_candles(symbol, candles, now_ts=now_ts)
                    print(f"   ✅ Flushed {len(candles)} candle(s) for {symbol}")
            
            # Update STATUS.md periodically
            if time.time() - last_status_update >= status_update_interval:
                pm.update_status(symbols, int(elapsed), target_duration_s, forever=forever)
                last_status_update = time.time()
            
            # Sleep until next poll
            loop_duration = time.time() - loop_start
            sleep_time = max(0, poll_interval_s - loop_duration)
            
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
    
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user. Flushing remaining candles...")
    
    # Final flush
    now_ts = int(time.time())
    for symbol in symbols:
        candles = builder.flush_candles(symbol, now_ts)
        if candles:
            pm.append_candles(symbol, candles, now_ts=now_ts)
            print(f"   ✅ Final flush: {len(candles)} candle(s) for {symbol}")
    
    # Final status
    pm.update_status(symbols, int(time.time() - start_time), target_duration_s, forever=forever)
    
    print()
    print("=" * 80)
    print("✅ COLLECTION COMPLETED")
    print("=" * 80)
    print()
    print(f"Artifacts: {pm.outdir}")
    print()
    
    for symbol in symbols:
        stats = pm.stats[symbol]
        print(f"{symbol}:")
        print(f"  Candles:    {stats['candles']}")
        print(f"  Last TS:    {datetime.fromtimestamp(stats['last_ts'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if stats['last_ts'] else 'N/A'}")
        print(f"  Duplicates: {stats['duplicates']}")
        print()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ostium REST Price Collector — Poll latest-price and build 1m candles"
    )
    parser.add_argument(
        "--symbols",
        default="EURUSD,XAUUSD,GBPJPY",
        help="Comma-separated symbols (default: EURUSD,XAUUSD,GBPJPY)"
    )
    parser.add_argument(
        "--forever",
        action="store_true",
        help="Run indefinitely (default when no --hours/--minutes)"
    )
    parser.add_argument(
        "--hours",
        type=int,
        help="Duration in hours (mutually exclusive with --minutes and --forever)"
    )
    parser.add_argument(
        "--minutes",
        type=int,
        help="Duration in minutes (mutually exclusive with --hours and --forever)"
    )
    parser.add_argument(
        "--poll-interval-s",
        type=int,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"Polling interval in seconds (default: {DEFAULT_POLL_INTERVAL_S})"
    )
    parser.add_argument(
        "--outdir",
        default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})"
    )
    parser.add_argument(
        "--resume",
        type=int,
        default=1,
        help="Resume from state.json if exists (0=no, 1=yes, default: 1)"
    )
    parser.add_argument(
        "--enable-daily-rotation",
        action="store_true",
        help="Enable daily rotation (daily/YYYYMMDD/ + LATEST_RUN.txt + retention)"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=f"Retention days for daily dirs (default: {DEFAULT_RETENTION_DAYS}, env OSTIUM_LAB_RETENTION_DAYS)"
    )

    args = parser.parse_args()
    
    # Handle hours/minutes/forever
    if sum([bool(args.hours), bool(args.minutes), args.forever]) > 1:
        parser.error("Cannot specify both --hours, --minutes and --forever")
    if args.minutes:
        hours = args.minutes / 60.0
        forever = False
    elif args.hours:
        hours = args.hours
        forever = False
    elif args.forever:
        hours = 0
        forever = True
    else:
        # Default: run indefinit per acumular mostra (no sabem quan caldrà aturar)
        hours = 0
        forever = True
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    retention = args.retention_days
    if retention is None:
        retention = int(os.getenv(OSTIUM_LAB_RETENTION_DAYS_ENV, str(DEFAULT_RETENTION_DAYS)))

    asyncio.run(run_collector(
        symbols=symbols,
        hours=hours,
        poll_interval_s=args.poll_interval_s,
        outdir=args.outdir,
        resume=bool(args.resume),
        forever=forever,
        enable_daily_rotation=args.enable_daily_rotation,
        retention_days=retention,
    ))


if __name__ == "__main__":
    main()
