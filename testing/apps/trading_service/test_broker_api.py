"""
Unit tests: Broker API endpoints

Tests /api/v1/broker/* amb mock adapter.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Evitar paper execution (requereix Lighter) — lifespan usa else branch
os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient

from application.main import create_app
from application.api.broker_routes import set_broker_deps
from application.api.error_codes import OSTIUM_POSITIONS_TIMEOUT
from foundation.config.constants import OSTIUM_POSITIONS_TIMEOUT_S
from domain.models import (
    TradingPair,
    PriceData,
    Balance,
    Position,
    OrderResult,
)


def _make_mock_adapter():
    """Adapter mock per tests."""
    adapter = AsyncMock()
    adapter.get_pairs = AsyncMock(
        return_value=[
            TradingPair(
                pair_id=0,
                symbol="ETH",
                base="ETH",
                quote="USDC",
                min_leverage=1.0,
                max_leverage=50.0,
                maker_fee_percent=0.0,
                taker_fee_percent=0.0,
            )
        ]
    )
    adapter.get_latest_price = AsyncMock(
        return_value=PriceData(
            symbol="ETH",
            bid=3950.0,
            ask=3950.5,
            mid=3950.25,
            timestamp=datetime.now(timezone.utc),
        )
    )
    adapter.get_balance = AsyncMock(
        return_value=Balance(
            usdc=10000.0,
            native_token=0.1,
            available_margin=8000.0,
            used_margin=2000.0,
        )
    )
    adapter.get_open_positions = AsyncMock(return_value=[])
    adapter.open_position = AsyncMock(
        return_value=OrderResult(
            success=True,
            position_id="lighter:0",
            order_id="ord_1",
            executed_price=3950.0,
            executed_size=0.5,
            tx_hash="0xabc",
        )
    )
    adapter.close_position = AsyncMock(return_value=True)
    return adapter


def test_broker_venues_empty_when_no_adapter():
    """GET /api/v1/broker/venues sense adapter_factory → []."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/venues")
    assert r.status_code == 200
    data = r.json()
    assert "venues" in data
    assert data["venues"] == []
    print("✓ broker/venues [] (no adapter) OK")


def test_broker_venues_reflects_availability():
    """GET /api/v1/broker/venues amb adapter lighter → ['lighter']."""
    app = create_app()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        mock = _make_mock_adapter()
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/venues")
    assert r.status_code == 200
    data = r.json()
    assert data["venues"] == ["lighter"]
    print("✓ broker/venues reflects ['lighter'] OK")


def test_broker_pairs_503_without_adapter():
    """GET /api/v1/broker/pairs sense adapter_factory → 503 + code=ADAPTER_NOT_AVAILABLE."""
    app = create_app()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan (adapter_factory=None per defecte)
        set_broker_deps(adapter_factory=None)  # assegura None
        r = client.get("/api/v1/broker/pairs?venue=lighter")
    assert r.status_code == 503
    data = r.json()
    assert data.get("code") == "ADAPTER_NOT_AVAILABLE"
    assert "adapter_factory not configured" in data.get("detail", "")
    print("✓ broker/pairs 503 + ADAPTER_NOT_AVAILABLE OK")


def test_broker_pairs_422_venue_not_configured():
    """GET /api/v1/broker/pairs venue=gtrade quan només hi ha lighter → 422 + VENUE_NOT_CONFIGURED."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/pairs?venue=gtrade")
    assert r.status_code == 422
    data = r.json()
    assert data.get("code") == "VENUE_NOT_CONFIGURED"
    assert "venue not configured" in data.get("detail", "")
    print("✓ broker/pairs 422 VENUE_NOT_CONFIGURED OK")


def test_broker_pairs_ok_with_adapter():
    """GET /api/v1/broker/pairs amb adapter → 200."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/pairs?venue=lighter")
    assert r.status_code == 200
    data = r.json()
    assert "pairs" in data
    assert len(data["pairs"]) >= 1
    assert data["pairs"][0]["symbol"] == "ETH"
    print("✓ broker/pairs OK")


def test_broker_price_latest_ok():
    """GET /api/v1/broker/price/latest amb adapter → 200."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/price/latest?venue=lighter&symbol=ETH")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "ETH"
    assert data["bid"] == 3950.0
    assert data["ask"] == 3950.5
    assert data["mid"] == 3950.25
    print("✓ broker/price/latest OK")


def test_broker_balance_ok():
    """GET /api/v1/broker/balance amb adapter → 200."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/balance?venue=lighter")
    assert r.status_code == 200
    data = r.json()
    assert data["usdc"] == 10000.0
    assert data["available_margin"] == 8000.0
    print("✓ broker/balance OK")


