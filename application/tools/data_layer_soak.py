"""
Data Layer soak (30–120 min). Invocat per scripts/run_soak.sh <minutes> data-layer.

Loop cada 60s, loga resum. Al final artifact JSON + exit code.

Post-compat (Ostium): si --post-compat 1, al final del soak intenta compat Ostium vs Dukascopy,
actualitza registry i afegeix graduation_summary a l'artifact. SKIP si no hi ha candles suficients.

Exit: 0 OK, 2 DEGRADED, 3 missing/gap, 4 dupes/ts_step, 5 stale, 6 health fail
"""

import argparse
import asyncio
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
DEFAULT_WAIT_READY_TIMEOUT_S = int(os.getenv("DATA_LAYER_SOAK_WAIT_READY_S", "120"))
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


def wait_for_data_status_ready(
    data_status_url: str,
    timeout_s: int = DEFAULT_WAIT_READY_TIMEOUT_S,
    poll_s: int = 1,
) -> tuple[dict | None, float, str, bool]:
    """
    Poll data_status fins que data_layer_status != initializing o timeout.
    Retorna (data_status, startup_wait_s, startup_status, startup_timeout).
    """
    start = time.monotonic()
    deadline = start + timeout_s
    while time.monotonic() < deadline:
        data_status = _get(data_status_url)
        if data_status is None:
            time.sleep(poll_s)
            continue
        status = data_status.get("data_layer_status", "ready")
        if status != "initializing":
            elapsed = time.monotonic() - start
            return data_status, elapsed, status, False
        time.sleep(poll_s)
    elapsed = time.monotonic() - start
    last = _get(data_status_url)
    return last, elapsed, last.get("data_layer_status", "initializing") if last else "unknown", True


