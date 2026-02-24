#!/usr/bin/env python3
"""
P7c — Data Layer soak: telemetria + evidència operativa

Valida que el pipeline candles→store→API funciona en runtime real (30–60 min).
Mètriques: missing_minutes<=1, duplicates==0, ts_step_errors==0, counters coherents.

Opt-in: --include-data-layer-soak
Preflight: SKIP exit 2 si entorn no preparat (.env, xarxa).

Output: datafiles/data_layer_soak/<ts>_data_layer_soak_<symbol>_<Nm>.json

Ús:
  python3 testing/integration/test_data_layer_soak_metrics.py --minutes 30 --symbol EURUSD
  ./test.sh testing/run_all.py --include-data-layer-soak
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
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

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

from foundation.utils.file_permissions import set_host_readable_permissions
from testing.helpers.lighter_test_env import (
    EXIT_SKIP,
    preflight_lighter_candlestick,
    select_soak_symbol,
)

PORT = 8011
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
DATA_STATUS_URL = f"http://localhost:{PORT}/api/v1/broker/data_status"
OHLCV_URL = "http://localhost:{PORT}/api/v1/broker/ohlcv/{symbol}"
COVERAGE_URL = "http://localhost:{PORT}/api/v1/broker/coverage"
HEALTH_TIMEOUT_S = 20
MISSING_MINUTES_MAX = 1
DUPLICATES_MAX = 0
TS_STEP_ERRORS_MAX = 0
DEFAULT_MINUTES = 30
DATA_LAYER_SOAK_SYMBOL_ENV = "DATA_LAYER_SOAK_SYMBOL"


def _env_for_broker(tmpdir: str, symbol: str) -> dict:
    """Broker amb Lighter real."""
    symbols = [symbol]
    env = os.environ.copy()
    env["VENUE"] = "lighter"
    env["MODE"] = "paper"
    env["USE_FAKE_PRICE_FEED"] = "0"
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = ",".join(symbols)
    env["LIGHTER_SYMBOLS"] = ",".join(symbols)
    env["BACKFILL_SYMBOLS"] = ",".join(symbols)
    env["DATAFILES_ROOT"] = tmpdir
    env["PORT"] = str(PORT)
    return env


def _wait_for_health() -> bool:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(0.5)
    return False


def _stop_broker(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _get_ohlcv(symbol: str, limit: int = 500) -> list:
    url = f"http://localhost:{PORT}/api/v1/broker/ohlcv/{symbol}?limit={limit}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("candles", [])


def _get_data_status() -> dict | None:
    try:
        r = requests.get(DATA_STATUS_URL, timeout=5)
        if r.status_code == 503:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _get_coverage(symbol: str) -> dict | None:
    try:
        url = f"http://localhost:{PORT}/api/v1/broker/coverage?symbol={symbol}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _validate_candles(candles: list) -> tuple[int, int]:
    """Retorna (ts_step_errors, duplicates). Candles ordenats per ts asc."""
    if len(candles) < 2:
        return 0, 0
    # Ordenar per ts (API pot retornar desc)
    def _ts(c):
        t = c.get("ts") or c.get("timestamp")
        return int(t) if t is not None else 0
    candles = sorted([c for c in candles if _ts(c) > 0], key=_ts)
    if len(candles) < 2:
        return 0, 0
    ts_step_errors = 0
    seen = set()
    duplicates = 0
    for i, c in enumerate(candles):
        ts = c.get("ts") or c.get("timestamp")
        if ts is not None:
            ts = int(ts) if isinstance(ts, (int, float)) else None
        if ts is None:
            continue
        if ts in seen:
            duplicates += 1
        seen.add(ts)
        if i > 0:
            prev_ts = candles[i - 1].get("ts") or candles[i - 1].get("timestamp")
            if prev_ts is not None:
                prev_ts = int(prev_ts) if isinstance(prev_ts, (int, float)) else prev_ts
                delta = ts - prev_ts if isinstance(prev_ts, (int, float)) else 0
                if delta != 60:
                    ts_step_errors += 1
    return ts_step_errors, duplicates


def main() -> int:
    parser = argparse.ArgumentParser(description="P7c Data Layer soak (metrics + validation)")
    parser.add_argument("--minutes", type=int, default=DEFAULT_MINUTES, help="Soak duration (default 30)")
    parser.add_argument(
        "--symbol",
        default=None,
        help="Symbol override (default: autoselect from LIGHTER_BASE_URL: testnet→ETH, mainnet→EURUSD)",
    )
    args = parser.parse_args()

    minutes = max(1, args.minutes)
    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    symbol_override = (args.symbol or os.getenv(DATA_LAYER_SOAK_SYMBOL_ENV, "")).strip() or None
    symbol = select_soak_symbol(base_url, override=symbol_override)
    url_lower = base_url.lower()
    base_url_kind = "testnet" if "testnet" in url_lower else ("mainnet" if "mainnet" in url_lower else "unknown")
    market_data_env = base_url_kind
    selected_symbol_reason = "override" if symbol_override else "auto"

    print("=" * 60)
    print("P7c — Data Layer Soak (metrics + validation)")
    print("=" * 60)
    print(f"  Symbol: {symbol} (base_url={base_url[:50]}..., env={market_data_env})")
    print(f"  Minutes: {minutes}")
    print()

    # Preflight (amb el mateix símbol que usarem al soak)
    ok, reason = asyncio.run(preflight_lighter_candlestick(symbol=symbol))
    if not ok:
        print(f"  SKIP: {reason}")
        return EXIT_SKIP

    tmpdir = tempfile.mkdtemp(prefix="brokerage_p7c_")
    process = None
    artifact_path = None

    try:
        print("Starting broker (Lighter real)...")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "application.main:app",
                "--host=0.0.0.0",
                f"--port={PORT}",
            ],
            cwd=str(ROOT),
            env=_env_for_broker(tmpdir, symbol),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_health():
            print("✗ Broker failed to become ready")
            return 1

        print("✓ Broker ready")

        # Poll cada minut
        start_time = time.monotonic()
        deadline = start_time + (minutes * 60)
        poll_interval = 60
        last_poll = 0
        data_status_snapshots = []

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_poll >= poll_interval:
                last_poll = now
                elapsed_min = int((now - start_time) / 60)
                try:
                    ohlcv = _get_ohlcv(symbol, limit=10)
                    status = _get_data_status()
                    if status:
                        data_status_snapshots.append({"elapsed_min": elapsed_min, "status": status})
                    print(f"  [{elapsed_min}m] ohlcv={len(ohlcv)} candles")
                except Exception as e:
                    print(f"  [{elapsed_min}m] poll error: {e}")
            time.sleep(5)

        # Final validation
        print("\n  Final validation...")
        candles = _get_ohlcv(symbol, limit=minutes + 100)
        coverage = _get_coverage(symbol)
        final_status = _get_data_status()

        ts_step_errors, duplicates = _validate_candles(candles)
        expected_minutes = minutes
        actual_count = len(candles)
        missing_minutes = max(0, expected_minutes - actual_count)
        candles_written = 0
        if final_status and symbol in final_status.get("symbols", {}):
            sym_metrics = final_status["symbols"][symbol]
            candles_written = sym_metrics.get("candles_written", 0)

        ok_missing = missing_minutes <= MISSING_MINUTES_MAX
        ok_duplicates = duplicates <= DUPLICATES_MAX
        ok_ts_step = ts_step_errors <= TS_STEP_ERRORS_MAX
        ok_counters = candles_written >= max(0, expected_minutes - MISSING_MINUTES_MAX)

        passed = ok_missing and ok_duplicates and ok_ts_step and ok_counters

        # Artifact
        datafiles_root = Path(os.getenv("DATAFILES_ROOT", str(ROOT / "datafiles")))
        soak_dir = datafiles_root / "data_layer_soak"
        soak_dir.mkdir(parents=True, exist_ok=True)
        set_host_readable_permissions(soak_dir)

        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        artifact_path = soak_dir / f"{ts_str}_data_layer_soak_{symbol}_{minutes}m.json"
        artifact = {
            "config": {
                "symbol": symbol,
                "minutes": minutes,
                "timestamp": ts_str,
                "base_url": base_url,
                "base_url_kind": base_url_kind,
                "market_data_env": market_data_env,
                "selected_symbol_reason": selected_symbol_reason,
            },
            "result": {
                "passed": passed,
                "candles_count": len(candles),
                "missing_minutes": missing_minutes,
                "duplicates": duplicates,
                "ts_step_errors": ts_step_errors,
                "candles_written": candles_written,
                "expected_minutes": expected_minutes,
                "actual_count": actual_count,
            },
            "thresholds": {
                "missing_minutes_max": MISSING_MINUTES_MAX,
                "duplicates_max": DUPLICATES_MAX,
                "ts_step_errors_max": TS_STEP_ERRORS_MAX,
            },
            "counters_final": final_status if final_status else {},
            "coverage": coverage,
        }
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
        set_host_readable_permissions(artifact_path)

        print(f"\n  Result: {'PASS' if passed else 'FAIL'}")
        print(f"    candles={len(candles)} expected~{expected_minutes}")
        print(f"    missing_minutes={missing_minutes} (max {MISSING_MINUTES_MAX})")
        print(f"    duplicates={duplicates} ts_step_errors={ts_step_errors}")
        print(f"    candles_written={candles_written}")
        print(f"  Artifact: {artifact_path}")

        if not passed:
            print("\n✗ Data Layer soak FAILED")
            return 1

        print("\n" + "=" * 60)
        print("✓ P7c Data Layer soak passed")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        traceback.print_exc()
        return 1

    finally:
        _stop_broker(process)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
