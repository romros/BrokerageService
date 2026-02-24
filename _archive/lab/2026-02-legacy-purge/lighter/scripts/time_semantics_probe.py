#!/usr/bin/env python3
"""
P0.3b — Lighter Candle Time Semantics Probe (TZ + boundary)

Demostra amb evidència si les candles de Lighter venen en UTC start-of-minute,
o si hi ha offset / "NY close style", i defineix la conversió canònica.

Output: lab/out/time_semantics_<symbol>.json

Ús:
  docker compose run --rm lighter-lab python3 lab/lighter/scripts/time_semantics_probe.py --symbol EURUSD --minutes 180
  docker compose run --rm lighter-lab python3 lab/lighter/scripts/time_semantics_probe.py --symbol XAU --minutes 180 --now 1771194000
"""
import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "lab" / "lighter" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:
    pass

SYMBOL_NORMALIZE = {"XAU": "XAUUSD", "EURUSD": "EURUSD", "ETH": "ETH"}
RESOLUTION = "1m"
RETRY_DELAY = 1.0
MAX_RETRIES = 3
TZ_NY = ZoneInfo("America/New_York")


def _normalize_symbol(s: str) -> str:
    return SYMBOL_NORMALIZE.get(s.upper(), s.upper())


def _load_market_id_map() -> dict[str, int]:
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


async def _autodetect_market_ids(base_url: str) -> dict[str, int]:
    import lighter
    cfg = lighter.Configuration(host=base_url)
    client = lighter.ApiClient(cfg)
    try:
        orders_api = lighter.OrderApi(client)
        resp = await orders_api.order_books()
        await client.close()
    except Exception as e:
        await client.close()
        raise RuntimeError(f"Autodetect order_books failed: {e}") from e

    result = {}
    for ob in getattr(resp, "order_books", []) or []:
        mid = getattr(ob, "market_id", None)
        sym = getattr(ob, "symbol", None)
        if mid is not None and sym:
            s = str(sym).upper().replace("-USDC", "").replace("-", "").replace("/", "")
            result[s] = mid
            if "XAU" in s:
                result["XAU"] = mid
                result["XAUUSD"] = mid
            elif "EUR" in s:
                result["EURUSD"] = mid
            elif "ETH" in s:
                result["ETH"] = mid
    return result


def _ts_raw_from_candle(c) -> int:
    """Extract raw t (ms or s) from candle."""
    def _get(*keys):
        for k in keys:
            if isinstance(c, dict):
                v = c.get(k)
            else:
                v = getattr(c, k, None)
            if v is not None:
                return v
        return None
    t_raw = int(_get("t", "T") or 0)
    return t_raw // 1000 if t_raw > 1e12 else t_raw


async def _fetch_candles(
    base_url: str,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
) -> list:
    """Fetch raw candles (list of objects/dicts)."""
    import lighter
    try:
        import httpx
        use_httpx = True
    except ImportError:
        use_httpx = False

    url = f"{base_url.rstrip('/')}/api/v1/candles"
    params = {
        "market_id": market_id,
        "resolution": RESOLUTION,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "count_back": count_back,
    }

    for attempt in range(MAX_RETRIES):
        try:
            if use_httpx:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(url, params=params, headers={"Accept-Encoding": "identity"})
                    r.raise_for_status()
                    data = r.json()
                return data.get("c", []) or []
            cfg = lighter.Configuration(host=base_url)
            client = lighter.ApiClient(cfg)
            api = lighter.CandlestickApi(client)
            obj = await api.candles(
                market_id=market_id,
                resolution=RESOLUTION,
                start_timestamp=start_ts,
                end_timestamp=end_ts,
                count_back=count_back,
            )
            await client.close()
            return getattr(obj, "c", []) or []
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                await asyncio.sleep(RETRY_DELAY * (attempt + 2))
            elif "br" in str(e).lower() and use_httpx:
                pass
            else:
                raise
    return []


