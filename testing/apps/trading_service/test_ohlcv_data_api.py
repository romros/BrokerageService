#!/usr/bin/env python3
"""
Phase 14 — Tests 0-network per OHLCV Data API (GET /api/v1/data/ohlcv/{symbol}).

Valida:
- symbol graduat → source=ostium_local
- symbol no graduat → source=dukascopy
- X-Data-* headers presents i coherents
- paginació: limit + offset + next_offset
- inputs invàlids → 422
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient
from domain.models import Candle


def _make_candles(symbol: str = "EURUSD", n: int = 20) -> list[Candle]:
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


def _create_app(tmp_dir: str):
    os.environ["DATAFILES_ROOT"] = tmp_dir
    from application.app_factory import create_app
    return create_app(role="trading_service")


def _mock_body_headers(candles: list[Candle], source: str):
    """Retorna (body_dict, headers_dict) com retornaria get_ohlcv_backtest."""
    body = {
        "symbol": candles[0].symbol if candles else "EURUSD",
        "timeframe": "1m",
        "count": len(candles),
        "candles": [
            {"ts": int(c.timestamp.timestamp()), "open": c.open, "high": c.high,
             "low": c.low, "close": c.close, "volume": c.volume}
            for c in candles
        ],
    }
    headers = {
        "X-Data-Source": source,
        "X-Data-Coverage-From": str(int(candles[0].timestamp.timestamp())) if candles else "0",
        "X-Data-Coverage-To": str(int(candles[-1].timestamp.timestamp()) + 60) if candles else "0",
        "X-Data-Missing-Minutes": "0",
        "X-Data-Max-Gap-S": "0",
    }
    return body, headers


def test_get_ohlcv_ostium_source():
    """Symbol graduat → source=ostium_local al response body."""
    candles = _make_candles("EURUSD", 20)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/EURUSD")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "ostium_local"
    assert data["symbol"] == "EURUSD"
    assert len(data["candles"]) == 20
    print(f"✓ test_get_ohlcv_ostium_source OK (candles={len(data['candles'])})")


def test_get_ohlcv_dukascopy_source():
    """Symbol no graduat → source=dukascopy."""
    candles = _make_candles("USDJPY", 10)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "dukascopy"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/USDJPY")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "dukascopy"
    print(f"✓ test_get_ohlcv_dukascopy_source OK")


def test_xdata_headers_present():
    """X-Data-* headers presents a la resposta."""
    candles = _make_candles("EURUSD", 5)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/EURUSD")
    assert resp.status_code == 200
    for h in ["x-data-source", "x-data-coverage-from", "x-data-coverage-to",
              "x-data-missing-minutes", "x-data-max-gap-s"]:
        assert h in resp.headers, f"Header absent: {h}"
    print(f"✓ test_xdata_headers_present OK")


def test_candles_format_array_of_arrays():
    """Format candles: [[ts, o, h, l, c, v], ...]"""
    candles = _make_candles("EURUSD", 3)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/EURUSD")
    data = resp.json()
    for row in data["candles"]:
        assert isinstance(row, list) and len(row) == 6, f"Format incorrecte: {row}"
        ts, o, h, l, c, v = row
        assert isinstance(ts, int) and ts > 0
        assert h >= o and h >= c
        assert l <= o and l <= c
    print(f"✓ test_candles_format_array_of_arrays OK")


def test_pagination_limit_offset():
    """limit + offset → next_offset coherent."""
    candles = _make_candles("EURUSD", 10)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                # Primera pàgina: limit=4, offset=0 → next_offset=4
                resp1 = client.get("/api/v1/data/ohlcv/EURUSD?limit=4&offset=0")
                assert resp1.status_code == 200
                d1 = resp1.json()
                assert len(d1["candles"]) == 4
                assert d1["next_offset"] == 4

                # Segona pàgina: limit=4, offset=4 → next_offset=8
                resp2 = client.get("/api/v1/data/ohlcv/EURUSD?limit=4&offset=4")
                d2 = resp2.json()
                assert len(d2["candles"]) == 4
                assert d2["next_offset"] == 8

                # Tercera pàgina: limit=4, offset=8 → 2 candles, next_offset=null
                resp3 = client.get("/api/v1/data/ohlcv/EURUSD?limit=4&offset=8")
                d3 = resp3.json()
                assert len(d3["candles"]) == 2
                assert d3["next_offset"] is None
    print(f"✓ test_pagination_limit_offset OK")


def test_invalid_symbol_returns_422():
    """Symbol invàlid → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/ohlcv/EU-RSD")
    assert resp.status_code == 422
    print(f"✓ test_invalid_symbol_returns_422 OK")


def test_invalid_timeframe_returns_422():
    """Timeframe no suportat → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/ohlcv/EURUSD?tf=5m")
    assert resp.status_code == 422
    print(f"✓ test_invalid_timeframe_returns_422 OK")


def test_from_ts_to_ts_range():
    """from_ts i to_ts passen correctament al provider."""
    candles = _make_candles("EURUSD", 5)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result) as m:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/EURUSD?from_ts=1700000000&to_ts=1700003600")
    assert resp.status_code == 200
    # Verificar que el mock ha estat cridat amb els timestamps correctes
    call_kwargs = m.call_args.kwargs
    assert int(call_kwargs["start"].timestamp()) == 1700000000
    assert int(call_kwargs["end"].timestamp()) == 1700003600
    print(f"✓ test_from_ts_to_ts_range OK")


def test_lowercase_symbol_normalized():
    """Symbol en minúscules → normalitzat a majúscules."""
    candles = _make_candles("EURUSD", 3)
    mock_result = AsyncMock(return_value=_mock_body_headers(candles, "ostium_local"))

    with tempfile.TemporaryDirectory() as tmpdir:
        app = _create_app(tmpdir)
        with patch("application.api.data_routes.get_ohlcv_backtest", mock_result):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/api/v1/data/ohlcv/eurusd")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "EURUSD"
    print(f"✓ test_lowercase_symbol_normalized OK")


def main():
    tests = [
        test_get_ohlcv_ostium_source,
        test_get_ohlcv_dukascopy_source,
        test_xdata_headers_present,
        test_candles_format_array_of_arrays,
        test_pagination_limit_offset,
        test_invalid_symbol_returns_422,
        test_invalid_timeframe_returns_422,
        test_from_ts_to_ts_range,
        test_lowercase_symbol_normalized,
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
    print(f"\n✓ All Phase 14 OHLCV Data API tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
