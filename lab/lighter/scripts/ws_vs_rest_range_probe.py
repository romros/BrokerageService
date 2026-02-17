#!/usr/bin/env python3
"""
P8.3.4 — Cross-check: % minuts H!=L en WS vs REST.

Compara candles WS (pipeline live) amb REST candlestick (mateixos minuts).
Mètrica: pct_ws_h_ne_l, pct_rest_h_ne_l.

Requereix: broker en marxa amb Lighter (mainnet EURUSD/XAU).
Opt-in: docker compose up brokerage; després executar.

Output: lab/out/ws_vs_rest_range_<symbol>_<minutes>m.json

Ús:
  # Primer: docker compose up -d brokerage (amb LIGHTER_BASE_URL mainnet)
  python3 lab/lighter/scripts/ws_vs_rest_range_probe.py --symbol EURUSD --minutes 30
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "lab" / "lighter" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:
    pass


async def run_probe(symbol: str, minutes: int, ws_url: str) -> dict:
    from application.tools.ws_soak import collect_ws_candles
    from foundation.config.constants import SUPPORTED_TIMEFRAME
    from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import LighterCandlestickBackfillProvider

    topic = f"candle:{symbol}:{SUPPORTED_TIMEFRAME}"
    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")

    print(f"  Collecting WS candles ({minutes} min)...")
    ws_candles, _ = await collect_ws_candles(ws_url, topic, minutes, allow_reconnects=2)

    if len(ws_candles) < 2:
        return {"symbol": symbol, "minutes": minutes, "error": f"WS collected {len(ws_candles)} candles", "pct_ws_h_ne_l": 0, "pct_rest_h_ne_l": 0}

    ws_by_ts = {c["ts"]: c for c in ws_candles}
    start_ts = min(ws_by_ts.keys())
    end_ts = max(ws_by_ts.keys()) + 60

    print(f"  Fetching REST [{start_ts}, {end_ts})...")
    provider = LighterCandlestickBackfillProvider(base_url=base_url)
    from datetime import datetime, timezone
    start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
    rest_candles = await provider.fetch_ohlcv(symbol, start_dt, end_dt)
    await provider._client.close()

    rest_by_ts = {int(c.timestamp.timestamp()): c for c in rest_candles}
    common_ts = set(ws_by_ts.keys()) & set(rest_by_ts.keys())

    ws_h_ne_l = sum(1 for ts in common_ts if ws_by_ts[ts].get("h") != ws_by_ts[ts].get("l"))
    rest_h_ne_l = sum(1 for ts in common_ts if rest_by_ts[ts].high != rest_by_ts[ts].low)
    n = len(common_ts) if common_ts else 0

    return {
        "symbol": symbol,
        "minutes": minutes,
        "common_count": n,
        "pct_ws_h_ne_l": round(ws_h_ne_l / n * 100, 2) if n else 0,
        "pct_rest_h_ne_l": round(rest_h_ne_l / n * 100, 2) if n else 0,
        "ws_h_ne_l_count": ws_h_ne_l,
        "rest_h_ne_l_count": rest_h_ne_l,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--ws-url", default=os.getenv("WS_URL", "ws://localhost:8000/api/v1/ws"))
    args = parser.parse_args()

    try:
        result = asyncio.run(run_probe(args.symbol.upper(), args.minutes, args.ws_url))
    except Exception as e:
        result = {"symbol": args.symbol, "minutes": args.minutes, "error": str(e), "pct_ws_h_ne_l": 0, "pct_rest_h_ne_l": 0}

    out_dir = ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"ws_vs_rest_range_{result['symbol']}_{result['minutes']}m.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Probe saved: {path}")
    if "error" not in result:
        print(f"  pct_ws_h_ne_l={result['pct_ws_h_ne_l']}% pct_rest_h_ne_l={result['pct_rest_h_ne_l']}%")


if __name__ == "__main__":
    main()
