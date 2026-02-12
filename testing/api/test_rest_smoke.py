"""
API smoke test - REST endpoints

Tests:
- Server starts and responds
- /health endpoint
- /mode endpoint
- /ohlcv endpoint (with test data)

Note: Requires server to be running (or starts it in subprocess)
"""


from datetime import datetime, timedelta
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from zoneinfo import ZoneInfo
import requests


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore


class APITestServer:
    """Helper to manage test server lifecycle"""

    def __init__(self, tmpdir: str, port: int = 8001):
        self.tmpdir = tmpdir
        self.port = port
        self.process = None
        self.base_url = f"http://localhost:{port}"

    def start(self):
        """Start FastAPI server in subprocess"""
        print(f"Starting test server on port {self.port}...")

        import os
        env = os.environ.copy()
        env["DATAFILES_ROOT"] = self.tmpdir
        env["MODE"] = "backtest"
        env["VENUE"] = "gtrade"
        env["PORT"] = str(self.port)

        # Start server
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "application.main:app",
             f"--host=0.0.0.0", f"--port={self.port}"],
            cwd=str(Path(__file__).parent.parent.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to be ready
        max_wait = 20  # Increased timeout
        for i in range(max_wait):
            try:
                response = requests.get(f"{self.base_url}/", timeout=2)
                if response.status_code == 200:
                    print(f"✓ Server ready after {i+1}s")
                    time.sleep(0.5)  # Extra wait for full initialization
                    return
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(1)

        # Print error output if server failed to start
        if self.process and self.process.poll() is not None:
            stdout, stderr = self.process.communicate(timeout=1)
            print(f"Server stdout: {stdout.decode()}")
            print(f"Server stderr: {stderr.decode()}")

        raise RuntimeError("Server failed to start within timeout")

    def stop(self):
        """Stop server"""
        if self.process:
            print("Stopping test server...")
            self.process.send_signal(signal.SIGTERM)
            self.process.wait(timeout=5)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def setup_test_data(tmpdir: str):
    """Setup test OHLCV data"""
    print("Setting up test data...")

    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)

    # Create 100 candles for XAUUSD
    for i in range(100):
        candle = Candle(
            symbol="XAUUSD",
            timestamp=base_time + timedelta(minutes=i),
            open=2700.0 + i * 0.1,
            high=2701.0 + i * 0.1,
            low=2699.0 + i * 0.1,
            close=2700.5 + i * 0.1,
            volume=100.0,
        )
        store.append(candle)

    # Create 50 candles for EURUSD
    for i in range(50):
        candle = Candle(
            symbol="EURUSD",
            timestamp=base_time + timedelta(minutes=i),
            open=1.05 + i * 0.0001,
            high=1.051 + i * 0.0001,
            low=1.049 + i * 0.0001,
            close=1.05 + i * 0.0001,
            volume=50.0,
        )
        store.append(candle)

    print("✓ Test data created (100 XAUUSD + 50 EURUSD candles)")


def test_root():
    """Test root endpoint"""
    print("\nTesting GET /...")
    response = requests.get("http://localhost:8001/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "service" in data, "Response should have 'service' field"
    print("✓ Root endpoint OK")


def test_health():
    """Test health endpoint"""
    print("\nTesting GET /api/v1/health...")
    response = requests.get("http://localhost:8001/api/v1/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "ok", f"Expected status=ok, got {data['status']}"
    assert data["mode"] == "backtest", f"Expected mode=backtest, got {data['mode']}"
    assert data["venue"] == "gtrade", f"Expected venue=gtrade, got {data['venue']}"
    print("✓ Health endpoint OK")


def test_mode():
    """Test mode endpoint"""
    print("\nTesting GET /api/v1/mode...")
    response = requests.get("http://localhost:8001/api/v1/mode")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["mode"] == "backtest"
    assert data["is_backtest"] is True
    assert data["is_live"] is False
    assert data["is_paper"] is False
    print("✓ Mode endpoint OK")


def test_ohlcv_basic():
    """Test OHLCV endpoint - basic request"""
    print("\nTesting GET /api/v1/ohlcv/XAUUSD (basic)...")

    response = requests.get("http://localhost:8001/api/v1/ohlcv/XAUUSD?limit=10")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert data["symbol"] == "XAUUSD"
    assert data["timeframe"] == "1m"
    assert data["count"] <= 10, f"Expected max 10 candles, got {data['count']}"
    assert len(data["candles"]) == data["count"]

    # Check candle structure
    if data["candles"]:
        candle = data["candles"][0]
        assert "ts" in candle
        assert "open" in candle
        assert "high" in candle
        assert "low" in candle
        assert "close" in candle
        assert "volume" in candle

    print(f"✓ OHLCV basic OK ({data['count']} candles)")


def test_ohlcv_range():
    """Test OHLCV endpoint - time range request"""
    print("\nTesting GET /api/v1/ohlcv/EURUSD (range)...")

    tz = ZoneInfo("America/New_York")
    base_time = datetime(2026, 2, 8, 10, 0, 0, tzinfo=tz)
    start = int(base_time.timestamp())
    end = int((base_time + timedelta(minutes=20)).timestamp())

    response = requests.get(
        f"http://localhost:8001/api/v1/ohlcv/EURUSD?since={start}&to={end}"
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert data["symbol"] == "EURUSD"
    assert data["count"] == 20, f"Expected 20 candles, got {data['count']}"
    assert data["is_complete"] is True, "Should be complete (no gaps)"

    print(f"✓ OHLCV range OK ({data['count']} candles, complete={data['is_complete']})")


def test_ohlcv_invalid_timeframe():
    """Test OHLCV endpoint - invalid timeframe"""
    print("\nTesting GET /api/v1/ohlcv/XAUUSD (invalid tf)...")

    response = requests.get("http://localhost:8001/api/v1/ohlcv/XAUUSD?tf=5m")
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    data = response.json()
    assert "detail" in data
    assert "1m" in data["detail"].lower(), "Error should mention supported timeframe"

    print("✓ Invalid timeframe handled correctly")


def test_ohlcv_unknown_symbol():
    """Test OHLCV endpoint - unknown symbol (returns empty)"""
    print("\nTesting GET /api/v1/ohlcv/UNKNOWN...")

    response = requests.get("http://localhost:8001/api/v1/ohlcv/UNKNOWN?limit=10")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    data = response.json()
    assert data["symbol"] == "UNKNOWN"
    assert data["count"] == 0, "Unknown symbol should return 0 candles"

    print("✓ Unknown symbol handled correctly")


def main():
    """Run all API smoke tests"""
    print("\n" + "="*60)
    print("API Smoke Tests - REST Endpoints")
    print("="*60)

    tmpdir = tempfile.mkdtemp(prefix="brokerage_test_")

    try:
        # Setup test data
        setup_test_data(tmpdir)

        # Start server and run tests
        with APITestServer(tmpdir, port=8001):
            test_root()
            test_health()
            test_mode()
            test_ohlcv_basic()
            test_ohlcv_range()
            test_ohlcv_invalid_timeframe()
            test_ohlcv_unknown_symbol()

        print("\n" + "="*60)
        print("✓ All API tests passed!")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
