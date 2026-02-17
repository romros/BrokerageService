"""
P5 — Unit tests: OHLCV headers + /coverage (Data Observability v0)

Sense xarxa. Usa CSVCandleStore tmpdir i candles fake.
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from application.main import create_app
from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore


def _setup_store_perfect(tmpdir: str, symbol: str = "EURUSD", n: int = 60):
    """Store amb dataset perfecte (sense gaps)."""
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 12, 0, 0, tzinfo=tz)
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )
    for i in range(n):
        store.append(Candle(
            symbol=symbol,
            timestamp=base + timedelta(minutes=i),
            open=1.05 + i * 0.0001,
            high=1.051 + i * 0.0001,
            low=1.049 + i * 0.0001,
            close=1.05 + i * 0.0001,
            volume=50.0,
        ))
    return store, base


def _setup_store_with_gap(tmpdir: str, symbol: str = "XAUUSD"):
    """Store amb gap (escriure primera part, saltar 5 minuts, escriure última part)."""
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )
    # 0-9 (10 candles)
    for i in range(10):
        store.append(Candle(
            symbol=symbol,
            timestamp=base + timedelta(minutes=i),
            open=2700.0 + i,
            high=2701.0 + i,
            low=2699.0 + i,
            close=2700.5 + i,
            volume=100.0,
        ))
    # Gap: 10-14 (5 minuts)
    # 15-29 (15 candles)
    for i in range(15, 30):
        store.append(Candle(
            symbol=symbol,
            timestamp=base + timedelta(minutes=i),
            open=2700.0 + i,
            high=2701.0 + i,
            low=2699.0 + i,
            close=2700.5 + i,
            volume=100.0,
        ))
    return store, base


def test_ohlcv_headers_no_gaps():
    """Store amb dataset perfecte → missing=0, max_gap=0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        store, base = _setup_store_perfect(tmpdir, "EURUSD", 60)
        start_ts = int(base.timestamp())
        end_ts = int((base + timedelta(minutes=30)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")  # trigger lifespan
            r = client.get(
                f"/api/v1/broker/ohlcv/EURUSD?limit=30&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        h = r.headers
        assert h.get("X-Data-Source") == "primary"
        assert "X-Data-Coverage-From" in h
        assert "X-Data-Coverage-To" in h
        assert h.get("X-Data-Missing-Minutes") == "0"
        assert h.get("X-Data-Max-Gap-S") == "0"
        assert h.get("X-Data-Repair") in ("none", "applied", "read_through", "read_through_failed")
        assert "X-Data-Repair-Filled" in h

        data = r.json()
        assert data["symbol"] == "EURUSD"
        assert data["is_complete"] is True
        assert data["missing_count"] == 0

    print("✓ test_ohlcv_headers_no_gaps OK")


def test_ohlcv_headers_with_gap():
    """Store amb gap → missing>0, max_gap>0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        store, base = _setup_store_with_gap(tmpdir, "XAUUSD")
        start_ts = int(base.timestamp())
        end_ts = int((base + timedelta(minutes=30)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")  # trigger lifespan
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        h = r.headers
        assert h.get("X-Data-Source") == "primary"
        missing = int(h.get("X-Data-Missing-Minutes", "0"))
        max_gap = int(h.get("X-Data-Max-Gap-S", "0"))
        assert missing > 0, "Hauria d'haver missing minutes"
        assert max_gap > 0, "Hauria d'haver max_gap_s > 0"

        data = r.json()
        assert data["symbol"] == "XAUUSD"
        assert not data["is_complete"]
        assert data["missing_count"] == missing

    print("✓ test_ohlcv_headers_with_gap OK")


def test_coverage_endpoint():
    """GET /coverage retorna resposta coherent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        _setup_store_perfect(tmpdir, "EURUSD", 100)

        app = create_app()
        with TestClient(app) as client:
            client.get("/")  # trigger lifespan
            r = client.get("/api/v1/broker/coverage?symbol=EURUSD&resolution=1m")
        assert r.status_code == 200

        data = r.json()
        assert data["symbol"] == "EURUSD"
        assert data["resolution"] == "1m"
        assert "earliest_ts" in data
        assert "latest_ts" in data
        assert data["source"] == "primary"
        assert "notes" in data

        w = data["window_72h"]
        assert "expected_minutes" in w
        assert "candles" in w
        assert "missing_minutes" in w
        assert "max_gap_s" in w
        assert w["expected_minutes"] == 4320, "72h = 4320 minuts"

    print("✓ test_coverage_endpoint OK")


def test_coverage_invalid_resolution():
    """GET /coverage amb resolution != 1m → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        _setup_store_perfect(tmpdir, "EURUSD", 10)

        app = create_app()
        with TestClient(app) as client:
            client.get("/")  # trigger lifespan
            r = client.get("/api/v1/broker/coverage?symbol=EURUSD&resolution=5m")
        assert r.status_code == 422
        data = r.json()
        assert data.get("code") == "TIMEFRAME_NOT_SUPPORTED"

    print("✓ test_coverage_invalid_resolution OK")


def test_data_status_503_when_no_pipeline():
    """P7c: GET /data_status → 503 quan no hi ha pipeline (venue=gtrade, mode=backtest)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir

        app = create_app()
        with TestClient(app) as client:
            client.get("/")  # trigger lifespan
            r = client.get("/api/v1/broker/data_status")
        assert r.status_code == 503
        data = r.json()
        assert data.get("code") == "DATA_STATUS_NOT_AVAILABLE"

    print("✓ test_data_status_503_when_no_pipeline OK")


def main():
    print("=" * 60)
    print("P5 — OHLCV headers + /coverage (unit, no xarxa)")
    print("=" * 60)
    test_ohlcv_headers_no_gaps()
    test_ohlcv_headers_with_gap()
    test_coverage_endpoint()
    test_coverage_invalid_resolution()
    test_data_status_503_when_no_pipeline()
    print()
    print("✓ Tots els tests P5 passats")


if __name__ == "__main__":
    main()
