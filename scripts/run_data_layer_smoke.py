#!/usr/bin/env python3
"""
Data Layer smoke (2–5 min). Per scripts/run_data_layer_smoke.sh.

Preflight: health, data_status, coverage, ohlcv.
Espera 3 min per writer iteration, revalua, guarda artifact.

Exit: 0 OK, 2 DEGRADED, 3 missing/gap, 4 dupes/ts_step, 5 stale, 6 health fail
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import requests
except ImportError:
    print("✗ requests required: pip install requests", file=sys.stderr)
    sys.exit(6)

from application.tools.data_layer_run_eval import eval_data_status

BROKER_URL = os.getenv("BROKER_URL", "http://localhost:8000")
SMOKE_WAIT_SECONDS = int(os.getenv("DATA_LAYER_SMOKE_WAIT_S", "180"))  # 3 min
MAX_GAP_S = int(os.getenv("DATA_LAYER_GATES_MAX_GAP_S", "180"))
MAX_MISSING_PER_24H = int(os.getenv("DATA_LAYER_GATES_MAX_MISSING_PER_24H", "1"))
MAX_STALE_SECONDS = int(os.getenv("DATA_LAYER_STALE_SECONDS", "180"))


def _get(url: str, timeout: int = 10) -> dict | None:
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def main() -> int:
    base = BROKER_URL.rstrip("/")
    health_url = f"{base}/api/v1/broker/health"
    data_status_url = f"{base}/api/v1/broker/data_status"
    coverage_url = f"{base}/api/v1/broker/coverage"
    symbols_raw = os.getenv("DATA_LAYER_WRITE_SYMBOLS", os.getenv("SYMBOLS", "XAUUSD,EURUSD"))
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
    symbol = symbols[0] if symbols else "XAUUSD"

    print("Data Layer smoke (2–5 min)")
    print(f"  Broker: {base}")
    print(f"  Symbols: {symbols}")
    print()

    # Preflight
    health = _get(health_url)
    if not health:
        print("✗ Health fail")
        return EXIT_HEALTH_FAIL
    print("✓ Health OK")

    data_status = _get(data_status_url)
    if not data_status:
        print("✗ data_status 503 or fail")
        return EXIT_HEALTH_FAIL
    print("✓ data_status OK")

    coverage = _get(f"{coverage_url}?symbol={symbol}&resolution=1m")
    print(f"  coverage: {coverage is not None}")

    ohlcv_url = f"{base}/api/v1/broker/ohlcv/{symbol}?tf=1m&limit=5"
    ohlcv = _get(ohlcv_url)
    print(f"  ohlcv: {len(ohlcv.get('candles', [])) if ohlcv else 0} candles")

    # Wait for writer iteration
    print(f"\n  Waiting {SMOKE_WAIT_SECONDS}s for writer...")
    time.sleep(SMOKE_WAIT_SECONDS)

    # Re-eval
    data_status = _get(data_status_url)
    result = eval_data_status(
        data_status,
        max_gap_s=MAX_GAP_S,
        max_missing_per_24h=MAX_MISSING_PER_24H,
        max_stale_seconds=MAX_STALE_SECONDS,
    )

    # Artifact
    datafiles_root = Path(os.getenv("DATAFILES_ROOT", str(ROOT / "datafiles")))
    runs_dir = datafiles_root / "data_layer_prod_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sym_str = "_".join(symbols[:3])
    artifact_path = runs_dir / f"{ts_str}_smoke_{sym_str}_3m.json"
    artifact = {
        "run": "smoke",
        "timestamp": ts_str,
        "symbols": symbols,
        "duration_seconds": SMOKE_WAIT_SECONDS,
        "result": {
            "exit_code": result.exit_code,
            "verdict": result.verdict,
            "reason": result.reason,
        },
        "thresholds": {
            "max_gap_s": MAX_GAP_S,
            "max_missing_per_24h": MAX_MISSING_PER_24H,
            "max_stale_seconds": MAX_STALE_SECONDS,
        },
        "data_status_final": data_status,
    }
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"\n  Artifact: {artifact_path}")
    print(f"  Result: {result.verdict} (exit {result.exit_code})")
    if result.reason:
        print(f"  Reason: {result.reason}")

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
