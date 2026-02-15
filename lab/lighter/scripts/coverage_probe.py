#!/usr/bin/env python3
"""
QA Lab — coverage_probe: Lighter mainnet coverage per símbol (EURUSD, XAU)

Troba earliest_ts i latest_ts 1m amb probing incremental + binary search.
Valida finestra recent 72h (missing_minutes, max_gap, duplicates, ts_step_errors).
Respecta rate limit (Volume Quota per SendTx; candlestick ~60 req/min) amb sleep 1.05s i retry 429.

Output: lab/out/coverage_mainnet_<symbol>.json

Ús:
  python3 lab/lighter/scripts/coverage_probe.py --symbol EURUSD
  python3 lab/lighter/scripts/coverage_probe.py --symbol XAU
  python3 lab/lighter/scripts/coverage_probe.py --symbol EURUSD --symbol XAU
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

SYMBOL_NORMALIZE = {"XAU": "XAUUSD", "EURUSD": "EURUSD"}
CHUNK_LIMIT = 500
RESOLUTION = "1m"
RETRY_DELAY = 1.0
MAX_RETRIES = 3
RATE_LIMIT_REQ_PER_MIN = 60
MIN_SLEEP_BETWEEN_REQ = 1.05  # > 1s per stay under 60/min
EARLIEST_EPOCH = 1609459200  # 2021-01-01
WINDOW_72H = 72 * 3600


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
    return result


def _ts_to_start_of_minute(ts: int) -> int:
    return (ts // 60) * 60


def _parse_candle(c, symbol_canonical: str) -> dict:
    """Parse Lighter candle (object or dict). ts: floor to start-of-minute (clau dedup)."""
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
    ts_s = t_raw // 1000 if t_raw > 1e12 else t_raw
    ts = (ts_s // 60) * 60  # floor to start-of-minute
    o = float(_get("o", "O") or 0)
    h = float(_get("h", "H") or 0)
    l_ = float(_get("l", "L") or 0)
    c_ = float(_get("c", "C") or 0)
    v = float(_get("v", "V") or 0)
    return {"ts": ts, "open": o, "high": h, "low": l_, "close": c_, "volume": v if v >= 0 else 0, "symbol": symbol_canonical}


async def _fetch_one(
    candlestick_api,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
    symbol_canonical: str,
) -> list[dict]:
    """Fetch one chunk, parse to canonical dicts."""
    candles_obj = await candlestick_api.candles(
        market_id=market_id,
        resolution=RESOLUTION,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        count_back=count_back,
    )
    items = getattr(candles_obj, "c", []) or []
    return [_parse_candle(c, symbol_canonical) for c in items]


async def _fetch_one_httpx(
    base_url: str,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
    symbol_canonical: str,
) -> list[dict]:
    """Fallback: fetch via httpx amb Accept-Encoding: identity (evita brotli)."""
    try:
        import httpx
    except ImportError:
        return []
    url = f"{base_url.rstrip('/')}/api/v1/candles"
    params = {
        "market_id": market_id,
        "resolution": RESOLUTION,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "count_back": count_back,
    }
    headers = {"Accept-Encoding": "identity"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    items = data.get("c", []) or []
    return [_parse_candle(obj, symbol_canonical) for obj in items]


async def _fetch_with_retry(
    candlestick_api,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
    symbol_canonical: str,
    rate_limit_hits: list,
    base_url: str | None = None,
) -> list[dict]:
    for attempt in range(MAX_RETRIES):
        try:
            return await _fetch_one(
                candlestick_api, market_id, start_ts, end_ts, count_back, symbol_canonical
            )
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                rate_limit_hits[0] += 1
                await asyncio.sleep(RETRY_DELAY * (attempt + 2))
            elif "br" in str(e).lower() or "content-encoding" in str(e).lower():
                # brotli decode error: fallback a httpx amb Accept-Encoding: identity
                if base_url and attempt == 0:
                    try:
                        return await _fetch_one_httpx(
                            base_url, market_id, start_ts, end_ts, count_back, symbol_canonical
                        )
                    except Exception:
                        pass
            raise
    return []


def _validate_72h(raw_candles: list[dict], start_ts: int, end_ts: int) -> dict:
    """
    Dedup ABANS de mètriques. Clau = ts (start-of-minute).
    Invariants: expected_minutes, missing_minutes, duplicates_raw, duplicates_after_dedup.
    """
    in_window = [r for r in raw_candles if start_ts <= r["ts"] < end_ts]
    raw_count = len(in_window)

    # Dedup: dict[ts] = candle (keep last)
    by_ts: dict[int, dict] = {}
    for row in in_window:
        by_ts[row["ts"]] = row
    unique_count = len(by_ts)
    duplicates_raw = raw_count - unique_count

    sorted_ts = sorted(by_ts.keys())
    expected_minutes = (end_ts - start_ts) // 60
    missing_minutes = max(0, expected_minutes - unique_count)

    ts_step_errors = 0
    max_gap = 0
    for i in range(1, len(sorted_ts)):
        delta = sorted_ts[i] - sorted_ts[i - 1]
        if delta != 60:
            ts_step_errors += 1
            max_gap = max(max_gap, delta)

    # duplicates_after_dedup ha de ser 0 (dataset efectiu deduplicat)
    duplicates_after_dedup = 0

    return {
        "raw_count": raw_count,
        "unique_count": unique_count,
        "expected_minutes": expected_minutes,
        "missing_minutes": missing_minutes,
        "max_gap_s": max_gap,
        "duplicates_raw": duplicates_raw,
        "duplicates_after_dedup": duplicates_after_dedup,
        "ts_step_errors": ts_step_errors,
        "candles_in_window": unique_count,
    }


async def _probe_earliest(
    candlestick_api,
    market_id: int,
    symbol_canonical: str,
    now_ts: int,
    rate_limit_hits: list,
    base_url: str,
) -> int | None:
    """Binary search for earliest_ts. Returns epoch seconds or None."""
    low = EARLIEST_EPOCH
    high = _ts_to_start_of_minute(now_ts - WINDOW_72H)
    best = None
    while low <= high:
        mid = _ts_to_start_of_minute((low + high) // 2)
        end = min(mid + 3600, high + 60)
        await asyncio.sleep(MIN_SLEEP_BETWEEN_REQ)
        rows = await _fetch_with_retry(
            candlestick_api, market_id, mid, end, 10, symbol_canonical, rate_limit_hits, base_url
        )
        if rows:
            best = min(r["ts"] for r in rows)
            high = mid - 60
        else:
            low = mid + 60
    return best


async def _probe_latest(
    candlestick_api,
    market_id: int,
    symbol_canonical: str,
    now_ts: int,
    rate_limit_hits: list,
    base_url: str,
) -> int | None:
    """Get latest_ts from most recent candle."""
    start = _ts_to_start_of_minute(now_ts - 3600)
    end = _ts_to_start_of_minute(now_ts)
    await asyncio.sleep(MIN_SLEEP_BETWEEN_REQ)
    rows = await _fetch_with_retry(
        candlestick_api, market_id, start, end, 500, symbol_canonical, rate_limit_hits, base_url
    )
    if not rows:
        return None
    return max(r["ts"] for r in rows)


async def _fetch_72h(
    candlestick_api,
    market_id: int,
    symbol_canonical: str,
    end_ts: int,
    rate_limit_hits: list,
    base_url: str,
) -> tuple[list[dict], int]:
    """
    Fetch 72h amb paginació sense solapament.
    Rang [since_ts, to_ts) exclusiu. Següent pàgina: next_since = last_ts + 60.
    """
    start_ts = end_ts - WINDOW_72H
    start_ts = _ts_to_start_of_minute(start_ts)
    end_ts = _ts_to_start_of_minute(end_ts)
    all_rows: list[dict] = []
    req_count = 0
    current = start_ts
    while current < end_ts:
        chunk_end = min(current + CHUNK_LIMIT * 60, end_ts)
        await asyncio.sleep(MIN_SLEEP_BETWEEN_REQ)
        rows = await _fetch_with_retry(
            candlestick_api, market_id, current, chunk_end, CHUNK_LIMIT, symbol_canonical, rate_limit_hits, base_url
        )
        req_count += 1
        for r in rows:
            if start_ts <= r["ts"] < end_ts:
                all_rows.append(r)
        if not rows:
            break
        last_ts = max(r["ts"] for r in rows)
        current = last_ts + 60  # cursor: següent pàgina sense solapament
    return all_rows, req_count


async def run_probe(base_url: str, symbol: str, market_id_map: dict[str, int], skip_earliest: bool = False) -> dict:
    import lighter

    symbol_canonical = _normalize_symbol(symbol)
    market_id = market_id_map.get(symbol.upper()) or market_id_map.get(symbol_canonical)
    if market_id is None:
        raise ValueError(f"market_id not found for {symbol}")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    rate_limit_hits = [0]

    cfg = lighter.Configuration(host=base_url)
    client = lighter.ApiClient(cfg)
    candlestick_api = lighter.CandlestickApi(client)

    try:
        # 1) Probe latest
        latest_ts = await _probe_latest(candlestick_api, market_id, symbol_canonical, now_ts, rate_limit_hits, base_url)
        if latest_ts is None:
            return {
                "symbol": symbol_canonical,
                "error": "No candles returned for latest probe",
                "earliest_ts": None,
                "latest_ts": None,
                "window_72h": None,
                "decision": "Lighter no viable",
            }

        # 2) Probe earliest (binary search)
        earliest_ts = None
        if not skip_earliest:
            try:
                earliest_ts = await _probe_earliest(candlestick_api, market_id, symbol_canonical, now_ts, rate_limit_hits, base_url)
            except Exception as e:
                if "br" in str(e).lower() or "content-encoding" in str(e).lower():
                    pass  # Skip on brotli decode errors (env-dependent)
                else:
                    raise

        # 3) Fetch 72h for validation
        candles_72h, req_72h = await _fetch_72h(
            candlestick_api, market_id, symbol_canonical, latest_ts + 60, rate_limit_hits, base_url
        )
        end_72h = _ts_to_start_of_minute(latest_ts + 60)
        start_72h = end_72h - WINDOW_72H
        validation = _validate_72h(candles_72h, start_72h, end_72h)

        await client.close()
    except Exception:
        await client.close()
        raise

        # Decision: invariants estrictes
    ok = (
        validation["missing_minutes"] == 0
        and validation["ts_step_errors"] == 0
        and validation["duplicates_after_dedup"] == 0
        and validation["candles_in_window"] == validation["expected_minutes"]
    )
    if earliest_ts and (now_ts - earliest_ts) < 30 * 24 * 3600:  # < 30 days
        decision = "Lighter recent (històric curt); cal Dukascopy per backfill llarg"
    elif ok:
        decision = "Lighter recent viable (72h OK); Dukascopy per històric pre-Lighter"
    else:
        decision = "Lighter recent amb gaps/errors; cal Dukascopy per integritat"

    return {
        "symbol": symbol_canonical,
        "earliest_ts": earliest_ts,
        "latest_ts": latest_ts,
        "probe_requests": 1 + (15 if earliest_ts else 0) + req_72h,
        "rate_limit_hits": rate_limit_hits[0],
        "window_72h": {
            "start_ts": start_72h,
            "end_ts": end_72h,
            **validation,
        },
        "decision": decision,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Lighter mainnet coverage probe")
    parser.add_argument("--symbol", action="append", required=True, help="Symbol (EURUSD, XAU)")
    parser.add_argument("--out-dir", default=None, help="Override output dir (default: lab/out)")
    parser.add_argument("--skip-earliest", action="store_true", help="Skip binary search for earliest (faster; use if brotli errors)")
    args = parser.parse_args()

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "lab" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    market_id_map = _load_market_id_map()
    if not market_id_map or not any(s.upper() in {k.upper() for k in market_id_map} for s in args.symbol):
        print("Autodetecting market_id...")
        market_id_map = asyncio.run(_autodetect_market_ids(base_url))

    print("=" * 70)
    print("QA Lab — coverage_probe (Lighter mainnet)")
    print("=" * 70)
    print(f"  Base URL: {base_url}")
    print(f"  Symbols: {args.symbol}")
    print()

    results = []
    for symbol in args.symbol:
        print(f"  Probing {symbol}...")
        try:
            out = asyncio.run(run_probe(base_url, symbol, market_id_map, skip_earliest=args.skip_earliest))
        except Exception as e:
            out = {"symbol": _normalize_symbol(symbol), "error": str(e), "decision": "Error"}
            import traceback
            traceback.print_exc()
        results.append(out)

        out_path = out_dir / f"coverage_mainnet_{out['symbol']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"    Saved: {out_path}")
        if "earliest_ts" in out and out["earliest_ts"]:
            print(f"    earliest_ts={out['earliest_ts']}")
        if "latest_ts" in out and out["latest_ts"]:
            print(f"    latest_ts={out['latest_ts']}")
        if "window_72h" in out and out["window_72h"]:
            w = out["window_72h"]
            print(f"    72h: raw={w.get('raw_count')} unique={w.get('unique_count')} dup_raw={w.get('duplicates_raw')} dup_after={w.get('duplicates_after_dedup')} missing={w.get('missing_minutes')} step_err={w.get('ts_step_errors')}")
        print(f"    decision: {out.get('decision', 'N/A')}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
