#!/usr/bin/env python3
"""
Ostium compat report amb dades reals (Ostium store vs Dukascopy)

Opt-in: --include-ostium-compat
Preflight: SKIP exit 2 si entorn no preparat (Ostium candles al store + Dukascopy).

Llegeix candles Ostium del candle_store (CSV), compara amb Dukascopy,
genera artifact i actualitza ostium_compat_registry.

Ús:
  python3 testing/integration/test_ostium_compat_report_real.py
  ./test.sh testing/run_all.py --include-ostium-compat
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from testing.helpers.ostium_compat_test_env import EXIT_SKIP, preflight_ostium_compat_real

SYMBOLS = ["EURUSD", "XAUUSD"]


async def _run():
    from application.tools.ostium_compat_report import run_compat

    root = os.getenv("DATAFILES_ROOT") or str(ROOT / "datafiles")
    broker = os.getenv("VENUE", "gtrade")
    window_minutes = int(os.getenv("OSTIUM_COMPAT_WINDOW_MINUTES", "650"))

    all_ok = True
    for symbol in SYMBOLS:
        ok, reason = await preflight_ostium_compat_real(symbol, datafiles_root=root, broker=broker)
        if not ok:
            print(f"  {symbol}: SKIP {reason}")
            continue

        result = await run_compat(
            symbol=symbol,
            window_minutes=window_minutes,
            datafiles_root=root,
            broker=broker,
        )
        status = result.get("status", "N/A")
        aligned = result.get("aligned_count", 0)
        path = result.get("path", "")
        # Només fail si hi ha error de store/fetch (path=None); verdict FAIL per dades és vàlid
        if not path and "store read error" in str(result.get("verdict_reason", "")):
            all_ok = False
        if not path and "dukascopy fetch error" in str(result.get("verdict_reason", "")):
            all_ok = False
        print(f"  {symbol}: {status} aligned={aligned} → {path}")

    return all_ok


def main():
    print("=" * 60)
    print("Ostium compat report real (Ostium store vs Dukascopy)")
    print("=" * 60)

    first = SYMBOLS[0]
    ok, reason = asyncio.run(preflight_ostium_compat_real(first))
    if not ok:
        print(f"  SKIP: {reason}")
        sys.exit(EXIT_SKIP)

    print("  Preflight OK")
    all_ok = asyncio.run(_run())
    print()
    if all_ok:
        print("  ✓ ostium_compat_report real PASS")
        sys.exit(0)
    else:
        print("  ✗ ostium_compat_report real FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
