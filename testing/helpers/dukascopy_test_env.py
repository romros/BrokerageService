"""
P6 — Preflight per compat_probe (Dukascopy + primary)

Comprova que l'entorn està preparat per test_compat_probe_strategy_level.
Si no → retorna (False, reason) per fer skip amb motiu clar, no fail.

Ordre de comprovació:
1. dukascopy-python instal·lat
2. Primary (candle_store) té dades per almenys 1 símbol (72h)
3. Dukascopy: cache O xarxa disponible (fetch o cache)

Ús:
  ok, reason = await preflight_compat_probe()
  if not ok:
      print(f"SKIP: {reason}")
      sys.exit(2)  # run_all tracta exit 2 com a skipped
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

EXIT_SKIP = 2
WINDOW_HOURS = 72
SYMBOLS = ["EURUSD", "XAUUSD"]


async def preflight_compat_probe() -> Tuple[bool, str]:
    """
    Preflight per compat_probe.
    Returns (ok, reason). Si not ok, reason és el missatge de skip.
    """
    # 1. dukascopy-python
    try:
        import dukascopy_python  # noqa: F401
    except ImportError:
        return False, "dukascopy-python not installed (pip install dukascopy-python)"

    # 2. Primary store amb dades
    root = os.getenv("DATAFILES_ROOT") or str(ROOT / "datafiles")
    broker = os.getenv("PRIMARY_BROKER", "lighter")

    from foundation.config.constants import CANONICAL_TIMEZONE, CANONICAL_TIMEZONE_NAME

    from infrastructure.storage.csv_store import CSVCandleStore  # lazy: evita carregar P6 si no es fa servir
    store = CSVCandleStore(root_path=root, broker=broker, canonical_tz=CANONICAL_TIMEZONE_NAME)

    end = datetime.now(CANONICAL_TIMEZONE)
    start = end - timedelta(hours=WINDOW_HOURS)
    has_primary = False
    for sym in SYMBOLS:
        last = store.get_last_timestamp(sym)
        if last and last >= start:
            rng = store.read_range(sym, start, end, validate_gaps=False)
            if rng.count >= 100:  # Mínim 100 candles per tenir overlap útil
                has_primary = True
                break
    if not has_primary:
        return False, f"Primary store has no data for {SYMBOLS} in last {WINDOW_HOURS}h (need >=100 candles)"

    # 3. Dukascopy: cache o xarxa
    from infrastructure.venues.dukascopy.dukascopy_client import DukascopyClient  # lazy: evita carregar P6 si no es fa servir
    client = DukascopyClient(cache_root=root)
    has_cache = client.has_cache("EURUSD", start, end) or client.has_cache("XAUUSD", start, end)
    if has_cache:
        return True, ""

    # Intentar fetch (xarxa)
    try:
        rows = await asyncio.to_thread(
            client.fetch_candles, "EURUSD", start, end, False
        )
        if len(rows) >= 100:
            return True, ""
    except Exception as e:
        err = str(e).lower()
        if "cache" in err and "network" in err:
            return False, "dukascopy cache missing + network unavailable"
        if "connect" in err or "timeout" in err or "unreachable" in err:
            return False, "Dukascopy API unreachable (network)"
        return False, f"Dukascopy error: {e}"

    return False, "dukascopy cache missing + fetch returned <100 candles"
