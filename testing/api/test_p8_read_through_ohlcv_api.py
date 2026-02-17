"""
P8.0b — API test: Read-through wired to OHLCV (0 network)

Valida que el read-through està cablejat a GET /api/v1/broker/ohlcv/{symbol}:
- omple gaps en el body retornat
- headers P5/P8 coherents
- no muta el store
- guards (max_missing, feature flag)
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

from application.api.broker_routes import set_broker_deps
from application.main import create_app
from domain.models import Candle
from foundation.config.constants import (
    ENABLE_READ_THROUGH_ENV,
    READ_THROUGH_MAX_MISSING_ENV,
)
from infrastructure.data.mock_provider import MockBackfillProvider
from infrastructure.storage.csv_store import CSVCandleStore

TZ = ZoneInfo("America/New_York")
BASE = datetime(2026, 2, 10, 14, 0, 0, tzinfo=TZ)


def _setup_store_single_gap(tmpdir: str, symbol: str = "XAUUSD") -> tuple[CSVCandleStore, datetime]:
    """Store amb 1 gap (falta 1 minut al mig). 0-9, gap 10, 11-29."""
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )
    for i in list(range(10)) + list(range(11, 30)):
        store.append(Candle(
            symbol=symbol,
            timestamp=BASE + timedelta(minutes=i),
            open=2700.0 + i,
            high=2701.0 + i,
            low=2699.0 + i,
            close=2700.5 + i,
            volume=100.0,
        ))
    return store, BASE


def _setup_store_multiple_gaps(tmpdir: str, symbol: str = "XAUUSD") -> tuple[CSVCandleStore, datetime]:
    """Store amb 3 gaps (falten minuts 10, 11, 12)."""
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )
    for i in list(range(10)) + list(range(13, 30)):
        store.append(Candle(
            symbol=symbol,
            timestamp=BASE + timedelta(minutes=i),
            open=2700.0 + i,
            high=2701.0 + i,
            low=2699.0 + i,
            close=2700.5 + i,
            volume=100.0,
        ))
    return store, BASE


def _setup_store_large_gap(tmpdir: str, symbol: str = "XAUUSD") -> tuple[CSVCandleStore, datetime]:
    """Store amb gap de 20 minuts (0-9, gap 10-29, 30-39)."""
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="gtrade",
        canonical_tz="America/New_York",
    )
    for i in list(range(10)) + list(range(30, 50)):
        store.append(Candle(
            symbol=symbol,
            timestamp=BASE + timedelta(minutes=i),
            open=2700.0 + i,
            high=2701.0 + i,
            low=2699.0 + i,
            close=2700.5 + i,
            volume=100.0,
        ))
    return store, BASE


def _ts_list_from_response(data: dict) -> list[int]:
    """Extreu llista de timestamps dels candles de la resposta."""
    return sorted(int(c["ts"]) for c in data.get("candles", []))


def _assert_continuous_ts(ts_list: list[int], step: int = 60) -> None:
    """Assert que ts_list és contínua amb step."""
    for i in range(len(ts_list) - 1):
        assert ts_list[i + 1] - ts_list[i] == step, f"Gap at {ts_list[i]} -> {ts_list[i+1]}"


def test_fills_single_gap():
    """Store amb 1 gap → read-through omple, X-Data-Repair=read_through, Filled=1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        os.environ[ENABLE_READ_THROUGH_ENV] = "1"
        _setup_store_single_gap(tmpdir, "XAUUSD")
        start_ts = int(BASE.timestamp())
        end_ts = int((BASE + timedelta(minutes=30)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")
            set_broker_deps(
                primary_backfill_provider=MockBackfillProvider(base_price=2700.0, seed=42),
                fallback_provider=None,
            )
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?limit=30&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        data = r.json()
        ts_list = _ts_list_from_response(data)
        _assert_continuous_ts(ts_list)
        assert len(ts_list) == 30
        assert data["is_complete"] is True
        assert data["missing_count"] == 0

        h = r.headers
        assert h.get("X-Data-Repair") == "read_through"
        assert h.get("X-Data-Repair-Filled") == "1"
        assert h.get("X-Data-Missing-Minutes") == "0"

    print("✓ test_fills_single_gap OK")


def test_fills_multiple_gaps():
    """Store amb 3 gaps → Filled=3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        os.environ[ENABLE_READ_THROUGH_ENV] = "1"
        _setup_store_multiple_gaps(tmpdir, "XAUUSD")
        start_ts = int(BASE.timestamp())
        end_ts = int((BASE + timedelta(minutes=30)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")
            set_broker_deps(
                primary_backfill_provider=MockBackfillProvider(base_price=2700.0, seed=99),
                fallback_provider=None,
            )
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?limit=30&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        data = r.json()
        ts_list = _ts_list_from_response(data)
        _assert_continuous_ts(ts_list)
        assert len(ts_list) == 30

        h = r.headers
        assert h.get("X-Data-Repair") == "read_through"
        assert h.get("X-Data-Repair-Filled") == "3"

    print("✓ test_fills_multiple_gaps OK")


def test_guard_max_missing_blocks():
    """Gap 20 minuts, READ_THROUGH_MAX_MISSING_MINUTES=10 → no read-through."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        os.environ[ENABLE_READ_THROUGH_ENV] = "1"
        os.environ[READ_THROUGH_MAX_MISSING_ENV] = "10"
        _setup_store_large_gap(tmpdir, "XAUUSD")
        start_ts = int(BASE.timestamp())
        end_ts = int((BASE + timedelta(minutes=50)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")
            set_broker_deps(
                primary_backfill_provider=MockBackfillProvider(base_price=2700.0),
                fallback_provider=None,
            )
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?limit=50&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        data = r.json()
        assert data["missing_count"] == 20
        assert not data["is_complete"]

        h = r.headers
        assert h.get("X-Data-Repair") != "read_through"
        assert int(h.get("X-Data-Missing-Minutes", "0")) == 20

    print("✓ test_guard_max_missing_blocks OK")


def test_failure_returns_original():
    """Provider llança → body original, X-Data-Repair=read_through_failed, Filled=0."""

    class FailingProvider:
        async def fetch_ohlcv(self, symbol, start, end):
            raise ConnectionError("mock network error")

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        os.environ[ENABLE_READ_THROUGH_ENV] = "1"
        _setup_store_single_gap(tmpdir, "XAUUSD")
        start_ts = int(BASE.timestamp())
        end_ts = int((BASE + timedelta(minutes=30)).timestamp())

        app = create_app()
        with TestClient(app) as client:
            client.get("/")
            set_broker_deps(
                primary_backfill_provider=FailingProvider(),
                fallback_provider=None,
            )
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?limit=30&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200

        data = r.json()
        assert data["missing_count"] == 1
        assert not data["is_complete"]
        ts_list = _ts_list_from_response(data)
        assert len(ts_list) == 29

        h = r.headers
        assert h.get("X-Data-Repair") == "read_through_failed"
        assert h.get("X-Data-Repair-Filled") == "0"

    print("✓ test_failure_returns_original OK")


def test_does_not_mutate_store():
    """Read-through no escriu al store; snapshot abans/després igual."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        os.environ[ENABLE_READ_THROUGH_ENV] = "1"
        store, _ = _setup_store_single_gap(tmpdir, "XAUUSD")
        start_ts = int(BASE.timestamp())
        end_ts = int((BASE + timedelta(minutes=30)).timestamp())

        before = store.read_range(
            symbol="XAUUSD",
            start=BASE,
            end=BASE + timedelta(minutes=30),
            validate_gaps=False,
        )
        before_ts = sorted(int(c.timestamp.timestamp()) for c in before.candles)

        app = create_app()
        with TestClient(app) as client:
            client.get("/")
            set_broker_deps(
                primary_backfill_provider=MockBackfillProvider(base_price=2700.0, seed=42),
                fallback_provider=None,
            )
            r = client.get(
                f"/api/v1/broker/ohlcv/XAUUSD?limit=30&since={start_ts}&to={end_ts}"
            )
        assert r.status_code == 200
        data = r.json()
        assert len(_ts_list_from_response(data)) == 30

        after = store.read_range(
            symbol="XAUUSD",
            start=BASE,
            end=BASE + timedelta(minutes=30),
            validate_gaps=False,
        )
        after_ts = sorted(int(c.timestamp.timestamp()) for c in after.candles)
        assert before_ts == after_ts

    print("✓ test_does_not_mutate_store OK")


def main():
    print("=" * 60)
    print("P8.0b — Read-through wired to OHLCV (API, 0 network)")
    print("=" * 60)
    test_fills_single_gap()
    test_fills_multiple_gaps()
    test_guard_max_missing_blocks()
    test_failure_returns_original()
    test_does_not_mutate_store()
    print()
    print("✓ Tots els tests P8.0b passats (0 network)")


if __name__ == "__main__":
    main()
