#!/usr/bin/env python3
"""
Phase 12 — Tests 0-network per Backtest API (POST /run + GET /runs + GET /runs/{run_id}).

Valida:
- GET  /api/v1/backtests/runs → llista run_ids (pot ser buit) — smoke gateway
- POST /api/v1/backtests/run → retorna run_id + KPIs + source
- GET  /api/v1/backtests/runs/{run_id} → retorna el mateix payload
- Artifact JSON escrit al disc
- Inputs invàlids → 422 amb error_code
- run_id inexistent → 404

Fixtures: generades en tempdir; runner usa dukascopy_override (0-network).
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Forçar mode backtest per evitar lifespan adapter
os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient
from domain.models import Candle
from application.api.error_codes import BACKTEST_NOT_FOUND, BACKTEST_INVALID_PARAMS


def _make_candles(symbol: str = "EURUSD", n: int = 60) -> list[Candle]:
    """Candles fictícies per substituir Dukascopy i Ostium (0-network)."""
    base_ts = int(datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    candles = []
    for i in range(n):
        ts = datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc)
        o = 1.0500 + (i % 8) * 0.0001
        candles.append(Candle(
            symbol=symbol, timestamp=ts,
            open=o, high=o + 0.0005, low=o - 0.0005, close=o + 0.0002, volume=0,
        ))
    return candles


def _create_app_with_temp_dir(tmp_dir: str):
    """Crea app factory amb DATAFILES_ROOT apuntant a un tempdir."""
    os.environ["DATAFILES_ROOT"] = tmp_dir
    from application.app_factory import create_app
    return create_app(role="trading_service")


def test_list_runs_empty():
    """GET /runs retorna 200 amb runs=[] quan no hi ha artifacts (smoke gateway)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        from application.app_factory import create_app
        app = create_app(role="trading_service")
        with TestClient(app) as client:
            resp = client.get("/api/v1/backtests/runs")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "runs" in data
        assert data["runs"] == []
        print("✓ test_list_runs_empty OK")


def test_post_run_returns_run_id():
    """POST /run retorna 200 amb run_id, symbol, kpis i x_data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Patch get_ohlcv_backtest per retornar candles 0-network
        candles = _make_candles("EURUSD", n=60)

        async def mock_get_ohlcv(symbol, start, end, datafiles_root, **kwargs):
            from application.data.backtest_market_data import _candles_to_body, _compute_xdata_headers
            body = _candles_to_body(symbol, candles)
            headers = _compute_xdata_headers(candles, "ostium_local", start, end)
            return body, headers

        with patch("application.tools.run_backtest.get_ohlcv_backtest", side_effect=mock_get_ohlcv):
            app = _create_app_with_temp_dir(tmpdir)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post("/api/v1/backtests/run", json={
                    "symbol": "EURUSD",
                    "days": 1,
                    "strategy": "simple_trend",
                })

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "run_id" in data, f"Missing run_id: {data}"
        assert data["symbol"] == "EURUSD"
        assert data["status"] == "completed"
        assert "kpis" in data
        assert "x_data" in data
        assert data["x_data"]["source"] == "ostium_local"
        assert "trades_count" in data["kpis"]
        assert "artifact_id" in data
        print(f"✓ test_post_run_returns_run_id OK (run_id={data['run_id']}, trades={data['kpis']['trades_count']})")


def test_get_run_returns_same_payload():
    """GET /runs/{run_id} retorna el mateix payload del POST."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candles = _make_candles("XAUUSD", n=50)

        async def mock_get_ohlcv(symbol, start, end, datafiles_root, **kwargs):
            from application.data.backtest_market_data import _candles_to_body, _compute_xdata_headers
            body = _candles_to_body(symbol, candles)
            headers = _compute_xdata_headers(candles, "ostium_local", start, end)
            return body, headers

        with patch("application.tools.run_backtest.get_ohlcv_backtest", side_effect=mock_get_ohlcv):
            app = _create_app_with_temp_dir(tmpdir)
            with TestClient(app, raise_server_exceptions=True) as client:
                # POST
                post_resp = client.post("/api/v1/backtests/run", json={
                    "symbol": "XAUUSD",
                    "days": 1,
                })
                assert post_resp.status_code == 200, post_resp.text
                run_id = post_resp.json()["run_id"]

                # GET
                get_resp = client.get(f"/api/v1/backtests/runs/{run_id}")

        assert get_resp.status_code == 200, f"GET status {get_resp.status_code}: {get_resp.text}"
        get_data = get_resp.json()
        assert get_data["run_id"] == run_id
        assert get_data["symbol"] == "XAUUSD"
        assert get_data["status"] == "completed"
        assert "kpis" in get_data
        assert "trades_sample" in get_data
        print(f"✓ test_get_run_returns_same_payload OK (run_id={run_id})")


