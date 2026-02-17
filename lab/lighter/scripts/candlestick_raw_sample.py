#!/usr/bin/env python3
"""
P8.3 — Raw sample: inspecció de respostes REST candlestick sense parsing.

Fa 1–3 requests REST i guarda URL, params, resposta raw, parse result.
Permet verificar si el problema zero_range ve de la font o del nostre parsing.

Output: lab/out/candlestick_raw_<symbol>_<minutes>m.json

Ús:
  python3 lab/lighter/scripts/candlestick_raw_sample.py --symbol EURUSD --minutes 10
  docker compose run --rm lighter-lab python3 lab/lighter/scripts/candlestick_raw_sample.py --symbol EURUSD --minutes 10
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


def _raw_val(obj, k1: str, k2: str):
    """Extreu valor de raw item (dict o object)."""
    if isinstance(obj, dict):
        return obj.get(k1) or obj.get(k2)
    return getattr(obj, k1, None) or getattr(obj, k2, None)


def _parse_candle_raw(obj, symbol: str) -> dict:
    """Parse raw candle (dict o object) a dict canònic."""
    def _get(o, *keys):
        for k in keys:
            if isinstance(o, dict):
                v = o.get(k)
            else:
                v = getattr(o, k, None)
            if v is not None:
                return v
        return None
    t_raw = int(_get(obj, "t", "T") or 0)
    ts_s = t_raw // 1000 if t_raw > 1e12 else t_raw
    ts = (ts_s // 60) * 60
    o = float(_get(obj, "o", "O") or 0)
    h = float(_get(obj, "h", "H") or 0)
    l_ = float(_get(obj, "l", "L") or 0)
    c_ = float(_get(obj, "c", "C") or 0)
    v = float(_get(obj, "v", "V") or 0)
    return {"ts": ts, "open": o, "high": h, "low": l_, "close": c_, "volume": v, "symbol": symbol}


async def run_raw_sample(symbol: str, minutes: int) -> dict:
    import httpx

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    endpoint = "/api/v1/candles"

    # Obtenir market_id
    from infrastructure.venues.lighter.lighter_candlestick_client import (
        LighterCandlestickClient,
        _normalize_symbol,
    )
    client = LighterCandlestickClient(base_url=base_url, market_id_map={})
    await client._ensure_market_ids()
    market_id = client._get_market_id(symbol)
    await client.close()

    end_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = (end_ts // 60) * 60
    start_ts = end_ts - minutes * 60
    count_back = min(minutes, 500)

    params = {
        "market_id": market_id,
        "resolution": "1m",
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "count_back": count_back,
    }
    url = f"{base_url}{endpoint}"
    headers = {"Accept-Encoding": "identity"}

    requests_made = []
    all_raw_items = []
    symbol_canonical = _normalize_symbol(symbol)

    async with httpx.AsyncClient(timeout=30.0) as client_http:
        r = await client_http.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()

    raw_c = data.get("c", []) or []
    requests_made.append({
        "url": url,
        "params": params,
        "status": 200,
        "raw_count": len(raw_c),
    })

    # Subset raw per no fer l'artifact enorme (primeres 5 + últimes 5 items)
    raw_sample = raw_c[:5] + raw_c[-5:] if len(raw_c) > 10 else raw_c
    raw_sample_serializable = []
    for item in raw_sample:
        if isinstance(item, dict):
            raw_sample_serializable.append(item)
        else:
            raw_sample_serializable.append({k: getattr(item, k, None) for k in ("t", "T", "o", "O", "h", "H", "l", "L", "c", "C", "v", "V") if hasattr(item, k)})

    parsed = [_parse_candle_raw(c, symbol_canonical) for c in raw_c]
    first_ts = parsed[0]["ts"] if parsed else None
    last_ts = parsed[-1]["ts"] if parsed else None
    sample_first = parsed[:3] if len(parsed) >= 3 else parsed
    sample_last = parsed[-3:] if len(parsed) >= 3 else []

    return {
        "symbol": symbol,
        "minutes": minutes,
        "base_url": base_url,
        "endpoint": endpoint,
        "params": params,
        "requests": requests_made,
        "raw_response_sample": raw_sample_serializable,
        "parse_result": {
            "first_ts": first_ts,
            "last_ts": last_ts,
            "count": len(parsed),
            "sample_first_3": sample_first,
            "sample_last_3": sample_last,
        },
        "raw_vs_parsed_check": {
            "raw_h_eq_l_count": sum(1 for c in raw_c if _raw_val(c, "h", "H") == _raw_val(c, "l", "L")) if raw_c else 0,
            "parsed_h_eq_l_count": sum(1 for p in parsed if p["high"] == p["low"]),
            "raw_o_eq_c_count": sum(1 for c in raw_c if _raw_val(c, "o", "O") == _raw_val(c, "c", "C")) if raw_c else 0,
            "parsed_o_eq_c_count": sum(1 for p in parsed if p["open"] == p["close"]),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="P8.3 Candlestick raw sample")
    parser.add_argument("--symbol", default="EURUSD", help="Symbol (EURUSD, XAUUSD)")
    parser.add_argument("--minutes", type=int, default=10, help="Minutes to fetch")
    parser.add_argument("--out", default=None, help="Output path (default: lab/out/candlestick_raw_<symbol>_<minutes>m.json)")
    args = parser.parse_args()

    result = asyncio.run(run_raw_sample(args.symbol.upper(), args.minutes))

    out_dir = ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = Path(args.out) if args.out else out_dir / f"candlestick_raw_{result['symbol']}_{result['minutes']}m.json"
    if not path.is_absolute():
        path = out_dir / path.name
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Raw sample saved: {path}")
    pr = result["parse_result"]
    rv = result["raw_vs_parsed_check"]
    print(f"  count={pr['count']} first_ts={pr['first_ts']} last_ts={pr['last_ts']}")
    print(f"  raw H==L: {rv['raw_h_eq_l_count']}/{pr['count']}  parsed H==L: {rv['parsed_h_eq_l_count']}/{pr['count']}")


if __name__ == "__main__":
    main()
