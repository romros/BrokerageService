"""
P4.0 — Integration: Gap Repair Flow (Lighter real)

Crea CSV temporal amb candles de Lighter, elimina 5 minuts, executa repair,
valida invariants: missing_minutes==0, duplicates_after_dedup==0, ts_step_errors==0.

Requereix xarxa (Lighter mainnet). Opt-in a run_all: --include-lighter-backfill.

Ús:
  python3 testing/integration/test_gap_repair_flow.py
  ./test.sh testing/run_all.py --include-lighter-backfill
"""

import asyncio
import json
import os
import sys
import tempfile
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

GAP_SIZE = 5
WINDOW_MINUTES = 90
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
    from application.services.backfill_service import BackfillService  # lazy: evita carregar P4 si preflight skip
    from domain.models import Candle
    from infrastructure.storage.csv_store import CSVCandleStore
    from infrastructure.storage.gap_validator import GapValidator
    from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import (
        LighterCandlestickBackfillProvider,
    )
    from infrastructure.venues.lighter.lighter_candlestick_client import (
        LighterCandlestickClient,
    )

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    market_id_map = _load_market_id_map()

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CSVCandleStore(
            root_path=tmpdir,
            broker="lighter",
            canonical_tz="America/New_York",
        )

        # 1. Fetch candles from Lighter
        now_ts = int(datetime.now(timezone.utc).timestamp())
        end_ts = (now_ts // 60) * 60
        start_ts = end_ts - (WINDOW_MINUTES * 60)

        client = LighterCandlestickClient(base_url=base_url, market_id_map=market_id_map)
        rows = await client.fetch_candles(SYMBOL, start_ts, end_ts)
        await client.close()

        if len(rows) < GAP_SIZE + 10:
            print(f"  SKIP: LIGHTER Candlestick returned {len(rows)} candles (symbol={SYMBOL}, need >=15)")
            from testing.helpers.lighter_test_env import EXIT_SKIP  # lazy: només en skip path
            sys.exit(EXIT_SKIP)

        # 2. Crear gap: escriure primera part, saltar GAP_SIZE minuts, escriure última part
        mid = len(rows) // 2
        gap_start_idx = mid - GAP_SIZE // 2
        gap_end_idx = gap_start_idx + GAP_SIZE

        candles_before = rows[:gap_start_idx]
        candles_after = rows[gap_end_idx:]

        def to_candle(r):
            return Candle(
                symbol=r["symbol"],
                timestamp=datetime.fromtimestamp(r["ts"], tz=timezone.utc),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                is_closed=True,
            )

        patch1 = [to_candle(r) for r in candles_before]
        patch2 = [to_candle(r) for r in candles_after]
        if patch1:
            store.patch(patch1)
        if patch2:
            store.patch(patch2)

        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

        # Verificar que hi ha gap
        rng = store.read_range(SYMBOL, start_dt, end_dt, validate_gaps=True)
        assert not rng.is_complete, "Hauria d'haver gap"
        gaps_before = GapValidator.find_gaps(rng.candles, start_dt, end_dt)
        print(f"  Gap creat: {len(gaps_before)} gaps, {rng.missing_count} missing")

        # 3. Executar repair
        provider = LighterCandlestickBackfillProvider(base_url=base_url, market_id_map=market_id_map)
        backfill = BackfillService(
            store=store,
            provider=provider,
            symbols=[SYMBOL],
            corrective_window_minutes=WINDOW_MINUTES,
            interval_seconds=99999,
        )
        filled = await backfill.backfill_symbol(SYMBOL, start=start_dt, end=end_dt)
        await provider._client.close()

        # 4. Validar invariants
        rng_after = store.read_range(SYMBOL, start_dt, end_dt, validate_gaps=True)
        report = GapValidator.validate(rng_after.candles, start_dt, end_dt, symbol=SYMBOL)

        missing_minutes = report.missing_count
        duplicates_after_dedup = 1 if report.has_duplicates else 0
        ts_step_errors = 0
        for i in range(1, len(rng_after.candles)):
            delta = (rng_after.candles[i].timestamp - rng_after.candles[i - 1].timestamp).total_seconds()
            if delta != 60:
                ts_step_errors += 1

        print()
        print("  Mètriques:")
        print(f"    filled={filled}")
        print(f"    missing_minutes={missing_minutes}")
        print(f"    duplicates_after_dedup={duplicates_after_dedup}")
        print(f"    ts_step_errors={ts_step_errors}")
        print()

        ok = missing_minutes == 0 and duplicates_after_dedup == 0 and ts_step_errors == 0
        if ok:
            print("  ✓ Gap repair flow test passed")
        else:
            print("  ✗ FAIL: invariants no complerts")
            sys.exit(1)


def main():
    print("=" * 60)
    print("Integration: Gap Repair Flow (Lighter real)")
    print("=" * 60)
    print(f"  Symbol: {SYMBOL}")
    print(f"  Window: {WINDOW_MINUTES} min, gap: {GAP_SIZE} min")
    print()
    _preflight_skip()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
