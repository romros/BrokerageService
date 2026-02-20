#!/usr/bin/env python3
"""
Phase 19 — Tests 0-network per OHLCV Data API amb Parquet/DuckDB (rangs llargs, cursor next_ts).

Valida:
- GET /ohlcv/{symbol} → DuckDB path si existeix Parquet (no legacy)
- Resposta inclou next_ts per paginació cursor
- Paginació cursor: next_ts del resultat anterior → pàgina següent sense solapament
- Rang multi-mes: candles de múltiples mesos a un sol request
- next_ts=None quan s'han retornat totes les candles
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient
from domain.models import Candle
from infrastructure.storage.parquet_store import ParquetCandleStore


def _make_candles(symbol: str, year: int, month: int, count: int) -> list:
    base_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    return [
        Candle(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc),
            open=1.1 + i * 0.0001,
            high=1.2 + i * 0.0001,
            low=1.0 + i * 0.0001,
            close=1.15 + i * 0.0001,
            volume=float(100 + i),
            is_closed=True,
        )
        for i in range(count)
    ]


def _write_parquet(tmp_root: str, symbol: str, year: int, month: int, count: int) -> list:
    candles = _make_candles(symbol, year, month, count)
    store = ParquetCandleStore(root_path=tmp_root)
    store.write_month(symbol, year, month, candles)
    return candles


def _create_app(tmp_dir: str):
    os.environ["DATAFILES_ROOT"] = tmp_dir
    from application.app_factory import create_app
    return create_app(role="trading_service")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ohlcv_uses_duckdb_path_when_parquet_exists():
    """GET /ohlcv/{symbol} → DuckDB path quan existeix Parquet (source=historical_parquet)."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 10)
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/ohlcv/EURUSD")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "historical_parquet"
    assert len(data["candles"]) == 10
    assert "next_ts" in data
    print(f"✓ test_ohlcv_uses_duckdb_path_when_parquet_exists OK (candles={len(data['candles'])})")


def test_ohlcv_duckdb_returns_next_ts_for_pagination():
    """next_ts present al response; None quan no hi ha més candles."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 20)
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            # Amb limit=5 → next_ts no None
            resp = client.get("/api/v1/data/ohlcv/EURUSD?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candles"]) == 5
    assert data["next_ts"] is not None
    assert isinstance(data["next_ts"], int)
    print(f"✓ test_ohlcv_duckdb_returns_next_ts_for_pagination OK (next_ts={data['next_ts']})")


def test_ohlcv_duckdb_cursor_pagination_no_overlap():
    """Paginació cursor: 2 pàgines sense solapament ni buits."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 10)
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            # Primera pàgina: limit=4
            r1 = client.get("/api/v1/data/ohlcv/EURUSD?limit=4")
            assert r1.status_code == 200
            d1 = r1.json()
            assert len(d1["candles"]) == 4
            assert d1["next_ts"] is not None

            # Segona pàgina: cursor = next_ts anterior
            r2 = client.get(f"/api/v1/data/ohlcv/EURUSD?limit=4&next_ts={d1['next_ts']}")
            assert r2.status_code == 200
            d2 = r2.json()
            assert len(d2["candles"]) == 4

    # Cap solapament: timestamp de d2[0] >= next_ts de d1
    ts_page1 = [c[0] for c in d1["candles"]]
    ts_page2 = [c[0] for c in d2["candles"]]
    assert max(ts_page1) < min(ts_page2), "Solapament detectat entre pàgines"
    print(f"✓ test_ohlcv_duckdb_cursor_pagination_no_overlap OK")


def test_ohlcv_duckdb_multimonth_range():
    """Candles de múltiples mesos retornades en un sol request."""
    with tempfile.TemporaryDirectory() as tmp:
        # Escriure 2 mesos
        candles_jan = _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        candles_feb = _write_parquet(tmp, "EURUSD", 2020, 2, 5)
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/ohlcv/EURUSD?limit=100")
    assert resp.status_code == 200
    data = resp.json()
    # 10 candles totals (5 gen + 5 feb)
    assert len(data["candles"]) == 10, f"Esperat 10, obtingut {len(data['candles'])}"
    # Ordenades per timestamp
    ts_list = [c[0] for c in data["candles"]]
    assert ts_list == sorted(ts_list), "Candles no ordenades per timestamp"
    print(f"✓ test_ohlcv_duckdb_multimonth_range OK (candles={len(data['candles'])})")


def test_ohlcv_duckdb_last_page_next_ts_none():
    """Última pàgina → next_ts=None."""
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            # Demanem més del que hi ha → tot en una pàgina
            resp = client.get("/api/v1/data/ohlcv/EURUSD?limit=100")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candles"]) == 5
    assert data["next_ts"] is None, f"Esperava next_ts=None, obtingut {data['next_ts']}"
    print(f"✓ test_ohlcv_duckdb_last_page_next_ts_none OK")


def main():
    tests = [
        test_ohlcv_uses_duckdb_path_when_parquet_exists,
        test_ohlcv_duckdb_returns_next_ts_for_pagination,
        test_ohlcv_duckdb_cursor_pagination_no_overlap,
        test_ohlcv_duckdb_multimonth_range,
        test_ohlcv_duckdb_last_page_next_ts_none,
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
    print(f"\n✓ All Phase 19 OHLCV long-range Parquet tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
