"""
Integration test: WS soak curt (60–120s) — P2.1

Reutilitza ws_soak.py amb durada curta. Assert:
- rep ≥1 candle
- reconnects <= allow_reconnects
- max_gap <= threshold

Arrenca broker amb USE_FAKE_PRICE_FEED=1 (sense xarxa).
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

PORT = 8008
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
WS_URL = f"ws://localhost:{PORT}/api/v1/ws"
HEALTH_TIMEOUT_S = 10
SOAK_MINUTES = 2  # 120s — prou per ≥2 candles
ALLOW_RECONNECTS = 3
MAX_GAP_SECONDS = 120


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
        time.sleep(0.5)
    return False


def _run_ws_soak(log_path: Path) -> int:
    """Executa ws_soak com subprocess. Retorna exit code."""
    root = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    if str(root) not in env.get("PYTHONPATH", "").split(os.pathsep):
        env["PYTHONPATH"] = os.pathsep.join([str(root), env.get("PYTHONPATH", "")])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "application.tools.ws_soak",
            "--minutes",
            str(SOAK_MINUTES),
            "--ws-url",
            WS_URL,
            "--topic",
            "candle:ETH:1m",
            "--allow-reconnects",
            str(ALLOW_RECONNECTS),
            "--max-gap-seconds",
            str(MAX_GAP_SECONDS),
            "--log-path",
            str(log_path),
        ],
        cwd=str(root),
        env=env,
    )
    return result.returncode


def _stop_broker(process: subprocess.Popen | None) -> None:
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
    print("Integration: WS Soak Short (fake feed, 2 min)")
    print("=" * 60 + "\n")

    tmpdir = tempfile.mkdtemp(prefix="brokerage_ws_soak_")
    root = Path(__file__).parent.parent.parent
    log_path = Path(tmpdir) / "ws_soak_short.log"
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

        print(f"Running ws_soak ({SOAK_MINUTES} min)...")
        exit_code = _run_ws_soak(log_path)

        if exit_code != 0:
            if log_path.exists():
                print(f"Log:\n{log_path.read_text()}")
            print(f"✗ ws_soak exited with code {exit_code}")
            return 1

        # Verificar output canònic
        log_text = log_path.read_text()
        assert "WS_SOAK_RESULT status=OK" in log_text, "Expected WS_SOAK_RESULT status=OK"
        assert "WS_SOAK_SUMMARY" in log_text, "Expected WS_SOAK_SUMMARY"

        print("✓ ws_soak passed (exit 0, status=OK)")
        print("\n" + "=" * 60)
        print("✓ WS soak short test passed!")
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
