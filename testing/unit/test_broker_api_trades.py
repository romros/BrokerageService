"""
Unit tests: Broker API GET /trades endpoint

Tests GET /api/v1/broker/trades amb mock adapter.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient

from application.main import create_app
from application.api.broker_routes import set_broker_deps
from domain.models import TradeFill, TradingPair, PriceData, Balance, OrderResult


def _make_mock_adapter_with_trades():
    """Adapter mock amb get_trade_history que retorna 2 trades."""
    adapter = AsyncMock()
    ts = datetime(2026, 2, 13, 12, 0, 0, tzinfo=timezone.utc)
    adapter.get_trade_history = AsyncMock(
        return_value=[
            TradeFill(
                trade_id="tx_1",
                symbol="ETH",
                side="buy",
                price=3950.0,
                size=0.5,
                fee=0.0,
                fee_currency="USDC",
                timestamp=ts,
                order_id="ord_1",
                position_id="lighter:0",
            ),
            TradeFill(
                trade_id="tx_2",
                symbol="ETH",
                side="sell",
                price=3960.0,
                size=0.5,
                fee=0.0,
                fee_currency="USDC",
                timestamp=ts,
                order_id="ord_2",
                position_id=None,
            ),
        ]
    )
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
        return_value=PriceData(symbol="ETH", bid=3950.0, ask=3950.5, mid=3950.25, timestamp=ts, is_market_open=True)
    )
    adapter.get_balance = AsyncMock(return_value=Balance(usdc=10000.0, native_token=0.1, available_margin=8000.0, used_margin=2000.0))
    adapter.get_open_positions = AsyncMock(return_value=[])
    adapter.open_position = AsyncMock(
        return_value=OrderResult(success=True, position_id="lighter:0", order_id="ord_1", executed_price=3950.0, executed_size=0.5, tx_hash="0xabc")
    )
    adapter.close_position = AsyncMock(return_value=True)
    return adapter


def test_broker_trades_200_with_adapter():
    """GET /api/v1/broker/trades?venue=lighter amb adapter → 200 + trades."""
    app = create_app()
    mock = _make_mock_adapter_with_trades()
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/trades?venue=lighter")
    assert r.status_code == 200
    data = r.json()
    assert "trades" in data
    assert len(data["trades"]) == 2
    assert data["trades"][0]["trade_id"] == "tx_1"
    assert data["trades"][0]["symbol"] == "ETH"
    assert data["trades"][0]["side"] == "buy"
    assert data["trades"][1]["side"] == "sell"
    print("✓ broker/trades 200 OK")


def test_broker_trades_503_without_adapter():
    """GET /api/v1/broker/trades sense adapter_factory → 503 + ADAPTER_NOT_AVAILABLE."""
    app = create_app()
    with TestClient(app) as client:
        client.get("/")
        set_broker_deps(adapter_factory=None)
        r = client.get("/api/v1/broker/trades?venue=lighter")
    assert r.status_code == 503
    data = r.json()
    assert data.get("code") == "ADAPTER_NOT_AVAILABLE"
    print("✓ broker/trades 503 ADAPTER_NOT_AVAILABLE OK")


def test_broker_trades_422_venue_not_configured():
    """GET /api/v1/broker/trades venue=gtrade quan només lighter → 422 + VENUE_NOT_CONFIGURED."""
    app = create_app()
    mock = _make_mock_adapter_with_trades()
    with TestClient(app) as client:
        client.get("/")
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/trades?venue=gtrade")
    assert r.status_code == 422
    data = r.json()
    assert data.get("code") == "VENUE_NOT_CONFIGURED"
    print("✓ broker/trades 422 VENUE_NOT_CONFIGURED OK")


def test_broker_trades_empty_list():
    """GET /api/v1/broker/trades amb adapter que retorna [] → 200 + trades=[]."""
    app = create_app()
    mock = _make_mock_adapter_with_trades()
    mock.get_trade_history = AsyncMock(return_value=[])
    with TestClient(app) as client:
        client.get("/")
        set_broker_deps(adapter_factory=lambda v: mock if v == "lighter" else None)
        r = client.get("/api/v1/broker/trades?venue=lighter")
    assert r.status_code == 200
    data = r.json()
    assert data["trades"] == []
    print("✓ broker/trades 200 empty OK")


def main():
    test_broker_trades_200_with_adapter()
    test_broker_trades_503_without_adapter()
    test_broker_trades_422_venue_not_configured()
    test_broker_trades_empty_list()
    print("\n✓ All broker API trades tests passed")


if __name__ == "__main__":
    main()
