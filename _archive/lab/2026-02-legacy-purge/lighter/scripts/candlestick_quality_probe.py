#!/usr/bin/env python3
"""
P8.2 — Candlestick quality probe: investigació zero_range a Lighter EURUSD.

Baixa candles via LighterCandlestickClient (REST directe, sense store/WS).
Calcula: zero_range_ratio, flat_close_ratio, unique_close_ratio, price_step_histogram.

Output: lab/out/candlestick_quality_<symbol>_<minutes>m.json

Ús:
  python3 lab/lighter/scripts/candlestick_quality_probe.py --symbol EURUSD --minutes 180
  python3 lab/lighter/scripts/candlestick_quality_probe.py --symbol XAUUSD --minutes 180
"""
import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "lab" / "lighter" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _price_step_histogram(candles: list) -> dict:
    """Delta de tick mínim: min non-zero step entre preus consecutius."""
    if len(candles) < 2:
        return {"min_nonzero_step": None, "steps_sample": [], "decimals_seen": {}}
    steps = []
    for i in range(1, len(candles)):
        c_prev, c_curr = candles[i - 1], candles[i]
        for field in ("open", "high", "low", "close"):
            v_prev = getattr(c_prev, field) if hasattr(c_prev, field) else c_prev.get(field)
            v_curr = getattr(c_curr, field) if hasattr(c_curr, field) else c_curr.get(field)
            d = abs(v_curr - v_prev)
            if d > 0:
                steps.append(d)
    min_step = min(steps) if steps else None
    decimals = Counter()
    for c in candles[:100]:
        for field in ("open", "high", "low", "close"):
            v = getattr(c, field) if hasattr(c, field) else c.get(field)
            if v is not None:
                s = str(v)
                if "." in s:
                    decimals[len(s.split(".")[-1])] += 1
    return {
        "min_nonzero_step": min_step,
        "steps_sample": sorted(set(steps))[:20] if steps else [],
        "decimals_seen": dict(decimals),
    }


async def run_probe(symbol: str, minutes: int) -> dict:
    from infrastructure.venues.lighter.lighter_candlestick_client import LighterCandlestickClient

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    market_env = "mainnet" if "mainnet" in base_url.lower() else "testnet"

    end_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = (end_ts // 60) * 60
    start_ts = end_ts - minutes * 60

    client = LighterCandlestickClient(base_url=base_url, market_id_map={})
    try:
        rows = await client.fetch_candles(symbol, start_ts, end_ts)
        market_id = client._get_market_id(symbol) if rows else None
    finally:
        await client.close()

    if not rows:
        return {
            "symbol": symbol,
            "minutes": minutes,
            "count": 0,
            "base_url": base_url,
            "market_data_env": market_env,
            "market_id": None,
            "from_epoch": start_ts,
            "to_epoch": end_ts,
            "zero_range_ratio": 0,
            "flat_close_ratio": 0,
            "unique_close_ratio": 0,
            "tick_min": None,
            "delta_close_min_nonzero": None,
            "delta_close_p50_nonzero": None,
            "unique_price_levels_ratio": 0,
            "price_step_histogram": {},
        }

    n = len(rows)
    zero_range = sum(1 for r in rows if r.get("high") == r.get("low")) / n if n else 0
    flat_close = sum(1 for r in rows if r.get("open") == r.get("close")) / n if n else 0
    unique_closes = len(set(r.get("close") for r in rows)) / n if n else 0

    # P8.3.2 Quantització: delta_close, unique_price_levels
    closes = [r.get("close") for r in rows if r.get("close") is not None]
    deltas = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)) if closes[i] != closes[i - 1]]
    delta_close_min_nonzero = min(deltas) if deltas else None
    delta_close_p50_nonzero = sorted(deltas)[len(deltas) // 2] if deltas else None
    unique_price_levels_ratio = len(set(closes)) / len(closes) if closes else 0

    class _C:
        def __init__(self, d):
            self.open = d.get("open")
            self.high = d.get("high")
            self.low = d.get("low")
            self.close = d.get("close")

    candles_obj = [_C(r) for r in rows]
    step_hist = _price_step_histogram(candles_obj)

    tick_min = step_hist.get("min_nonzero_step")
    return {
        "symbol": symbol,
        "minutes": minutes,
        "count": n,
        "base_url": base_url,
        "market_data_env": market_env,
        "market_id": market_id,
        "from_epoch": start_ts,
        "to_epoch": end_ts,
        "zero_range_ratio": round(zero_range, 4),
        "flat_close_ratio": round(flat_close, 4),
        "unique_close_ratio": round(unique_closes, 4),
        "tick_min": tick_min,
        "delta_close_min_nonzero": delta_close_min_nonzero,
        "delta_close_p50_nonzero": delta_close_p50_nonzero,
        "unique_price_levels_ratio": round(unique_price_levels_ratio, 4),
        "price_step_histogram": step_hist,
    }


def main():
    parser = argparse.ArgumentParser(description="P8.2 Candlestick quality probe")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol (EURUSD, XAUUSD)")
    parser.add_argument("--minutes", type=int, default=180, help="Minutes to fetch")
    args = parser.parse_args()

    result = asyncio.run(run_probe(args.symbol.upper(), args.minutes))

    out_dir = ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"candlestick_quality_{result['symbol']}_{result['minutes']}m.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Probe saved: {path}")
    print(f"  zero_range_ratio={result['zero_range_ratio']:.2%} flat_close_ratio={result['flat_close_ratio']:.2%}")
    print(f"  unique_close_ratio={result['unique_close_ratio']:.2%} count={result['count']}")


if __name__ == "__main__":
    main()
