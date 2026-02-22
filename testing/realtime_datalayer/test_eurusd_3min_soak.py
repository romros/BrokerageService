#!/usr/bin/env python3
"""
Realtime DataLayer — soak 3 min seguint EURUSD.

Comprova si EURUSD es degrada o es queda estancat.
Executa: ./test.sh testing/realtime_datalayer/test_eurusd_3min_soak.py

O contra servei en marxa:
  BASE_URL=http://localhost:8081 python3 testing/realtime_datalayer/test_eurusd_3min_soak.py
  SOAK_SYMBOL=USDJPY (opcional; default EURUSD)
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_URL = os.getenv("BASE_URL", "").strip()

SOAK_SYMBOL = (os.getenv("SOAK_SYMBOL", "EURUSD").strip().upper()) or "EURUSD"

REALTIME_PREFIX = os.getenv("REALTIME_PREFIX", "/realtime").strip()
if not REALTIME_PREFIX.startswith("/"):
    REALTIME_PREFIX = "/" + REALTIME_PREFIX
if REALTIME_PREFIX.endswith("/"):
    REALTIME_PREFIX = REALTIME_PREFIX[:-1]
if not REALTIME_PREFIX:
    REALTIME_PREFIX = "/realtime"


def _fetch(client, path):
    if BASE_URL:
        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as r:
                return r.status == 200, __import__("json").loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return False, {"error": str(e) or f"HTTP {e.code}", "http_status": e.code}
        except urllib.error.URLError as e:
            return False, {"error": str(getattr(e, "reason", None) or e), "http_status": None}
        except Exception as e:
            return False, {"error": str(e), "http_status": None}
    r = client.get(path)
    return r.status_code == 200, r.json() if r.status_code == 200 else {}


def main() -> int:
    duration_s = 180  # 3 minuts
    interval_s = 10
    samples = []

    symbols_path = f"{REALTIME_PREFIX}/symbols" if BASE_URL else "/symbols"

    if BASE_URL:
        client = None
        ok, data = _fetch(client, symbols_path)
        if not ok:
            err_msg = data.get("error", "unknown")
            status = data.get("http_status")
            status_str = f" (status={status})" if status is not None else ""
            print(f"Error: no es pot obtenir 200 a {BASE_URL}{symbols_path}{status_str} error={err_msg}")
            return 1
    else:
        from application.app_factory import create_app
        from fastapi.testclient import TestClient
        app = create_app(role="realtime_datalayer")
        client = TestClient(app)
        client.get(symbols_path)

    start = time.time()
    while time.time() - start < duration_s:
        ok, data = _fetch(client, symbols_path)
        if not ok:
            samples.append({"t": int(time.time() - start), "error": "fetch failed"})
        else:
            by = data.get("by_symbol", {}).get(SOAK_SYMBOL, {})
            samples.append({
                "t": int(time.time() - start),
                "ticks": by.get("ticks_seen", 0),
                "candles": by.get("candles_written", 0),
                "state": by.get("state", "?"),
                "last_tick_age_s": by.get("last_tick_age_s"),
                "last_candle_age_s": by.get("last_candle_age_s"),
            })
        time.sleep(interval_s)

    if not BASE_URL and client and hasattr(client, "__exit__"):
        client.__exit__(None, None, None)

    print(f"\n=== Soak 3 min {SOAK_SYMBOL} ===")
    for s in samples:
        print(f"  t={s['t']:3d}s  ticks={s.get('ticks', '?'):>4}  candles={s.get('candles', '?'):>2}  state={s.get('state', '?'):12}  tick_age={s.get('last_tick_age_s')}s  candle_age={s.get('last_candle_age_s')}s")

    last = samples[-1] if samples else {}
    if last.get("state") == "degraded":
        print(f"\n⚠ {SOAK_SYMBOL} ha quedat degraded")
        return 1
    if last.get("candles", 0) < 2 and last.get("ticks", 0) > 5:
        print("\n⚠ Molts ticks però poques candles (possible bloqueig)")
        return 1
    print("\n✓ Soak OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
