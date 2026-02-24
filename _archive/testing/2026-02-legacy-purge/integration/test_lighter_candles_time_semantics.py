"""
P4.0 — Integration: Lighter Candles Time Semantics (Lighter real)

Valida el contracte temporal de Lighter Candlestick API:
- ts % 60 == 0 (start-of-minute UTC)
- increments de 60s
- latest candle és tancada (latest_ts <= now_floor - 60)

Promoció de lab/lighter/scripts/time_semantics_probe.py a test de producció.
Requereix xarxa (Lighter mainnet). Opt-in: --include-lighter-backfill.

Ús:
  python3 testing/integration/test_lighter_candles_time_semantics.py
  ./test.sh testing/run_all.py --include-lighter-backfill
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

MINUTES = 120
SYMBOL = "EURUSD"


def _preflight_skip():
    """P4.2: skip si entorn no preparat (no fail amb 0 candles)."""
    from testing.helpers.lighter_test_env import EXIT_SKIP, preflight_lighter_candlestick  # lazy: defer fins a preflight
    ok, reason = asyncio.run(preflight_lighter_candlestick())
    if not ok:
        print(f"  SKIP: {reason}")
        sys.exit(EXIT_SKIP)


def _load_market_id_map():
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"EURUSD": 96, "XAUUSD": 92, "XAU": 92}


async def _run():
    from infrastructure.venues.lighter.lighter_candlestick_client import LighterCandlestickClient  # lazy: evita carregar P4 si preflight skip

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    market_id_map = _load_market_id_map()

    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = (now_ts // 60) * 60
    start_ts = end_ts - (MINUTES * 60)

    client = LighterCandlestickClient(base_url=base_url, market_id_map=market_id_map)
    rows = await client.fetch_candles(SYMBOL, start_ts, end_ts)
    await client.close()

    if len(rows) < 10:
        print(f"  SKIP: LIGHTER Candlestick returned {len(rows)} candles (symbol={SYMBOL}, need >=10)")
        from testing.helpers.lighter_test_env import EXIT_SKIP  # lazy: només en skip path
        sys.exit(EXIT_SKIP)

    ts_list = sorted(r["ts"] for r in rows)
    non_start_of_minute = [ts for ts in ts_list if ts % 60 != 0]
    is_start_of_minute = len(non_start_of_minute) == 0

    step_ok = True
    for i in range(1, len(ts_list)):
        if ts_list[i] - ts_list[i - 1] != 60:
            step_ok = False
            break

    latest_ts = ts_list[-1] if ts_list else None
    now_floor_utc = (now_ts // 60) * 60
    latest_lag_seconds = (now_floor_utc - latest_ts) if latest_ts is not None else None
    latest_closed = latest_lag_seconds >= 60 if latest_lag_seconds is not None else True

    print()
    print("  Mètriques:")
    print(f"    candles_count={len(rows)}")
    print(f"    is_start_of_minute (ts % 60 == 0): {is_start_of_minute}")
    print(f"    step_ok (increments 60s): {step_ok}")
    print(f"    latest_ts={latest_ts}")
    print(f"    now_floor_utc={now_floor_utc}")
    print(f"    latest_lag_seconds={latest_lag_seconds}")
    print(f"    latest_closed (lag >= 60): {latest_closed}")
    print()

    ok = is_start_of_minute and step_ok and latest_closed
    if ok:
        print("  ✓ Lighter candles time semantics test passed")
    else:
        print("  ✗ FAIL: contracte temporal no complert")
        if non_start_of_minute:
            print(f"    non_start_of_minute: {non_start_of_minute[:5]}...")
        sys.exit(1)


def main():
    print("=" * 60)
    print("Integration: Lighter Candles Time Semantics")
    print("=" * 60)
    print(f"  Symbol: {SYMBOL}")
    print(f"  Minutes: {MINUTES}")
    print()
    _preflight_skip()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
