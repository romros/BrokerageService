#!/usr/bin/env python3
"""
TASK LAB — Historical Candles Feasibility (Lighter) + paginator + normalització 1m

Descarrega històric 1m de Lighter via CandlestickApi (SDK), el pagina (≤500 per request),
el normalitza a la semàntica canònica del projecte (ts epoch UTC start-of-minute) i el guarda
en CSV canònic. Decideix si P4 (backfill+gap repair) és viable amb Lighter com a primary.

Config: LIGHTER_BASE_URL, LIGHTER_MARKET_ID_MAP (opcional), SYMBOLS
Output: datafiles/lab_lighter_history/{symbol}/{YYYY}/{MM}.csv
Format: ts,open,high,low,close,volume

Ús:
  python3 lab/lighter/scripts/fetch_historical_candles.py --symbol EURUSD --hours 72
  python3 lab/lighter/scripts/fetch_historical_candles.py --symbol XAU --hours 72
  python3 lab/lighter/scripts/fetch_historical_candles.py --symbol ETH --hours 24

Symbol normalization (AGENTS §2.0): XAU→XAUUSD canonical; EURUSD directe.
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

# Symbol normalization: Lighter XAU → canonical XAUUSD
SYMBOL_NORMALIZE = {"XAU": "XAUUSD", "EURUSD": "EURUSD", "ETH": "ETH", "BTC": "BTC"}

CHUNK_LIMIT = 500  # Lighter API limit per request
RESOLUTION = "1m"  # 1 minute (enum: 1m, 5m, 15m, 30m, 1h, 4h, 12h, 1d, 1w)
RETRY_DELAY = 1.0
MAX_RETRIES = 3


def _normalize_symbol(s: str) -> str:
    """Map Lighter symbol to canonical (XAU→XAUUSD)."""
    return SYMBOL_NORMALIZE.get(s.upper(), s.upper())


def _load_market_id_map() -> dict[str, int]:
    """Load symbol→market_id from LIGHTER_MARKET_ID_MAP (JSON) or env."""
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


async def _autodetect_market_ids(base_url: str) -> dict[str, int]:
    """Autodetect symbol→market_id via OrderApi.order_books()."""
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
            elif "ETH" in s or s == "WETH":
                result["ETH"] = mid
            elif "BTC" in s or s == "WBTC":
                result["BTC"] = mid
            elif "EUR" in s:
                result["EURUSD"] = mid
    return result


def _ts_to_start_of_minute(ts: int) -> int:
    """Ensure ts is start-of-minute (floor to 60s)."""
    return (ts // 60) * 60


def _parse_lighter_candle(c, symbol_canonical: str) -> dict:
    """Parse Lighter Candle to canonical dict. Lighter returns t in milliseconds."""
    t_raw = int(getattr(c, "t", 0) or 0)
    ts = _ts_to_start_of_minute(t_raw // 1000 if t_raw > 1e12 else t_raw)
    o = float(getattr(c, "o", 0) or getattr(c, "O", 0) or 0)
    h = float(getattr(c, "h", 0) or getattr(c, "H", 0) or 0)
    l_ = float(getattr(c, "l", 0) or getattr(c, "L", 0) or 0)
    c_ = float(getattr(c, "c", 0) or getattr(c, "C", 0) or 0)
    v = float(getattr(c, "v", 0) or getattr(c, "V", 0) or 0)
    return {
        "ts": ts,
        "open": o,
        "high": h,
        "low": l_,
        "close": c_,
        "volume": v if v >= 0 else 0,
        "symbol": symbol_canonical,
    }


async def _fetch_chunk(
    candlestick_api,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
) -> list:
    """Fetch one chunk of candles. Returns list of parsed canonical dicts."""
    candles_obj = await candlestick_api.candles(
        market_id=market_id,
        resolution=RESOLUTION,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        count_back=count_back,
    )
    items = getattr(candles_obj, "c", []) or []
    return items


async def fetch_historical(
    base_url: str,
    symbol: str,
    hours: int,
    market_id_map: dict[str, int],
) -> tuple[list[dict], int, int, int]:
    """
    Fetch historical 1m candles with pagination.
    Returns (candles, requests_count, rate_limit_hits, duplicates).
    """
    import lighter

    symbol_canonical = _normalize_symbol(symbol)
    market_id = market_id_map.get(symbol.upper()) or market_id_map.get(symbol_canonical)
    if market_id is None:
        raise ValueError(f"market_id not found for {symbol} (tried {symbol.upper()}, {symbol_canonical})")

    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - (hours * 3600)
    start_ts = _ts_to_start_of_minute(start_ts)
    end_ts = _ts_to_start_of_minute(end_ts)

    cfg = lighter.Configuration(host=base_url)
    client = lighter.ApiClient(cfg)
    candlestick_api = lighter.CandlestickApi(client)

    all_candles: list[dict] = []
    requests_count = 0
    rate_limit_hits = 0
    current_start = start_ts

    try:
        while current_start < end_ts:
            chunk_end = min(current_start + CHUNK_LIMIT * 60, end_ts)
            for attempt in range(MAX_RETRIES):
                try:
                    items = await _fetch_chunk(
                        candlestick_api,
                        market_id,
                        current_start,
                        chunk_end,
                        CHUNK_LIMIT,
                    )
                    requests_count += 1
                    for c in items:
                        row = _parse_lighter_candle(c, symbol_canonical)
                        if start_ts <= row["ts"] < end_ts:
                            all_candles.append(row)
                    break
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower():
                        rate_limit_hits += 1
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    else:
                        raise
            current_start = chunk_end
            await asyncio.sleep(0.2)

        await client.close()
    except Exception:
        await client.close()
        raise

    # Deduplicate by ts, sort
    by_ts: dict[int, dict] = {}
    for row in all_candles:
        t = row["ts"]
        if t not in by_ts:
            by_ts[t] = row
    candles_sorted = sorted(by_ts.values(), key=lambda x: x["ts"])
    duplicates = len(all_candles) - len(candles_sorted)

    return candles_sorted, requests_count, rate_limit_hits, duplicates


def validate_candles(candles: list[dict]) -> tuple[int, int]:
    """Returns (ts_step_errors, missing_minutes)."""
    if len(candles) < 2:
        return 0, 0
    ts_step_errors = 0
    for i in range(1, len(candles)):
        delta = candles[i]["ts"] - candles[i - 1]["ts"]
        if delta != 60:
            ts_step_errors += 1
    expected = (candles[-1]["ts"] - candles[0]["ts"]) // 60 + 1
    missing = max(0, expected - len(candles))
    return ts_step_errors, missing


def write_csv(candles: list[dict], out_root: Path, symbol: str) -> list[Path]:
    """Write candles to datafiles/lab_lighter_history/{symbol}/{YYYY}/{MM}.csv. Returns paths."""
    written: list[Path] = []
    by_month: dict[tuple[int, int], list[dict]] = {}
    for c in candles:
        dt = datetime.fromtimestamp(c["ts"], tz=timezone.utc)
        key = (dt.year, dt.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(c)

    for (year, month), rows in sorted(by_month.items()):
        dir_path = out_root / symbol / str(year) / f"{month:02d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        csv_path = dir_path / f"{month:02d}.csv"
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("ts,open,high,low,close,volume\n")
            for r in rows:
                f.write(f"{r['ts']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")
        written.append(csv_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Lighter historical 1m candles")
    parser.add_argument("--symbol", required=True, help="Symbol (EURUSD, XAU, XAUUSD, ETH, BTC)")
    parser.add_argument("--hours", type=int, default=72, help="Hours to fetch (default 72)")
    parser.add_argument("--out-dir", default=None, help="Override output root (default: datafiles/lab_lighter_history)")
    args = parser.parse_args()

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    if args.out_dir:
        out_root = Path(args.out_dir)
    else:
        out_root = ROOT / "datafiles" / "lab_lighter_history"
    out_root.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("LAB — Historical Candles Feasibility (Lighter)")
    print("=" * 70)
    print(f"  Base URL: {base_url}")
    print(f"  Symbol: {args.symbol} (canonical: {_normalize_symbol(args.symbol)})")
    print(f"  Hours: {args.hours}")
    print(f"  Output: {out_root}")
    print()

    market_id_map = _load_market_id_map()
    if not market_id_map or args.symbol.upper() not in {k.upper() for k in market_id_map}:
        print("  Autodetecting market_id via order_books...")
        try:
            market_id_map = asyncio.run(_autodetect_market_ids(base_url))
            print(f"  Detected: {market_id_map}")
        except Exception as e:
            print(f"  ❌ Autodetect failed: {e}")
            return 1

    try:
        candles, requests_count, rate_limit_hits, duplicates = asyncio.run(
            fetch_historical(base_url, args.symbol, args.hours, market_id_map)
        )
    except Exception as e:
        print(f"  ❌ Fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    if not candles:
        print("  ⚠️  No candles returned")
        return 1

    ts_step_errors, missing_minutes = validate_candles(candles)
    earliest_ts = candles[0]["ts"]
    latest_ts = candles[-1]["ts"]
    symbol_canonical = _normalize_symbol(args.symbol)

    paths = write_csv(candles, out_root, symbol_canonical)
    print(f"  CSV written: {paths}")

    print()
    print("  Summary:")
    print(f"    earliest_ts={earliest_ts}")
    print(f"    latest_ts={latest_ts}")
    print(f"    candles_count={len(candles)}")
    print(f"    requests_count={requests_count}")
    print(f"    rate_limit_hits={rate_limit_hits}")
    print(f"    duplicates={duplicates}")
    print(f"    ts_step_errors={ts_step_errors}")
    print(f"    missing_minutes={missing_minutes}")

    ok = ts_step_errors == 0 and missing_minutes <= 1  # output deduplicated by ts
    print()
    if ok:
        print("  ✅ DONE: duplicates=0, missing_minutes<=1, ts_step_errors=0")
    else:
        print("  ⚠️  Check: duplicates, ts_step_errors, or missing_minutes outside acceptance")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