def _run_post_compat(
    compat_symbol: str,
    compat_candles: int,
    datafiles_root: str,
    broker: str,
) -> dict:
    """
    Executa post-compat Ostium vs Dukascopy.
    Retorna dict amb symbol, verdict, ostium_primary_allowed, reason, skipped.
    """
    try:
        from application.tools.ostium_compat_report import run_compat
    except ImportError:
        return {
            "symbol": compat_symbol,
            "verdict": "SKIP",
            "ostium_primary_allowed": False,
            "reason": "ostium_compat_report not available",
            "skipped": True,
        }

    result = asyncio.run(
        run_compat(
            symbol=compat_symbol,
            window_minutes=compat_candles,
            datafiles_root=datafiles_root,
            broker=broker,
        )
    )

    # Si no hi ha Ostium candles o Dukascopy → SKIP (no registry write)
    verdict_reason = result.get("verdict_reason", "")
    if not result.get("registry_updated", False):
        if "no Ostium candles" in verdict_reason or "store read" in verdict_reason:
            return {
                "symbol": compat_symbol,
                "verdict": "SKIP",
                "ostium_primary_allowed": False,
                "reason": verdict_reason,
                "skipped": True,
            }
        if "no Dukascopy" in verdict_reason or "dukascopy" in verdict_reason.lower():
            return {
                "symbol": compat_symbol,
                "verdict": "SKIP",
                "ostium_primary_allowed": False,
                "reason": verdict_reason,
                "skipped": True,
            }

    status = result.get("status", "FAIL")
    return {
        "symbol": compat_symbol,
        "verdict": status,
        "ostium_primary_allowed": result.get("ostium_primary_allowed", False),
        "reason": verdict_reason,
        "skipped": False,
        "path": result.get("path"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Data Layer soak (loop data_status)")
    parser.add_argument("minutes", type=int, nargs="?", default=30, help="Duration minutes (1-120)")
    parser.add_argument("--post-compat", type=int, default=0, help="1 = run Ostium compat after soak (ostium profile)")
    parser.add_argument("--compat-symbol", default=os.getenv("OSTIUM_COMPAT_SYMBOL", "EURUSD"), help="Symbol for compat")
    parser.add_argument("--compat-candles", type=int, default=int(os.getenv("OSTIUM_COMPAT_WINDOW_MINUTES", "650")), help="Window minutes for compat")
    parser.add_argument("--wait-timeout", type=int, default=DEFAULT_WAIT_READY_TIMEOUT_S, help="Seconds to wait for data_status ready")
    parser.add_argument("--profile", default="", help="Profile: ostium = use canonical symbols from data_status")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols (quarantined filtered + warned)")
    args = parser.parse_args()

    minutes = max(1, min(120, args.minutes))
    post_compat = args.post_compat == 1
    compat_symbol = args.compat_symbol.upper()
    compat_candles = args.compat_candles

    base = BROKER_URL.rstrip("/")
    data_status_url = f"{base}/api/v1/broker/data_status"

    # Symbols: --symbols > env > data_status (ostium profile) > default
    symbols_raw = args.symbols or os.getenv("DATA_LAYER_WRITE_SYMBOLS", os.getenv("SYMBOLS", "EURUSD,GBPUSD"))
    symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
    sym_str = "_".join(symbols[:3])

    print("Data Layer soak")
    print(f"  Broker: {base}")
    print(f"  Duration: {minutes} min")
    print(f"  Symbols: {symbols}")
    if post_compat:
        print(f"  Post-compat: {compat_symbol} ({compat_candles}m)")
    print()

    # Wait for data_status ready (no 503 / initializing)
    print("  Waiting for data_status ready...")
    data_status, startup_wait_s, startup_status, startup_timeout = wait_for_data_status_ready(
        data_status_url, timeout_s=args.wait_timeout, poll_s=1
    )
    print(f"  Ready in {startup_wait_s:.0f}s (status={startup_status}, timeout={startup_timeout})")

    # Ostium profile: use canonical symbols from data_status (allowlist - quarantine)
    if args.profile == "ostium" and data_status:
        ds_symbols = list((data_status.get("symbols") or {}).keys())
        if ds_symbols:
            symbols = sorted(ds_symbols)
            sym_str = "_".join(symbols[:3])
            print(f"  Ostium profile: using canonical symbols from data_status: {symbols}")
    # --symbols provided: filter quarantined and warn
    elif args.symbols and data_status:
        syms_data = data_status.get("symbols") or {}
        allowed = []
        for s in symbols:
            m = syms_data.get(s, {})
            if m.get("quarantined"):
                print(f"  WARNING: symbol {s} is quarantined ({m.get('quarantine_reason', '?')}) — ignoring")
            else:
                allowed.append(s)
        symbols = allowed
        sym_str = "_".join(symbols[:3]) if symbols else "none"

    if startup_timeout:
        print(f"\n✗ Soak FAILED: data_status still initializing after {args.wait_timeout}s")
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
            "startup_wait_s": startup_wait_s,
            "startup_status": startup_status,
            "startup_timeout": True,
            "result": {"exit_code": 6, "verdict": "health_fail", "reason": "data_status initializing timeout"},
        }
        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
        print(f"  Artifact: {artifact_path}")
        return 6

    start = time.monotonic()
    deadline = start + (minutes * 60)
    snapshots = []
    last_result = None
    last_data_status = data_status

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
        "startup_wait_s": startup_wait_s,
        "startup_status": startup_status,
        "startup_timeout": False,
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

    graduation_summary = None
    if post_compat:
        # Run post-compat si verdict OK o degraded (no dupes/ts_step ni health_fail)
        exit_ok_for_compat = last_result and last_result.exit_code in (0, 2, 3, 5)
        if exit_ok_for_compat:
            broker_venue = os.getenv("VENUE", "gtrade")
            grad = _run_post_compat(
                compat_symbol=compat_symbol,
                compat_candles=compat_candles,
                datafiles_root=str(datafiles_root),
                broker=broker_venue,
            )
            graduation_summary = grad
            print(f"\n  Post-compat {compat_symbol}: {grad['verdict']} — ostium_primary_allowed={grad['ostium_primary_allowed']}")
            if grad.get("skipped"):
                print(f"    SKIP: {grad.get('reason', '')}")
            elif grad.get("path"):
                print(f"    artifact={grad['path']}")
        else:
            graduation_summary = {
                "symbol": compat_symbol,
                "verdict": "SKIP",
                "ostium_primary_allowed": False,
                "reason": f"soak verdict {last_result.verdict if last_result else 'health_fail'} not suitable for compat",
                "skipped": True,
            }
            print(f"\n  Post-compat {compat_symbol}: SKIP (soak verdict not suitable)")

    if graduation_summary:
        artifact["graduation_summary"] = graduation_summary

    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"\n  Artifact: {artifact_path}")
    print(f"  Result: {artifact['result']['verdict']} (exit {artifact['result']['exit_code']})")

    return last_result.exit_code if last_result else 6


if __name__ == "__main__":
    sys.exit(main())
