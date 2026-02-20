"""
Integration test: Freqtrade runner curt amb venue=paper (zero tx)

Broker: MODE=paper, ENABLE_LIVE_TRADING=0, USE_FAKE_PRICE_FEED=1 → PaperVenueAdapter.
No requereix credencials Lighter. Sempre s'executa.

P3.1: Logs del broker a fitxer; en fallada imprimeix últimes línies.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from testing.helpers.run_broker_subprocess import (
    dump_broker_log_on_failure,
    start_broker_with_logs,
)

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

PORT = 8010
HEALTH_URL = f"http://127.0.0.1:{PORT}/api/v1/broker/health"
BROKER_URL = f"http://127.0.0.1:{PORT}"
HEALTH_TIMEOUT_S = 30
RUNNER_MINUTES = 1


def _env_for_broker(tmpdir: str) -> dict:
    """Paper mode: zero tx, fake feed, no Lighter. Coherent amb AGENTS/ESTAT."""
    env = os.environ.copy()
    env["VENUE"] = "paper"
    env["MODE"] = "paper"
    env["ENABLE_LIVE_TRADING"] = "0"
    env["USE_FAKE_PRICE_FEED"] = "1"
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = "ETH"
    env["DATAFILES_ROOT"] = tmpdir
    env["PORT"] = str(PORT)
    env["MARKET_DATA_ENV"] = env.get("MARKET_DATA_ENV", "mainnet")
    env["TESTING"] = "1"  # P3.1: heartbeat + diagnostics
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


def _run_freqtrade_runner(log_path: Path) -> tuple[int, str]:
    root = Path(__file__).resolve().parent.parent.parent
    env = os.environ.copy()
    if str(root) not in env.get("PYTHONPATH", "").split(os.pathsep):
        env["PYTHONPATH"] = os.pathsep.join([str(root), env.get("PYTHONPATH", "")])
    env["BROKER_URL"] = BROKER_URL

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "application.tools.freqtrade_runner",
            "--broker-url",
            BROKER_URL,
            "--venue",
            "paper",
            "--symbol",
            "ETH",
            "--minutes",
            str(RUNNER_MINUTES),
            "--open-every-minutes",
            "1",
            "--log-dir",
            str(log_path.parent),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode, out


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


def main() -> int:
    print("\n" + "=" * 60)
    print("Integration: Freqtrade Runner Short (venue=paper, zero tx)")
    print("=" * 60 + "\n")

    tmpdir = tempfile.mkdtemp(prefix="brokerage_freqtrade_paper_")
    root = Path(__file__).resolve().parent.parent.parent
    log_path = Path(tmpdir) / "freqtrade_runner_paper.log"
    process = None
    broker_log_path: Path | None = None

    try:
        print(f"Starting broker on port {PORT} (MODE=paper, USE_FAKE_PRICE_FEED=1)...")
        broker_log_path, process = start_broker_with_logs(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "application.main:app",
                "--host=0.0.0.0",
                f"--port={PORT}",
            ],
            env=_env_for_broker(tmpdir),
            cwd=str(root),
            log_dir=Path(tmpdir),
            port=PORT,
        )

        if not _wait_for_health():
            dump_broker_log_on_failure(broker_log_path)
            print("✗ Broker failed to become ready (timeout)")
            return 1

        print("✓ Broker ready (paper mode)")

        print(f"Running freqtrade_runner --venue paper ({RUNNER_MINUTES} min)...")
        exit_code, output = _run_freqtrade_runner(log_path)
        print(output)

        if exit_code != 0:
            dump_broker_log_on_failure(broker_log_path)
            print(f"✗ freqtrade_runner exited with code {exit_code}")
            return 1

        assert "FREQTRADE_RUNNER" in output
        assert "positions_after=0" in output
        assert "opens=" in output or "open" in output.lower()
        assert "closes=" in output or "close" in output.lower()

        print("✓ freqtrade_runner passed (venue=paper, positions_after=0)")
        print("\n" + "=" * 60)
        print("✓ Freqtrade runner short (paper) test passed!")
        print("=" * 60 + "\n")
        return 0

    except AssertionError as e:
        if broker_log_path and broker_log_path.exists():
            dump_broker_log_on_failure(broker_log_path)
        print(f"✗ Assertion failed: {e}")
        return 1
    except Exception as e:
        if broker_log_path and broker_log_path.exists():
            dump_broker_log_on_failure(broker_log_path)
            print(f"✗ Error: {e}")
            traceback.print_exc()
        return 1

    finally:
        _stop_broker(process)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
