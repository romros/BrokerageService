"""
API test: headers X-Data-Source=ostium_recorded quan Ostium primary (0 network)

Arrenca broker amb OSTIUM_ENABLED=1, ostium_compat_registry PASS, fixtures.
Valida: X-Data-Source=ostium_recorded, X-Data-Primary-Source=ostium_recorded.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore
from application.data.ostium_compat_registry import save_ostium_registry

ROOT = Path(__file__).resolve().parent.parent.parent
TZ = ZoneInfo("America/New_York")
BASE_TIME = datetime(2026, 2, 8, 10, 0, 0, tzinfo=TZ)


def _setup_primary(tmpdir: str) -> None:
    store = CSVCandleStore(root_path=tmpdir, broker="gtrade", canonical_tz="America/New_York")
    for i in range(120):
        store.append(Candle(
            symbol="EURUSD",
            timestamp=BASE_TIME + timedelta(minutes=i),
            open=1.05 + i * 0.0001,
            high=1.051 + i * 0.0001,
            low=1.049 + i * 0.0001,
            close=1.05 + i * 0.0001,
            volume=50.0,
        ))


def _setup_ostium_registry(tmpdir: str) -> None:
    reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    save_ostium_registry("EURUSD", "PASS", "corr=0.98", registry_path=str(reg_path))


def _start_broker(tmpdir: str, port: int = 8003) -> subprocess.Popen:
    env = {
        "DATAFILES_ROOT": tmpdir,
        "MODE": "backtest",
        "VENUE": "gtrade",
        "PORT": str(port),
        "PYTHONPATH": str(ROOT),
        "DATA_LAYER_ENABLED": "1",
        "OSTIUM_ENABLED": "1",
        "DATA_LAYER_WRITE_MODE": "realtime_plus_backfill",
        "SYMBOLS": "EURUSD",
        "OSTIUM_INGEST_ENABLED_OVERRIDE": "1",  # 0-network: simula Ostium primary sense API
    }
    for k, v in list(__import__("os").environ.items()):
        if k not in env:
            env[k] = v
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "application.main:app", "--host=0.0.0.0", f"--port={port}"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://localhost:{port}"
    for _ in range(30):
        try:
            r = requests.get(f"{base}/", timeout=2)
            if r.status_code == 200:
                return proc
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(1)
    proc.terminate()
    proc.wait(timeout=3)
    raise RuntimeError("Broker no arrenca")


def test_primary_ostium_headers(port: int) -> None:
    """Query dins primary amb Ostium PASS -> X-Data-Source=ostium_recorded."""
    since = int((BASE_TIME + timedelta(minutes=10)).timestamp())
    to = int((BASE_TIME + timedelta(minutes=30)).timestamp())
    r = requests.get(
        f"http://localhost:{port}/api/v1/broker/ohlcv/EURUSD?since={since}&to={to}&tf=1m",
        timeout=10,
    )
    assert r.status_code == 200
    assert r.headers.get("X-Data-Source") == "ostium_recorded"
    assert r.headers.get("X-Data-Primary-Source") == "ostium_recorded"
    data = r.json()
    assert data["count"] == 20
    print("✓ X-Data-Source=ostium_recorded OK")


def test_coverage_ostium_source(port: int) -> None:
    """Coverage amb Ostium primary -> source=ostium_recorded."""
    r = requests.get(
        f"http://localhost:{port}/api/v1/broker/coverage?symbol=EURUSD&resolution=1m",
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("source") == "ostium_recorded"
    print("✓ coverage source=ostium_recorded OK")


def main() -> int:
    print("=" * 60)
    print("API test: OHLCV headers primary Ostium (0 network)")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp(prefix="brokerage_ostium_headers_")
    port = 8003

    try:
        _setup_primary(tmpdir)
        _setup_ostium_registry(tmpdir)

        proc = _start_broker(tmpdir, port)
        try:
            test_primary_ostium_headers(port)
            test_coverage_ostium_source(port)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

        print()
        print("✓ Tots els tests OHLCV headers primary Ostium passats")
        return 0
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
