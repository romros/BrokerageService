"""
Data Layer soak (30–120 min). Invocat per scripts/run_soak.sh <minutes> data-layer.

Loop cada 60s, loga resum. Al final artifact JSON + exit code.

Exit: 0 OK, 2 DEGRADED, 3 missing/gap, 4 dupes/ts_step, 5 stale, 6 health fail
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import requests
except ImportError:
    print("✗ requests required: pip install requests", file=sys.stderr)
    sys.exit(6)

from application.tools.data_layer_run_eval import eval_data_status

BROKER_URL = os.getenv("BROKER_URL", "http://localhost:8000")
POLL_INTERVAL = 60
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
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    minutes = max(1, min(120, minutes))

    base = BROKER_URL.rstrip("/")
    data_status_url = f"{base}/api/v1/broker/data_status"
    symbols_raw = os.getenv("DATA_LAYER_WRITE_SYMBOLS", os.getenv("SYMBOLS", "XAUUSD,EURUSD"))
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
    sym_str = "_".join(symbols[:3])

    print("Data Layer soak")
    print(f"  Broker: {base}")
    print(f"  Duration: {minutes} min")
    print(f"  Symbols: {symbols}")
    print()

    start = time.monotonic()
    deadline = start + (minutes * 60)
    snapshots = []
    last_result = None
    last_data_status = None

    while time.monotonic() < deadline:
        data_status = _get(data_status_url)
        last_data_status = data_status
        result = eval_data_status(
            data_status,
            max_gap_s=MAX_GAP_S,
            max_missing_per_24h=MAX_MISSING_PER_24H,
            max_stale_seconds=MAX_STALE_SECONDS,
        )
        last_result = result

        elapsed = int(time.monotonic() - start)
        syms_summary = []
        if data_status:
            for sym, m in (data_status.get("symbols") or {}).items():
                s = m.get("symbol_state", "?")
                st = m.get("stale_seconds", 0)
                miss = m.get("missing_minutes_24h", 0)
                syms_summary.append(f"{sym}={s} stale={st} miss={miss}")
        print(f"  [{elapsed}s] {result.verdict} | {' '.join(syms_summary) or 'no symbols'}")

        if result.exit_code != 0:
            print(f"\n✗ Soak FAILED: {result.reason}")
            break

        snapshots.append({"elapsed_s": elapsed, "verdict": result.verdict})
        time.sleep(POLL_INTERVAL)

    # Artifact
    datafiles_root = Path(os.getenv("DATAFILES_ROOT", str(ROOT / "datafiles")))
    runs_dir = datafiles_root / "data_layer_prod_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_path = runs_dir / f"{ts_str}_soak_{sym_str}_{minutes}m.json"
    artifact = {
        "run": "soak",
        "timestamp": ts_str,
        "symbols": symbols,
        "duration_minutes": minutes,
        "result": {
            "exit_code": last_result.exit_code if last_result else 6,
            "verdict": last_result.verdict if last_result else "health_fail",
            "reason": last_result.reason if last_result else "no data",
        },
        "thresholds": {
            "max_gap_s": MAX_GAP_S,
            "max_missing_per_24h": MAX_MISSING_PER_24H,
            "max_stale_seconds": MAX_STALE_SECONDS,
        },
        "snapshots_count": len(snapshots),
        "data_status_final": last_data_status,
    }
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"\n  Artifact: {artifact_path}")
    print(f"  Result: {artifact['result']['verdict']} (exit {artifact['result']['exit_code']})")

    return last_result.exit_code if last_result else 6


if __name__ == "__main__":
    sys.exit(main())
