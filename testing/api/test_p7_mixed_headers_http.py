"""
P7b — API test: headers X-Data-Source / X-Data-Cutover-Ts via HTTP real (0 network)

Arrenca broker amb fixtures locals (primary CSV + dukascopy cache + compat_registry).
Valida: primary-only, fallback-only, mixed PASS, mixed DENY (422).
"""

import json
import shutil
import traceback
import signal
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

ROOT = Path(__file__).resolve().parent.parent.parent
TZ = ZoneInfo("America/New_York")
BASE_TIME = datetime(2026, 2, 8, 10, 0, 0, tzinfo=TZ)
CUTOVER_TS = int(BASE_TIME.timestamp())


def _setup_primary(tmpdir: str) -> None:
    """Primary store: EURUSD des de BASE_TIME (cutover)."""
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


def _setup_dukascopy_cache(tmpdir: str) -> None:
    """Dukascopy cache: EURUSD abans de cutover (08:00–10:00 NY)."""
    start = BASE_TIME - timedelta(hours=2)
    cache_dir = Path(tmpdir) / "dukascopy_cache" / "EURUSD" / str(start.year)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{start.month:02d}.csv"
    with open(path, "w") as f:
        f.write("ts,open,high,low,close,volume\n")
        for i in range(120):
            ts = int((start + timedelta(minutes=i)).timestamp())
            ts = (ts // 60) * 60
            o = 1.04 + i * 0.0001
            f.write(f"{ts},{o},{o+0.0002},{o-0.0002},{o+0.0001},0\n")


def _setup_registry(tmpdir: str, eurusd_status: str) -> None:
    """Compat registry: EURUSD status PASS o FAIL."""
    reg_dir = Path(tmpdir) / "compat_probe"
    reg_dir.mkdir(parents=True, exist_ok=True)
    with open(reg_dir / "compat_registry.json", "w") as f:
        json.dump({"EURUSD": {"status": eurusd_status, "asof_ts": CUTOVER_TS, "window_hours": 72}}, f)


def _start_broker(tmpdir: str, port: int = 8002) -> subprocess.Popen:
    env = {
        "DATAFILES_ROOT": tmpdir,
        "MODE": "backtest",
        "VENUE": "gtrade",
        "PORT": str(port),
        "PYTHONPATH": str(ROOT),
        "DUKASCOPY_BACKFILL_MODE": "m1",
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
    for _ in range(25):
        try:
            r = requests.get(f"{base}/", timeout=2)
            if r.status_code == 200:
                return proc
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(1)
    proc.terminate()
    proc.wait(timeout=3)
    raise RuntimeError("Broker no arrenca dins timeout")


def test_primary_only(tmpdir: str, port: int) -> None:
    """Query dins primary → X-Data-Source=primary, no X-Data-Cutover-Ts."""
    since = int((BASE_TIME + timedelta(minutes=10)).timestamp())
    to = int((BASE_TIME + timedelta(minutes=30)).timestamp())
    r = requests.get(f"http://localhost:{port}/api/v1/broker/ohlcv/EURUSD?since={since}&to={to}&tf=1m", timeout=10)
    assert r.status_code == 200
    assert r.headers.get("X-Data-Source") == "primary"
    assert "X-Data-Cutover-Ts" not in r.headers or r.headers.get("X-Data-Cutover-Ts") == ""
    data = r.json()
    assert data["count"] == 20
    print("✓ primary-only OK")


def test_fallback_only(tmpdir: str, port: int) -> None:
    """Query abans cutover → X-Data-Source=fallback."""
    since = int((BASE_TIME - timedelta(hours=1)).timestamp())
    to = int((BASE_TIME - timedelta(minutes=30)).timestamp())
    r = requests.get(f"http://localhost:{port}/api/v1/broker/ohlcv/EURUSD?since={since}&to={to}&tf=1m", timeout=10)
    assert r.status_code == 200
    assert r.headers.get("X-Data-Source") == "fallback"
    data = r.json()
    assert data["count"] == 30
    print("✓ fallback-only OK")


def test_mixed_pass(tmpdir: str, port: int) -> None:
    """Query travessa cutover + registry PASS → mixed + X-Data-Cutover-Ts."""
    since = int((BASE_TIME - timedelta(minutes=30)).timestamp())
    to = int((BASE_TIME + timedelta(minutes=30)).timestamp())
    r = requests.get(f"http://localhost:{port}/api/v1/broker/ohlcv/EURUSD?since={since}&to={to}&tf=1m", timeout=10)
    assert r.status_code == 200
    assert r.headers.get("X-Data-Source") == "mixed"
    assert r.headers.get("X-Data-Cutover-Ts") == str(CUTOVER_TS)
    data = r.json()
    assert data["count"] == 60
    print("✓ mixed PASS OK")


def test_mixed_deny(tmpdir: str, port: int) -> None:
    """Query travessa cutover + registry FAIL → 422 MIXED_SOURCE_NOT_ALLOWED."""
    since = int((BASE_TIME - timedelta(minutes=30)).timestamp())
    to = int((BASE_TIME + timedelta(minutes=30)).timestamp())
    r = requests.get(f"http://localhost:{port}/api/v1/broker/ohlcv/EURUSD?since={since}&to={to}&tf=1m", timeout=10)
    assert r.status_code == 422
    data = r.json()
    assert data.get("code") == "MIXED_SOURCE_NOT_ALLOWED"
    print("✓ mixed DENY 422 OK")


def main() -> int:
    print("=" * 60)
    print("P7b — Mixed headers via HTTP (0 network)")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp(prefix="brokerage_p7b_")
    port = 8002

    try:
        _setup_primary(tmpdir)
        _setup_dukascopy_cache(tmpdir)
        _setup_registry(tmpdir, "PASS")

        proc = _start_broker(tmpdir, port)
        try:
            test_primary_only(tmpdir, port)
            test_fallback_only(tmpdir, port)
            test_mixed_pass(tmpdir, port)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

        _setup_registry(tmpdir, "FAIL")
        proc2 = _start_broker(tmpdir, port)
        try:
            test_mixed_deny(tmpdir, port)
        finally:
            proc2.terminate()
            proc2.wait(timeout=5)

        print()
        print("✓ Tots els tests P7b HTTP passats")
        return 0
    except Exception as e:
        print(f"\n✗ Error: {e}")
        traceback.print_exc()
        return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
