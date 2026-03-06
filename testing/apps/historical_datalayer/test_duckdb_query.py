#!/usr/bin/env python3
"""
Phase 16 — Tests 0-network per DuckDBQueryService + routing a data_routes.

Valida:
- has_data() false si no hi ha Parquet
- has_data() true després d'escriure
- query_ohlcv() retorna candles correctes des de Parquet
- filtre from_ts funciona
- paginació next_ts funciona
- última pàgina retorna next_ts=None
- compute_xdata_headers() retorna camps X-Data-*
- GET /ohlcv/{symbol} → routing DuckDB si existeix Parquet
- GET /ohlcv/{symbol} → routing legacy si no hi ha Parquet
"""

import sys
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from infrastructure.storage.parquet_store import ParquetCandleStore
from infrastructure.query.duckdb_query_service import DuckDBQueryService


def _make_candles(symbol: str, base_ts: int, count: int) -> list:
    return [
        Candle(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc),
            open=1.1 + i * 0.001,
            high=1.2 + i * 0.001,
            low=1.0 + i * 0.001,
            close=1.15 + i * 0.001,
            volume=float(100 + i),
            is_closed=True,
        )
        for i in range(count)
    ]


def _write_parquet(tmp_root: str, symbol: str, year: int, month: int, count: int) -> list:
    """Escriu parquet al path ticks (T9.19: DuckDB llegeix de historical_parquet_ticks_v1)."""
    base_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    candles = _make_candles(symbol, base_ts, count)
    from infrastructure.storage import parquet_store
    with patch.object(parquet_store, "PARQUET_SUBDIR", "historical_parquet_ticks_v1"):
        store = ParquetCandleStore(root_path=tmp_root)
        store.write_month(symbol, year, month, candles)
    return candles


# ---------------------------------------------------------------------------
# Tests DuckDBQueryService
# ---------------------------------------------------------------------------

def test_has_data_false_when_no_parquet():
    with tempfile.TemporaryDirectory() as tmp:
        svc = DuckDBQueryService(root_path=tmp)
        assert svc.has_data("EURUSD") is False
    print("✓ test_has_data_false_when_no_parquet OK")


def test_has_data_true_after_write():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 10)
        svc = DuckDBQueryService(root_path=tmp)
        assert svc.has_data("EURUSD") is True
    print("✓ test_has_data_true_after_write OK")


def test_query_ohlcv_returns_correct_candles():
    with tempfile.TemporaryDirectory() as tmp:
        candles = _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        svc = DuckDBQueryService(root_path=tmp)
        result = svc.query_ohlcv("EURUSD")
        assert result["source"] == "dukascopy"
        assert len(result["candles"]) == 5
        first = result["candles"][0]
        assert len(first) == 6
        assert first[0] == int(candles[0].timestamp.timestamp())
    print("✓ test_query_ohlcv_returns_correct_candles OK")


def test_query_ohlcv_from_ts_filter():
    with tempfile.TemporaryDirectory() as tmp:
        candles = _write_parquet(tmp, "EURUSD", 2020, 1, 10)
        base_ts = int(candles[0].timestamp.timestamp())
        from_ts = base_ts + 5 * 60  # des de la candle índex 5
        svc = DuckDBQueryService(root_path=tmp)
        result = svc.query_ohlcv("EURUSD", from_ts=from_ts)
        assert len(result["candles"]) == 5
        assert result["candles"][0][0] == from_ts
    print("✓ test_query_ohlcv_from_ts_filter OK")


def test_query_ohlcv_pagination_next_ts():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 10)
        svc = DuckDBQueryService(root_path=tmp)
        result = svc.query_ohlcv("EURUSD", limit=3)
        # 10 candles, limit=3 → next_ts != None
        assert result["next_ts"] is not None, "Esperava next_ts != None"
        assert len(result["candles"]) == 3
        # Pàgina 2 via next_ts
        result2 = svc.query_ohlcv("EURUSD", next_ts=result["next_ts"], limit=3)
        assert len(result2["candles"]) == 3
        # No hi ha solapament
        assert result2["candles"][0][0] > result["candles"][-1][0]
    print("✓ test_query_ohlcv_pagination_next_ts OK")


def test_query_ohlcv_last_page_next_ts_none():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        svc = DuckDBQueryService(root_path=tmp)
        result = svc.query_ohlcv("EURUSD", limit=10)
        assert result["next_ts"] is None
        assert len(result["candles"]) == 5
    print("✓ test_query_ohlcv_last_page_next_ts_none OK")


def test_compute_xdata_headers_structure():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        svc = DuckDBQueryService(root_path=tmp)
        result = svc.query_ohlcv("EURUSD")
        headers = svc.compute_xdata_headers("EURUSD", result["candles"], None, None)
        assert "X-Data-Source" in headers
        assert "X-Data-Coverage-From" in headers
        assert "X-Data-Coverage-To" in headers
        assert "X-Data-Missing-Minutes" in headers
        assert "X-Data-Max-Gap-S" in headers
        assert headers["X-Data-Source"] == "dukascopy"
    print("✓ test_compute_xdata_headers_structure OK")


# ---------------------------------------------------------------------------
# Tests routing a data_routes via FastAPI TestClient
# ---------------------------------------------------------------------------

def _make_app():
    from application.app_factory import create_app
    return create_app(role="trading_service")


def test_data_routes_uses_duckdb_when_parquet_exists():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        from fastapi.testclient import TestClient
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        with patch.dict(os.environ, {"DATAFILES_ROOT": tmp}):
            resp = client.get("/api/v1/data/ohlcv/EURUSD")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["source"] == "dukascopy", f"Source: {body.get('source')}"
        assert isinstance(body["candles"], list)
        assert len(body["candles"]) == 5
        assert "next_ts" in body
    print("✓ test_data_routes_uses_duckdb_when_parquet_exists OK")


def test_data_routes_legacy_when_no_parquet():
    with tempfile.TemporaryDirectory() as tmp:
        fake_body = {
            "candles": [
                {"ts": 1577836800, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 100.0},
            ],
            "source": "ostium_local",
        }
        fake_headers = {
            "X-Data-Source": "ostium_local",
            "X-Data-Coverage-From": "1577836800",
            "X-Data-Coverage-To": "1577836860",
        }
        from fastapi.testclient import TestClient
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        with patch("application.api.data_routes.get_ohlcv_backtest", new=AsyncMock(return_value=(fake_body, fake_headers))):
            with patch.dict(os.environ, {"DATAFILES_ROOT": tmp}):
                resp = client.get("/api/v1/data/ohlcv/EURUSD?from_ts=1577836800&to_ts=1577836860")
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["source"] == "ostium_local", f"Source: {body.get('source')}"
        assert "next_offset" in body
    print("✓ test_data_routes_legacy_when_no_parquet OK")


def main():
    tests = [
        test_has_data_false_when_no_parquet,
        test_has_data_true_after_write,
        test_query_ohlcv_returns_correct_candles,
        test_query_ohlcv_from_ts_filter,
        test_query_ohlcv_pagination_next_ts,
        test_query_ohlcv_last_page_next_ts_none,
        test_compute_xdata_headers_structure,
        test_data_routes_uses_duckdb_when_parquet_exists,
        test_data_routes_legacy_when_no_parquet,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        sys.exit(1)
    print(f"\n✓ All Phase 16 DuckDB tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
