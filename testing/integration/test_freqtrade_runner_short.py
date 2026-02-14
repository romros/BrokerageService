"""
Integration test: Freqtrade runner curt (60–120s) — PAPER DONE handshake

Arrenca broker amb pipeline (USE_FAKE_PRICE_FEED=1) i adapter (USE_FAKE_PRICE_FEED=0).
Per open/close cal adapter → USE_FAKE_PRICE_FEED=0 i credencials Lighter (.env).

Si no hi ha .env Lighter, el broker pot fallar a arrencar; el test fallarà amb timeout.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

PORT = 8009
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
BROKER_URL = f"http://localhost:{PORT}"
HEALTH_TIMEOUT_S = 15
RUNNER_MINUTES = 2  # 120s — prou per ≥1 candle i 1 open+close


def _env_for_broker(tmpdir: str) -> dict:
    """Env vars per arrencar broker. Pipeline + adapter requereix USE_FAKE_PRICE_FEED=0 i Lighter .env."""
    env = os.environ.copy()
    env["VENUE"] = "lighter"
    env["MODE"] = "paper"
    env["USE_FAKE_PRICE_FEED"] = "0"  # Adapter necessari per open/close
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = "ETH,BTC"
    env["DATAFILES_ROOT"] = tmpdir
    env["PORT"] = str(PORT)
    env["MARKET_DATA_ENV"] = env.get("MARKET_DATA_ENV", "mainnet")
    env["ENABLE_LIVE_TRADING"] = "0"
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
    """Executa freqtrade_runner. Retorna (exit_code, stdout+stderr)."""
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
            "lighter",
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


def _has_lighter_env() -> bool:
    """Comprova si hi ha credencials Lighter (test requereix adapter)."""
    return bool(os.getenv("LIGHTER_BASE_URL") or os.getenv("LIGHTER_L1_ADDRESS"))


def main() -> int:
    print("\n" + "=" * 60)
    print("Integration: Freqtrade Runner Short (PAPER DONE handshake)")
    print("=" * 60 + "\n")

    if not _has_lighter_env():
        print("⊘ Skip: LIGHTER_* env not set (test requires adapter for open/close)")
        print("  Set .env with Lighter credentials to run this test.")
        return 0

    tmpdir = tempfile.mkdtemp(prefix="brokerage_freqtrade_")
    root = Path(__file__).resolve().parent.parent.parent
    log_path = Path(tmpdir) / "freqtrade_runner_short.log"
    process = None

    try:
        print(f"Starting broker on port {PORT} (VENUE=lighter, adapter required)...")
        print("  Note: Requires Lighter .env for open/close. Pipeline uses real feed.")
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
                print(f"Broker stdout: {(out or b'').decode()}")
                print(f"Broker stderr: {(err or b'').decode()}")
            print("✗ Broker failed to become ready (check Lighter .env?)")
            return 1

        print("✓ Broker ready")

        print(f"Running freqtrade_runner ({RUNNER_MINUTES} min)...")
        exit_code, output = _run_freqtrade_runner(log_path)
        print(output)

        if exit_code != 0:
            print(f"✗ freqtrade_runner exited with code {exit_code}")
            return 1

        # Assertions
        assert "FREQTRADE_RUNNER" in output, "Expected FREQTRADE_RUNNER output"
        assert "candles_read=" in output or "candles_read" in output, "Expected candles_read"
        assert "opens=" in output or "open" in output.lower(), "Expected opens"
        assert "closes=" in output or "close" in output.lower(), "Expected closes"
        assert "positions_after=0" in output, "Expected positions_after=0"

        # Parse summary for stricter checks
        candles_read = 0
        opens = 0
        closes = 0
        positions_after = -1
        for line in output.split("\n"):
            if "summary" in line.lower():
                for part in line.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "candles_read":
                            candles_read = int(v)
                        elif k == "opens":
                            opens = int(v)
                        elif k == "closes":
                            closes = int(v)
                        elif k == "positions_after":
                            positions_after = int(v)

        assert candles_read >= 1, f"Expected candles_read>=1, got {candles_read}"
        assert opens >= 1, f"Expected opens>=1, got {opens}"
        assert closes >= 1, f"Expected closes>=1, got {closes}"
        assert positions_after == 0, f"Expected positions_after=0, got {positions_after}"

        print("✓ freqtrade_runner passed (exit 0, positions_after=0)")
        print("\n" + "=" * 60)
        print("✓ Freqtrade runner short test passed!")
        print("=" * 60 + "\n")
        return 0

    except AssertionError as e:
        print(f"✗ Assertion failed: {e}")
        return 1
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
