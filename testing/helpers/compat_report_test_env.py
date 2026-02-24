"""
P8.1 — Preflight per compat_report real (Lighter + Dukascopy)

Comprova que l'entorn està preparat per test_compat_report_real.
Si no → retorna (False, reason) per fer skip amb motiu clar, no fail.

Ordre de comprovació:
1. Lighter Candlestick API accessible
2. Dukascopy: cache o xarxa disponible (EURUSD/XAUUSD)
3. Si testnet + ETH: skip "Dukascopy no té ETH"

Ús:
  ok, reason = await preflight_compat_report_real(symbol)
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

# Dukascopy només suporta EURUSD, XAUUSD
DUKASCOPY_SYMBOLS = frozenset({"EURUSD", "XAUUSD", "XAU"})


async def preflight_compat_report_real(symbol: str) -> Tuple[bool, str]:
    """
    Preflight per P8.1 compat_report real.
    Returns (ok, reason). Si not ok, reason és el missatge de skip.
    """
    s = symbol.upper().strip()
    if s == "XAU":
        s = "XAUUSD"

    # ETH (testnet): Dukascopy no té ETH
    if s == "ETH":
        return False, "Dukascopy no té ETH (només EURUSD, XAUUSD)"

    # 1. Lighter
    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    try:
        from testing.helpers.legacy_venue_test_env import preflight_lighter_candlestick
        ok, reason = await preflight_lighter_candlestick(symbol=s)
        if not ok:
            return False, f"Lighter: {reason}"
    except Exception as e:
        return False, f"Lighter preflight error: {e}"

    # 2. Dukascopy (només si el símbol és suportat)
    if s not in DUKASCOPY_SYMBOLS:
        return False, f"Dukascopy no suporta {symbol} (només EURUSD, XAUUSD)"

    try:
        import dukascopy_python  # noqa: F401
    except ImportError:
        return False, "dukascopy-python not installed (pip install dukascopy-python)"

    root = os.getenv("DATAFILES_ROOT") or str(ROOT / "datafiles")
    from infrastructure.venues.dukascopy.dukascopy_client import DukascopyClient
    client = DukascopyClient(cache_root=root)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=72)
    has_cache = client.has_cache(s, start, end)
    if has_cache:
        return True, ""

    try:
        rows = await asyncio.to_thread(client.fetch_candles, s, start, end, False)
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