def test_artifact_written_to_disc():
    """Artifact JSON escrit a datafiles/backtests/ i recuperable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candles = _make_candles("EURUSD", n=30)

        async def mock_get_ohlcv(symbol, start, end, datafiles_root, **kwargs):
            from application.data.backtest_market_data import _candles_to_body, _compute_xdata_headers
            body = _candles_to_body(symbol, candles)
            headers = _compute_xdata_headers(candles, "dukascopy", start, end)
            return body, headers

        with patch("application.tools.run_backtest.get_ohlcv_backtest", side_effect=mock_get_ohlcv):
            app = _create_app_with_temp_dir(tmpdir)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post("/api/v1/backtests/run", json={"symbol": "EURUSD", "days": 1})
                assert resp.status_code == 200
                run_id = resp.json()["run_id"]

        # Verificar artifact al disc
        backtests_dir = Path(tmpdir) / "backtests"
        artifacts = list(backtests_dir.glob(f"{run_id}_*.json"))
        assert len(artifacts) == 1, f"Expected 1 artifact, found {artifacts}"
        artifact_data = json.loads(artifacts[0].read_text())
        assert artifact_data["run_ts"] == run_id
        assert artifact_data["phase"] == "Phase11_backtest_offline"
        print(f"✓ test_artifact_written_to_disc OK ({artifacts[0].name})")


def test_invalid_symbol_returns_422():
    """Símbol invàlid → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app_with_temp_dir(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/backtests/run", json={"symbol": "!INVALID!", "days": 1})
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        print("✓ test_invalid_symbol_returns_422 OK")


def test_invalid_strategy_returns_422():
    """Estratègia no suportada → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app_with_temp_dir(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/backtests/run", json={
                "symbol": "EURUSD", "days": 1, "strategy": "nonexistent_strategy"
            })
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        print("✓ test_invalid_strategy_returns_422 OK")


def test_invalid_days_returns_422():
    """days <= 0 → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app_with_temp_dir(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/api/v1/backtests/run", json={"symbol": "EURUSD", "days": -1})
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
        print("✓ test_invalid_days_returns_422 OK")


def test_get_nonexistent_run_returns_404():
    """run_id inexistent → 404 BACKTEST_NOT_FOUND."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app_with_temp_dir(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/backtests/runs/20260101_000000")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        body = resp.json()
        assert body.get("code") == BACKTEST_NOT_FOUND
        print("✓ test_get_nonexistent_run_returns_404 OK")


def test_post_run_lowercase_symbol_normalized():
    """Símbol en minúscules → normalitzat a majúscules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candles = _make_candles("EURUSD", n=20)

        async def mock_get_ohlcv(symbol, start, end, datafiles_root, **kwargs):
            from application.data.backtest_market_data import _candles_to_body, _compute_xdata_headers
            body = _candles_to_body(symbol, candles)
            headers = _compute_xdata_headers(candles, "dukascopy", start, end)
            return body, headers

        with patch("application.tools.run_backtest.get_ohlcv_backtest", side_effect=mock_get_ohlcv):
            app = _create_app_with_temp_dir(tmpdir)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post("/api/v1/backtests/run", json={"symbol": "eurusd", "days": 1})

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "EURUSD"
        print("✓ test_post_run_lowercase_symbol_normalized OK")


def main() -> int:
    test_list_runs_empty()
    test_post_run_returns_run_id()
    test_get_run_returns_same_payload()
    test_artifact_written_to_disc()
    test_invalid_symbol_returns_422()
    test_invalid_strategy_returns_422()
    test_invalid_days_returns_422()
    test_get_nonexistent_run_returns_404()
    test_post_run_lowercase_symbol_normalized()
    print("\n✓ All Phase 12 backtest API tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
