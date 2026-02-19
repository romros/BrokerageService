#!/usr/bin/env python3
"""
Realtime DataLayer — soak 3 min seguint EURUSD.

Comprova si EURUSD es degrada o es queda estancat.
Executa: ./test.sh testing/realtime_datalayer/test_eurusd_3min_soak.py

O contra servei en marxa:
  BASE_URL=http://localhost:8081 python3 testing/realtime_datalayer/test_eurusd_3min_soak.py
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_URL = os.getenv("BASE_URL", "").strip()


def _fetch(client, path):
    if BASE_URL:
        import urllib.request
        try:
            with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as r:
                return r.status == 200, __import__("json").loads(r.read().decode())
        except Exception as e:
            return False, {"error": str(e)}
    r = client.get(path)
    return r.status_code == 200, r.json() if r.status_code == 200 else {}


def main() -> int:
    duration_s = 180  # 3 minuts
    interval_s = 10
    samples = []

    if BASE_URL:
        client = None
        ok, _ = _fetch(client, "/symbols")
        if not ok:
            print(f"Error: no es pot connectar a {BASE_URL}")
            return 1
    else:
        from application.app_factory import create_app
        from fastapi.testclient import TestClient
        app = create_app(role="realtime_datalayer")
        client = TestClient(app)
        client.get("/symbols")

    start = time.time()
    while time.time() - start < duration_s:
        ok, data = _fetch(client, "/symbols")
        if not ok:
            samples.append({"t": int(time.time() - start), "error": "fetch failed"})
        else:
            by = data.get("by_symbol", {}).get("EURUSD", {})
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

    print("\n=== Soak 3 min EURUSD ===")
    for s in samples:
        print(f"  t={s['t']:3d}s  ticks={s.get('ticks', '?'):>4}  candles={s.get('candles', '?'):>2}  state={s.get('state', '?'):12}  tick_age={s.get('last_tick_age_s')}s  candle_age={s.get('last_candle_age_s')}s")

    last = samples[-1] if samples else {}
    if last.get("state") == "degraded":
        print("\n⚠ EURUSD ha quedat degraded")
        return 1
    if last.get("candles", 0) < 2 and last.get("ticks", 0) > 5:
        print("\n⚠ Molts ticks però poques candles (possible bloqueig)")
        return 1
    print("\n✓ Soak OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
