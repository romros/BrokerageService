"""
M3.4 / M3.5 Smoke runner — bootstrap + reconcile loop for N seconds, clean stop.
M3.5: --repeat N, --pause-s, --log-path; SMOKE_RESULT/SMOKE_SUMMARY; log to datafiles/smoke_runs/.

Use: python -m application.smoke --venue lighter --mode PAPER --seconds 120
     python -m application.smoke --venue lighter --repeat 3 --seconds 120  # 3 runs, log auto

RECONCILE_INTERVAL_S is read from env and governs the loop.
Exits with code 1 if any CRITICAL/error (bootstrap or reconcile tick); on --repeat, stops at first failure.
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from domain.interfaces import IVenueAdapter
from domain.models import Position

from loguru import logger as loguru_logger

from application.services.bootstrap_service import run_bootstrap
from foundation.utils.file_permissions import set_host_readable_permissions
from application.services.reconcile_service import (
    ReconcileService,
    reconcile_interval_sec_from_env,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

# Greppable canonical lines (M3.5)
SMOKE_RESULT_PREFIX = "SMOKE_RESULT "
SMOKE_SUMMARY_PREFIX = "SMOKE_SUMMARY "


async def run_smoke(
    adapter: IVenueAdapter,
    tracker: "IPositionTrackerLike",
    duration_sec: float,
    *,
    interval_sec: Optional[float] = None,
    sleep_fn: Optional[Callable] = None,
    bootstrap_fn: Optional[Callable] = None,
) -> tuple[bool, int]:
    """
    Run smoke: bootstrap (if bootstrap_fn) → start reconcile loop → run duration_sec → stop.

    Args:
        adapter: venue adapter (get_open_positions).
        tracker: object with get_positions() (used as local_provider source).
        duration_sec: how long to run the reconcile loop before stopping.
        interval_sec: reconcile interval; if None, use reconcile_interval_sec_from_env().
        sleep_fn: injectable for tests.
        bootstrap_fn: optional async callable(); if None, no bootstrap run.

    Returns:
        (success, error_count). success is False if error_count > 0.
    """
    errors: List[Exception] = []
    interval = interval_sec if interval_sec is not None else reconcile_interval_sec_from_env()

    async def local_provider():
        return tracker.get_positions()

    if bootstrap_fn is not None:
        try:
            await bootstrap_fn()
        except Exception as e:
            logger.exception("Bootstrap failed: %s", e)
            errors.append(e)

    def on_tick_error(exc: Exception) -> None:
        errors.append(exc)

    svc = ReconcileService(
        adapter=adapter,
        local_provider=local_provider,
        interval_sec=interval,
        sleep_fn=sleep_fn,
        on_tick_error=on_tick_error,
        bootstrap_fn=None,  # already ran above
    )
    try:
        await svc.start()
        await asyncio.sleep(duration_sec)
    finally:
        await svc.stop()

    error_count = len(errors)
    success = error_count == 0
    if error_count > 0:
        logger.error("Smoke finished with {} error(s)", error_count)
        for i, e in enumerate(errors, 1):
            logger.error("  error #{}: {}", i, e)
    return success, error_count


# Tracker-like: anything with get_positions() (avoid circular import of IPositionTracker)
class IPositionTrackerLike:
    def get_positions(self) -> List[Position]:
        ...


def _build_mock_wiring():
    """Build mock adapter + tracker for --venue mock (tests / dry run)."""
    # Lazy: evita carregar infrastructure/domain si --venue mock (només es crida per mock)
    from infrastructure.reconcile import InMemoryPositionTracker  # lazy: mock path
    from domain.models import Position  # lazy: mock path

    class FakeAdapter:
        async def get_open_positions(self):
            return []

        async def get_trade_history(self, symbol=None, since=None, to=None, limit=500):
            return []

    return FakeAdapter(), InMemoryPositionTracker()


def _emit_smoke_result(venue: str, mode: str, run: int, total: int, seconds: float, status: str, errors: int) -> None:
    line = f"{SMOKE_RESULT_PREFIX}venue={venue} mode={mode} run={run}/{total} seconds={seconds} status={status} errors={errors}"
    print(line, flush=True)  # stdout per test_smoke_repeat + grep
    logger.info(line)  # log file quan --log-path


def _emit_smoke_summary(venue: str, mode: str, runs: int, ok: int, failed: int, log_path: Optional[str] = None) -> None:
    parts = [f"{SMOKE_SUMMARY_PREFIX}venue={venue} mode={mode} runs={runs} ok={ok} failed={failed}"]
    if log_path is not None:
        parts.append(f" log_path={log_path}")
    line = "".join(parts)
    print(line, flush=True)  # stdout per test_smoke_repeat + grep
    logger.info(line)  # log file quan --log-path


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke runner: bootstrap + reconcile loop")
    parser.add_argument("--venue", default=os.getenv("VENUE", "mock"), help="Venue (mock | lighter)")
    parser.add_argument("--mode", default=os.getenv("MODE", "PAPER"), help="Mode (PAPER | LIVE)")
    parser.add_argument("--seconds", "--duration", type=float, default=120, dest="seconds", help="Run duration (seconds)")
    parser.add_argument("--repeat", type=int, default=1, help="Number of consecutive runs (default 1)")
    parser.add_argument("--pause-s", type=float, default=5.0, dest="pause_s", help="Pause between runs in seconds (default 5)")
    parser.add_argument("--log-path", type=str, default=None, dest="log_path", help="Write stdout/stderr to this file (default when repeat>1: datafiles/smoke_runs/<ts>_<venue>_<N>x.log)")
    args = parser.parse_args()

    repeat = max(1, args.repeat)
    pause_s = max(0.0, args.pause_s)
    log_path: Optional[str] = args.log_path
    if log_path is None and repeat > 1:
        datafiles = os.getenv("DATAFILES_ROOT", "datafiles")
        Path(datafiles).mkdir(parents=True, exist_ok=True)
        runs_dir = Path(datafiles) / "smoke_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        set_host_readable_permissions(runs_dir)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_path = str(runs_dir / f"{ts}_{args.venue}_{repeat}x.log")

    # Loguru captura sys.stderr a la config; el Tee no rep els logs.
    # Afegim un sink directe al fitxer perquè el log es vagi omplint durant el soak.
    log_sink_id = None
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        # Banner immediat: l'usuari veu que el fitxer no és buit des del principi
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Soak smoke started at {datetime.now().isoformat()}\n")
            f.flush()
        set_host_readable_permissions(log_path)
        log_sink_id = loguru_logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
            level="INFO",
            encoding="utf-8",
            mode="a",  # append després del banner
        )

    try:
        return _main_impl(args, repeat, pause_s, log_path)
    finally:
        if log_sink_id is not None:
            loguru_logger.remove(log_sink_id)


def _main_impl(args, repeat: int, pause_s: float, log_path: Optional[str]) -> int:
    adapter = None
    tracker = None

    if args.venue == "mock":
        adapter, tracker = _build_mock_wiring()
    elif args.venue == "lighter":
        try:
            # Lazy: evita carregar lighter/builders si --venue mock
            from infrastructure.reconcile import InMemoryPositionTracker  # lazy: lighter path
            from infrastructure.builders.lighter_di import build_lighter_paper_adapter  # lazy: lighter path
            adapter = build_lighter_paper_adapter()
            tracker = InMemoryPositionTracker()
        except Exception as e:
            logger.exception("Failed to build Lighter wiring: %s", e)
            return 1
    else:
        logger.error("Unsupported venue: %s (use mock or lighter)", args.venue)
        return 1

    async def _run_once():
        """Run one smoke cycle with full adapter lifecycle (start → run → stop)."""
        # For lighter: start adapter, bootstrap, run smoke, stop adapter (try/finally)
        # For mock: adapter has no start/stop
        if args.venue == "lighter":
            try:
                await adapter.start()
                await run_bootstrap(adapter, tracker)
                return await run_smoke(
                    adapter, tracker, args.seconds,
                    interval_sec=reconcile_interval_sec_from_env(),
                    bootstrap_fn=None,  # already ran bootstrap above
                )
            finally:
                await adapter.stop()
        else:
            # mock: no start/stop
            return await run_smoke(
                adapter, tracker, args.seconds,
                interval_sec=reconcile_interval_sec_from_env(),
                bootstrap_fn=None,
            )

    ok_count = 0
    for run_num in range(1, repeat + 1):
        try:
            success, error_count = asyncio.run(_run_once())
        except Exception as e:
            logger.exception(f"Smoke run {run_num}/{repeat} failed with exception: {e}")
            success = False
            error_count = 1
        
        status = "OK" if success else "FAILED"
        _emit_smoke_result(args.venue, args.mode, run_num, repeat, args.seconds, status, error_count)
        if not success:
            _emit_smoke_summary(args.venue, args.mode, repeat, ok_count, 1, log_path=log_path)
            return 1
        ok_count += 1
        if run_num < repeat:
            time.sleep(pause_s)

    _emit_smoke_summary(args.venue, args.mode, repeat, ok_count, 0, log_path=log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
