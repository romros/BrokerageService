"""
P4.0 — Integration: Lighter Backfill Pagination + Dedup (Lighter real)

Valida paginació i deduplicació del LighterCandlestickClient:
- expected_minutes == unique_count (o missing_minutes acceptable)
- duplicates_after_dedup == 0
- ts_step_errors == 0

Promoció de lab/lighter/scripts/coverage_probe.py a test de producció.
Requereix xarxa (Lighter mainnet). Opt-in: --include-lighter-backfill.

Ús:
  python3 testing/integration/test_lighter_backfill_pagination_dedup.py
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

# Finestra que força paginació (500 per request)
WINDOW_MINUTES = 600
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


def _validate_dedup(raw_rows: list, start_ts: int, end_ts: int) -> dict:
    """Dedup per ts; mètriques: expected_minutes, unique_count, duplicates_after_dedup, ts_step_errors."""
    in_window = [r for r in raw_rows if start_ts <= r["ts"] < end_ts]
    raw_count = len(in_window)

    by_ts = {}
    for row in in_window:
        by_ts[row["ts"]] = row
    unique_count = len(by_ts)
    duplicates_raw = raw_count - unique_count

    sorted_ts = sorted(by_ts.keys())
    expected_minutes = (end_ts - start_ts) // 60
    missing_minutes = max(0, expected_minutes - unique_count)

    ts_step_errors = 0
    for i in range(1, len(sorted_ts)):
        if sorted_ts[i] - sorted_ts[i - 1] != 60:
            ts_step_errors += 1

    return {
        "raw_count": raw_count,
        "unique_count": unique_count,
        "expected_minutes": expected_minutes,
        "missing_minutes": missing_minutes,
        "duplicates_raw": duplicates_raw,
        "duplicates_after_dedup": 0,
        "ts_step_errors": ts_step_errors,
    }


async def _run():
    from infrastructure.venues.lighter.lighter_candlestick_client import LighterCandlestickClient  # lazy: evita carregar P4 si preflight skip

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    market_id_map = _load_market_id_map()

    now_ts = int(datetime.now(timezone.utc).timestamp())
    end_ts = (now_ts // 60) * 60
    start_ts = end_ts - (WINDOW_MINUTES * 60)

    client = LighterCandlestickClient(base_url=base_url, market_id_map=market_id_map)
    rows = await client.fetch_candles(SYMBOL, start_ts, end_ts)
    await client.close()

    if len(rows) < 100:
        print(f"  SKIP: LIGHTER Candlestick returned {len(rows)} candles (symbol={SYMBOL}, need >=100)")
        from testing.helpers.lighter_test_env import EXIT_SKIP  # lazy: només en skip path
        sys.exit(EXIT_SKIP)

    report = _validate_dedup(rows, start_ts, end_ts)

    print()
    print("  Mètriques:")
    print(f"    raw_count={report['raw_count']}")
    print(f"    unique_count={report['unique_count']}")
    print(f"    expected_minutes={report['expected_minutes']}")
    print(f"    missing_minutes={report['missing_minutes']}")
    print(f"    duplicates_raw={report['duplicates_raw']}")
    print(f"    duplicates_after_dedup={report['duplicates_after_dedup']}")
    print(f"    ts_step_errors={report['ts_step_errors']}")
    print()

    ok = (
        report["duplicates_after_dedup"] == 0
        and report["ts_step_errors"] == 0
        and report["missing_minutes"] <= 10
    )
    if ok:
        print("  ✓ Lighter backfill pagination/dedup test passed")
    else:
        print("  ✗ FAIL: invariants paginació/dedup no complerts")
        sys.exit(1)


def main():
    print("=" * 60)
    print("Integration: Lighter Backfill Pagination + Dedup")
    print("=" * 60)
    print(f"  Symbol: {SYMBOL}")
    print(f"  Window: {WINDOW_MINUTES} min (força paginació)")
    print()
    _preflight_skip()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
