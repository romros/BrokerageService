"""
Integration test: WS preflight contra broker real (P2.0.1)

Arrenca el broker amb USE_FAKE_PRICE_FEED=1 (sense xarxa), executa ws_preflight
i verifica que el pipeline ticks→candles→store→WS funciona end-to-end.

Estratègia:
- Port 8007 (evita conflictes amb altres tests)
- Broker amb VENUE=lighter, MODE=paper, USE_FAKE_PRICE_FEED=1
- Poll health fins 200 o timeout 10s
- ws_preflight --ws-url ws://localhost:8007/api/v1/ws --symbol ETH --minutes 2
- Assert exit 0
- Cleanup: SIGTERM + kill fallback
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

PORT = 8007
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
WS_URL = f"ws://localhost:{PORT}/api/v1/ws"
HEALTH_TIMEOUT_S = 10
READINESS_POLL_INTERVAL_S = 0.5


def _env_for_broker(tmpdir: str) -> dict:
    """Env vars per arrencar broker amb fake price feed."""
    env = os.environ.copy()
    env["VENUE"] = "lighter"
    env["MODE"] = "paper"
    env["USE_FAKE_PRICE_FEED"] = "1"
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = "ETH,BTC"
    env["DATAFILES_ROOT"] = tmpdir
    env["PORT"] = str(PORT)
    return env


def _wait_for_health() -> bool:
    """Poll health endpoint fins 200 o timeout."""
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(READINESS_POLL_INTERVAL_S)
    return False


def _run_ws_preflight() -> int:
    """Executa ws_preflight com subprocess. Retorna exit code."""
    root = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    if str(root) not in env.get("PYTHONPATH", "").split(os.pathsep):
        env["PYTHONPATH"] = os.pathsep.join([str(root), env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "application.tools.ws_preflight",
            "--ws-url",
            WS_URL,
            "--symbol",
            "ETH",
            "--minutes",
            "2",
        ],
        cwd=str(root),
        env=env,
    )
    return result.returncode


def _stop_broker(process: subprocess.Popen) -> None:
    """Atura broker (SIGTERM + kill fallback)."""
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
    print("Integration: WS Preflight vs Broker Real (fake feed)")
    print("=" * 60 + "\n")

    tmpdir = tempfile.mkdtemp(prefix="brokerage_ws_preflight_")
    root = Path(__file__).parent.parent.parent
    process = None

    try:
        print(f"Starting broker on port {PORT} (USE_FAKE_PRICE_FEED=1)...")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "application.main:app",
                "--host=0.0.0.0",
                f"--port={PORT}",
            ],
            cwd=str(root),
            env=_env_for_broker(tmpdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_health():
            if process and process.poll() is not None:
                out, err = process.communicate(timeout=1)
                print(f"Broker stdout: {out.decode()}")
                print(f"Broker stderr: {err.decode()}")
            print("✗ Broker failed to become ready within timeout")
            return 1

        print("✓ Broker ready")

        print("Running ws_preflight...")
        exit_code = _run_ws_preflight()

        if exit_code != 0:
            print(f"✗ ws_preflight exited with code {exit_code}")
            return 1

        print("✓ ws_preflight passed (exit 0)")
        print("\n" + "=" * 60)
        print("✓ WS preflight integration test passed!")
        print("=" * 60 + "\n")
        return 0

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        _stop_broker(process)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