def test_broker_positions_ok():
    """GET /api/v1/broker/positions amb adapter → 200."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/positions?venue=lighter")
    assert r.status_code == 200
    data = r.json()
    assert "positions" in data
    assert data["positions"] == []
    print("✓ broker/positions OK")


def test_broker_positions_ostium_live_timeout_504():
    """T5.5: GET /positions venue=ostium MODE=live amb adapter que no retorna → 504 en ~5s."""
    async def hang():
        await asyncio.sleep(999)

    app = create_app()
    mock = _make_mock_adapter()
    mock.get_open_positions = AsyncMock(side_effect=hang)
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(
            adapter_factory=lambda v: mock if v == "ostium" else None,
            mode="live",
            venue="ostium",
        )
        t0 = time.monotonic()
        r = client.get("/api/v1/broker/positions?venue=ostium")
        elapsed = time.monotonic() - t0
    assert r.status_code == 504, f"Expected 504, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("error") == OSTIUM_POSITIONS_TIMEOUT
    assert data.get("timeout_s") == OSTIUM_POSITIONS_TIMEOUT_S
    assert 4 <= elapsed <= 8, f"Expected ~5s timeout, got {elapsed:.1f}s"
    print("✓ broker/positions ostium LIVE timeout 504 OK")


def test_broker_orders_open_canonical_body():
    """POST /api/v1/broker/orders/open amb JSON body (canònic) → 202 + poll confirmed. T5.19 Fast-ACK."""
    import time
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.post(
            "/api/v1/broker/orders/open",
            json={
                "venue": "lighter",
                "symbol": "ETH",
                "side": "long",
                "collateral": 100,
                "leverage": 20,
            },
        )
        assert r.status_code == 202, f"Expected 202 Fast-ACK, got {r.status_code}: {r.text}"
        data = r.json()
        assert data["success"] is True and data.get("pending") is True
        operation_id = data.get("operation_id")
        assert operation_id, "operation_id required for poll"
        # Poll fins confirmed (background task corre en següent request)
        for _ in range(50):
            r2 = client.get(f"/api/v1/broker/operations/{operation_id}")
            if r2.status_code == 200:
                op = r2.json()
                if op.get("status") == "confirmed":
                    assert op.get("position_id") == "lighter:0"
                    print("✓ broker/orders/open (body) OK — 202 + poll confirmed")
                    return
                if op.get("status") == "error":
                    raise AssertionError(f"Operation error: {op.get('error')}")
            time.sleep(0.05)
    raise AssertionError(f"Operation {operation_id} no confirmed en 2.5s")


def test_broker_health_200():
    """GET /api/v1/broker/health retorna 200."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    print("✓ broker/health 200 OK")


def test_broker_candles_200():
    """GET /api/v1/broker/candles?symbol=ETH&timeframe=1m&limit=10 retorna 200."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/candles?symbol=ETH&timeframe=1m&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert "candles" in data
    assert data.get("timeframe") == "1m"
    print("✓ broker/candles 200 OK")


def test_broker_candles_timeframe_422():
    """GET /api/v1/broker/candles?...timeframe=5m retorna 422 + code=TIMEFRAME_NOT_SUPPORTED."""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/candles?symbol=ETH&timeframe=5m&limit=10")
    assert r.status_code == 422
    data = r.json()
    assert data.get("code") == "TIMEFRAME_NOT_SUPPORTED"
    print("✓ broker/candles 422 TIMEFRAME_NOT_SUPPORTED OK")


def test_broker_orders_open_side_invalid_422():
    """POST /api/v1/broker/orders/open amb side=foo (body) → 422 + code=INVALID_SIDE."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.post(
            "/api/v1/broker/orders/open",
            json={
                "venue": "lighter",
                "symbol": "ETH",
                "side": "foo",
                "collateral": 100,
                "leverage": 20,
            },
        )
    assert r.status_code == 422
    data = r.json()
    detail = data.get("detail", "")
    if isinstance(detail, list):
        msg = " ".join(str(d.get("msg", "")) for d in detail if isinstance(d, dict))
    else:
        msg = str(detail)
    assert data.get("code") == "INVALID_SIDE" or "side" in msg.lower()
    print("✓ broker/orders/open 422 INVALID_SIDE OK")


def test_broker_orders_close_canonical_body():
    """POST /api/v1/broker/orders/close amb JSON body (canònic) → 200."""
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.post(
            "/api/v1/broker/orders/close",
            json={"venue": "lighter", "position_id": "lighter:0", "percent": 100},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    print("✓ broker/orders/close (body) OK")


def test_broker_operations_get():
    """T5.14: GET /operations/{id} retorna operation després d'open. T5.19: 202 + poll confirmed."""
    import time
    app = create_app()
    mock = _make_mock_adapter()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.post(
            "/api/v1/broker/orders/open",
            json={
                "venue": "lighter",
                "symbol": "ETH",
                "side": "long",
                "collateral": 100,
                "leverage": 20,
            },
        )
        assert r.status_code == 202
        data = r.json()
        op_id = data.get("operation_id")
        assert op_id, f"expected operation_id in response: {data}"
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{op_id}")
            if r_op.status_code == 200:
                op = r_op.json()
                if op.get("status") == "confirmed":
                    assert op.get("operation_id") == op_id
                    assert op.get("kind") == "open"
                    assert op.get("venue") == "lighter"
                    assert op.get("symbol") == "ETH"
                    assert op.get("position_id") == "lighter:0"
                    print("✓ broker/operations/{id} OK")
                    return
            time.sleep(0.05)
    raise AssertionError(f"Operation {op_id} no confirmed")


def main():
    test_broker_health_200()
    test_broker_venues_empty_when_no_adapter()
    test_broker_venues_reflects_availability()
    test_broker_pairs_503_without_adapter()
    test_broker_pairs_422_venue_not_configured()
    test_broker_pairs_ok_with_adapter()
    test_broker_candles_200()
    test_broker_candles_timeframe_422()
    test_broker_price_latest_ok()
    test_broker_balance_ok()
    test_broker_positions_ok()
    test_broker_positions_ostium_live_timeout_504()
    test_broker_orders_open_canonical_body()
    test_broker_orders_open_side_invalid_422()
    test_broker_orders_close_canonical_body()
    test_broker_operations_get()
    print("\n✓ All Broker API unit tests passed")


if __name__ == "__main__":
    main()
