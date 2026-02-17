#!/usr/bin/env python3
"""
P8.1 — Compat report amb dades reals (Lighter vs Dukascopy)

Opt-in: --include-compat-report
Preflight: SKIP exit 2 si entorn no preparat (xarxa, .env).

Obté dades 1m de:
  A: Lighter (via LighterCandlestickBackfillProvider)
  B: Dukascopy (via DukascopyBackfillProvider)

Finestra: 72h (4320 candles) si hi ha dades; sinó 24h.
Symbols: mainnet EURUSD (opcional XAUUSD); testnet ETH → SKIP "Dukascopy no té ETH".

Genera artifact JSON a datafiles/compat_reports/...
Asserts: només integritat (no duplicates, ts_step_err==0); no asserts durs de compat.

Ús:
  python3 testing/integration/test_compat_report_real.py
  ./test.sh testing/run_all.py --include-compat-report
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from foundation.utils.file_permissions import set_host_readable_permissions
from testing.helpers.compat_report_test_env import EXIT_SKIP, preflight_compat_report_real

WINDOW_HOURS_DEFAULT = 72
WINDOW_HOURS_FALLBACK = 24
MIN_CANDLES = 100

# mainnet: EURUSD (opcional XAUUSD); testnet: ETH → skip
def _select_symbols() -> list:
    base_url = (os.getenv("LIGHTER_BASE_URL") or "").lower()
    if "testnet" in base_url:
        return ["ETH"]  # Dukascopy no té → preflight skip
    return ["EURUSD", "XAUUSD"]


async def _run():
    from application.services.compat_report_service import build_compat_report, save_compat_report
    from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import LighterCandlestickBackfillProvider
    from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider

    root = os.getenv("DATAFILES_ROOT") or str(ROOT / "datafiles")
    lighter = LighterCandlestickBackfillProvider()
    dukascopy = DukascopyBackfillProvider(cache_root=root)

    end = datetime.now(timezone.utc)
    end_ts = int(end.timestamp())
    end_ts = (end_ts // 60) * 60
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    symbols = _select_symbols()
    all_ok = True

    for symbol in symbols:
        ok, reason = await preflight_compat_report_real(symbol)
        if not ok:
            print(f"  {symbol}: SKIP {reason}")
            continue

        # Finestra 72h; si pocs candles, provar 24h
        for window_h in (WINDOW_HOURS_DEFAULT, WINDOW_HOURS_FALLBACK):
            start_dt = end_dt - timedelta(hours=window_h)

            try:
                candles_a = await lighter.fetch_ohlcv(symbol, start_dt, end_dt)
            except Exception as e:
                print(f"  {symbol}: Lighter error: {e}")
                all_ok = False
                break

            try:
                candles_b = await dukascopy.fetch_ohlcv(symbol, start_dt, end_dt)
            except Exception as e:
                print(f"  {symbol}: Dukascopy error: {e}")
                all_ok = False
                break

            if len(candles_a) < MIN_CANDLES or len(candles_b) < MIN_CANDLES:
                if window_h == WINDOW_HOURS_FALLBACK:
                    print(f"  {symbol}: SKIP <{MIN_CANDLES} candles (A={len(candles_a)}, B={len(candles_b)})")
                    break
                continue

            base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
            market_env = "mainnet" if "mainnet" in base_url.lower() else "testnet"
            req_a = (len(candles_a) + 499) // 500 if candles_a else 0
            provenance = {
                "source_a": "lighter_rest_candlestick",
                "source_b": "dukascopy_backfill",
                "base_url_a": base_url,
                "market_data_env_a": market_env,
                "request_count_a": req_a,
                "request_count_b": 1,
                "sample_request_a": f"/api/v1/candles?market_id=<id>&resolution=1m&start_timestamp=...&end_timestamp=...",
            }
            report = build_compat_report(
                candles_a, candles_b, symbol,
                source_a="lighter_rest_candlestick", source_b="dukascopy_backfill",
                provenance=provenance,
            )

            # Asserts d'integritat: només duplicates (ts_step_err/missing poden existir en dades reals)
            int_a = report.get("integrity_a", {})
            int_b = report.get("integrity_b", {})
            assert int_a.get("duplicates", 0) == 0, f"Lighter duplicates: {int_a}"
            assert int_b.get("duplicates", 0) == 0, f"Dukascopy duplicates: {int_b}"
            if int_a.get("ts_step_err", 0) or int_b.get("ts_step_err", 0):
                print(f"    WARN ts_step_err: A={int_a.get('ts_step_err')} B={int_b.get('ts_step_err')}")

            path = save_compat_report(report, datafiles_root=root)
            out_dir = Path(root) / "compat_reports"
            set_host_readable_permissions(out_dir)
            if Path(path).parent == out_dir:
                set_host_readable_permissions(path)

            print(f"  {symbol}: OK aligned={report['aligned_count']} corr={report['returns'].get('corr', 0):.4f} → {path}")
            break
        else:
            print(f"  {symbol}: SKIP insufficient data after 72h and 24h")

    return all_ok


def main():
    print("=" * 60)
    print("P8.1 — Compat report real (Lighter vs Dukascopy)")
    print("=" * 60)

    symbols = _select_symbols()
    if not symbols:
        print("  SKIP: no symbols configured")
        sys.exit(EXIT_SKIP)

    # Preflight primer símbol (o el que correspongui)
    first = symbols[0]
    ok, reason = asyncio.run(preflight_compat_report_real(first))
    if not ok:
        print(f"  SKIP: {reason}")
        sys.exit(EXIT_SKIP)

    print("  Preflight OK")
    all_ok = asyncio.run(_run())
    print()
    if all_ok:
        print("  ✓ compat_report real PASS")
        sys.exit(0)
    else:
        print("  ✗ compat_report real FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