def _now_floor_minute_utc(now_ts: int | None) -> int:
    """Floor current time to start-of-minute UTC."""
    if now_ts is not None:
        return (now_ts // 60) * 60
    return (int(datetime.now(timezone.utc).timestamp()) // 60) * 60


def main() -> int:
    parser = argparse.ArgumentParser(description="Lighter candle time semantics probe")
    parser.add_argument("--symbol", required=True, help="EURUSD, XAU, or ETH")
    parser.add_argument("--minutes", type=int, default=180, help="Minutes to fetch (default 180)")
    parser.add_argument("--now", type=int, default=None, help="Override 'now' as epoch (for reproducibility)")
    parser.add_argument("--out-dir", default=None, help="Override output dir (default: lab/out)")
    args = parser.parse_args()

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    symbol_canonical = _normalize_symbol(args.symbol)
    market_id_map = _load_market_id_map()
    if not market_id_map or symbol_canonical.upper() not in {k.upper() for k in market_id_map}:
        market_id_map = asyncio.run(_autodetect_market_ids(base_url))

    market_id = market_id_map.get(args.symbol.upper()) or market_id_map.get(symbol_canonical)
    if market_id is None:
        print(f"Error: market_id not found for {args.symbol}")
        return 1

    now_floor_utc = _now_floor_minute_utc(args.now)
    end_ts = now_floor_utc
    start_ts = end_ts - (args.minutes * 60)
    start_ts = (start_ts // 60) * 60

    print("=" * 70)
    print("P0.3b — Lighter Candle Time Semantics Probe")
    print("=" * 70)
    print(f"  Symbol: {args.symbol} (canonical: {symbol_canonical})")
    print(f"  Minutes: {args.minutes}")
    print(f"  Range: {start_ts} .. {end_ts}")
    print(f"  now_floor_utc_ts: {now_floor_utc}")
    print()

    raw_candles = asyncio.run(_fetch_candles(base_url, market_id, start_ts, end_ts, min(args.minutes + 10, 500)))
    if not raw_candles:
        print("  Error: no candles returned")
        return 1

    ts_list: list[int] = []
    non_start_of_minute: list[int] = []
    for c in raw_candles:
        ts_s = _ts_raw_from_candle(c)
        ts_list.append(ts_s)
        if ts_s % 60 != 0:
            non_start_of_minute.append(ts_s)

    ts_list.sort()
    is_start_of_minute = len(non_start_of_minute) == 0

    step_ok = True
    for i in range(1, len(ts_list)):
        if ts_list[i] - ts_list[i - 1] != 60:
            step_ok = False
            break

    latest_ts = ts_list[-1] if ts_list else None
    latest_lag_seconds = (now_floor_utc - latest_ts) if latest_ts is not None else None

    # Heurística: si latest_ts == now_floor_utc_ts → inclou candle parcial (minut en curs)
    includes_partial = (latest_ts == now_floor_utc) if latest_ts is not None else False

    # 10 timestamps aleatoris
    sample_size = min(10, len(ts_list))
    sample_ts = random.sample(ts_list, sample_size) if len(ts_list) >= sample_size else ts_list
    sample_ts.sort()

    print("  Sample timestamps (ts_utc_iso | ts_ny_iso):")
    for ts in sample_ts:
        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
        dt_ny = dt_utc.astimezone(TZ_NY)
        print(f"    {ts}  {dt_utc.isoformat()}  |  {dt_ny.isoformat()}")

    print()
    print("  Boundary probe:")
    print(f"    latest_ts: {latest_ts}")
    print(f"    now_floor_utc_ts: {now_floor_utc}")
    print(f"    latest_lag_seconds: {latest_lag_seconds}")
    print(f"    includes_partial (latest==now_floor): {includes_partial}")
    print()
    print("  Checks:")
    print(f"    is_start_of_minute (ts % 60 == 0): {is_start_of_minute}")
    if non_start_of_minute:
        print(f"    Non-start samples: {non_start_of_minute[:5]}...")
    print(f"    step_ok (increments of 60): {step_ok}")

    # Notes / conclusió
    if is_start_of_minute and step_ok:
        if includes_partial:
            notes = "t és UTC start-of-minute. L'API pot retornar candle parcial (latest==now_floor). Conversió: NO cal; ts ja és start-of-minute. TZ NY només per display/particions."
        else:
            notes = "t és UTC start-of-minute. Retorna només tancades (latest = now_floor - 60). NO hi ha conversió de TZ al dataset; ts epoch UTC."
    elif not is_start_of_minute:
        notes = "t NO és start-of-minute (ts % 60 != 0). Cal definir conversió canònica: floor(ts/60)*60 o similar."
    else:
        notes = "Increments != 60. Revisar semantics."

    result = {
        "symbol": symbol_canonical,
        "is_start_of_minute": is_start_of_minute,
        "step_ok": step_ok,
        "latest_ts": latest_ts,
        "now_floor_utc_ts": now_floor_utc,
        "latest_lag_seconds": latest_lag_seconds,
        "includes_partial": includes_partial,
        "notes": notes,
        "candles_count": len(ts_list),
        "non_start_of_minute_count": len(non_start_of_minute),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    out_path = out_dir / f"time_semantics_{symbol_canonical}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print()
    print(f"  Saved: {out_path}")
    print(f"  Notes: {notes}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
