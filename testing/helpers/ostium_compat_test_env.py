"""
Preflight per Ostium compat report real (Ostium store + Dukascopy)

Comprova que l'entorn està preparat per test_ostium_compat_report_real.
Si no → retorna (False, reason) per fer skip amb motiu clar, no fail.

Ordre de comprovació:
1. Ostium candles al candle_store (CSV) per símbol
2. Dukascopy: cache o xarxa disponible (EURUSD/XAUUSD)

Ús:
  ok, reason = await preflight_ostium_compat_real(symbol, datafiles_root, broker)
  if not ok:
      print(f"SKIP: {reason}")
      sys.exit(2)
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

DUKASCOPY_SYMBOLS = frozenset({"EURUSD", "XAUUSD", "XAU"})
MIN_OSTIUM_CANDLES = 100


async def preflight_ostium_compat_real(
    symbol: str,
    datafiles_root: str | None = None,
    broker: str = "gtrade",
) -> Tuple[bool, str]:
    """
    Preflight per Ostium compat report real.
    Returns (ok, reason). Si not ok, reason és el missatge de skip.
    """
    s = symbol.upper().strip()
    if s == "XAU":
        s = "XAUUSD"

    if s not in DUKASCOPY_SYMBOLS:
        return False, f"Dukascopy no suporta {symbol} (només EURUSD, XAUUSD)"

    root = datafiles_root or os.getenv("DATAFILES_ROOT") or str(ROOT / "datafiles")

    # 1. Ostium candles al store
    from infrastructure.storage.csv_store import CSVCandleStore
    store = CSVCandleStore(root_path=root, broker=broker)
    now = datetime.now(timezone.utc)
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=650)
    try:
        cr = store.read_range(s, start, end, validate_gaps=False)
        candles_a = cr.candles if cr else []
    except Exception as e:
        return False, f"store read error: {e}"
    if len(candles_a) < MIN_OSTIUM_CANDLES:
        return False, f"Ostium store <{MIN_OSTIUM_CANDLES} candles (got {len(candles_a)})"

    # 2. Dukascopy
    try:
        import dukascopy_python  # noqa: F401
    except ImportError:
        return False, "dukascopy-python not installed (pip install dukascopy-python)"

    from infrastructure.venues.dukascopy.dukascopy_client import DukascopyClient
    client = DukascopyClient(cache_root=root)
    has_cache = client.has_cache(s, start, end)
    if has_cache:
        return True, ""

    try:
        rows = await asyncio.to_thread(client.fetch_candles, s, start, end, False)
        if len(rows) >= MIN_OSTIUM_CANDLES:
            return True, ""
    except Exception as e:
        err = str(e).lower()
        if "cache" in err and "network" in err:
            return False, "dukascopy cache missing + network unavailable"
        if "connect" in err or "timeout" in err or "unreachable" in err:
            return False, "Dukascopy API unreachable (network)"
        return False, f"Dukascopy error: {e}"

    return False, "dukascopy cache missing + fetch returned <100 candles"
