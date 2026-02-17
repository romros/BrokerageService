#!/usr/bin/env python3
"""
P8.3.3 — Debug: raw vs normalized per detectar pèrdua de precisió.

Compara valors raw (del JSON) amb normalized (després del nostre parsing).
Si raw != normalized → problema nostre. Si raw H==L i parsed H==L → font.

Output: lab/out/candlestick_normalization_debug_<symbol>_<minutes>m.json

Ús:
  python3 lab/lighter/scripts/candlestick_normalization_debug.py --symbol EURUSD --minutes 10
"""
import argparse
import asyncio
import json
import os
import sys
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


async def run_debug(symbol: str, minutes: int) -> dict:
    import httpx
    from infrastructure.venues.lighter.lighter_candlestick_client import (
        LighterCandlestickClient,
        _parse_candle,
        _normalize_symbol,
    )

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    client = LighterCandlestickClient(base_url=base_url, market_id_map={})
    await client._ensure_market_ids()
    market_id = client._get_market_id(symbol)
    await client.close()

    end_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = (end_ts // 60) * 60
    start_ts = end_ts - minutes * 60

    url = f"{base_url}/api/v1/candles"
    params = {"market_id": market_id, "resolution": "1m", "start_timestamp": start_ts, "end_timestamp": end_ts, "count_back": min(minutes, 500)}
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(url, params=params, headers={"Accept-Encoding": "identity"})
    r.raise_for_status()
    data = r.json()
    raw_items = data.get("c", []) or []

    symbol_canonical = _normalize_symbol(symbol)
    sample_size = min(20, len(raw_items))
    comparisons = []
    precision_loss_count = 0

    for i, raw in enumerate(raw_items[:sample_size]):
        raw_o = raw.get("o") or raw.get("O")
        raw_h = raw.get("h") or raw.get("H")
        raw_l = raw.get("l") or raw.get("L")
        raw_c = raw.get("c") or raw.get("C")
        parsed = _parse_candle(raw, symbol_canonical)
        cmp = {
            "idx": i,
            "raw_o": raw_o, "raw_h": raw_h, "raw_l": raw_l, "raw_c": raw_c,
            "parsed_o": parsed["open"], "parsed_h": parsed["high"], "parsed_l": parsed["low"], "parsed_c": parsed["close"],
            "raw_h_eq_l": raw_h == raw_l,
            "parsed_h_eq_l": parsed["high"] == parsed["low"],
        }
        if raw_o is not None and parsed["open"] is not None and abs(float(raw_o) - parsed["open"]) > 1e-15:
            precision_loss_count += 1
        comparisons.append(cmp)

    return {
        "symbol": symbol,
        "minutes": minutes,
        "sample_size": sample_size,
        "total_count": len(raw_items),
        "comparisons": comparisons,
        "precision_loss_detected": precision_loss_count,
        "conclusion": "raw_h_eq_l == parsed_h_eq_l → no pèrdua nostra; problema a la font" if all(c["raw_h_eq_l"] == c["parsed_h_eq_l"] for c in comparisons) else "revisar",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--minutes", type=int, default=10)
    args = parser.parse_args()

    result = asyncio.run(run_debug(args.symbol.upper(), args.minutes))

    out_dir = ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"candlestick_normalization_debug_{result['symbol']}_{result['minutes']}m.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Debug saved: {path}")
    print(f"  precision_loss_detected={result['precision_loss_detected']} conclusion={result['conclusion']}")


if __name__ == "__main__":
    main()
