#!/usr/bin/env python3
"""
Split vNext Phase 1 — Service role wiring tests (0-network)

- realtime_datalayer: només data routes (health, data_status, ohlcv, candles); sense trading
- trading_service: data + trading; sense ingest/writer
- entrypoints: import sense side-effects
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _get_route_paths(app) -> set[str]:
    """Extreu paths de les rutes de l'app via OpenAPI."""
    openapi = app.openapi()
    return set(openapi.get("paths", {}).keys())


def test_service_role_wiring_realtime_only_starts_datalayer():
    """Realtime_datalayer: té data routes (health, data_status, ohlcv); NO té trading (orders)."""
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    paths = _get_route_paths(app)

    assert any("/health" in p for p in paths), f"realtime ha de tenir health: {paths}"
    assert any("data_status" in p for p in paths)
    assert any("ohlcv" in p for p in paths)
    assert any("candles" in p for p in paths)

    orders_paths = [p for p in paths if "orders" in p]
    assert len(orders_paths) == 0, f"realtime_datalayer no ha d'exposar /orders: {paths}"
    print("OK test_service_role_wiring_realtime_only_starts_datalayer")


def test_service_role_wiring_trading_does_not_start_ingest_or_writer():
    """Trading_service: té trading routes; _role_starts_ostium_ingest(trading)=False."""
    from application.app_factory import (
        _role_starts_ostium_ingest,
        _role_starts_ingest_or_writer,
        create_app,
    )

    assert _role_starts_ostium_ingest("trading_service") is False
    assert _role_starts_ingest_or_writer("trading_service") is False

    app = create_app(role="trading_service")
    paths = _get_route_paths(app)
    assert any("orders" in p for p in paths), f"trading_service ha d'exposar /orders: {paths}"
    assert any("balance" in p for p in paths)
    print("OK test_service_role_wiring_trading_does_not_start_ingest_or_writer")


def test_split_entrypoints_import():
    """Import dels 3 entrypoints sense side-effects (no arrenca server)."""
    from apps.realtime_datalayer.app import app as app_realtime
    from apps.historical_datalayer.app import app as app_historical
    from apps.trading_service.app import app as app_trading

    assert app_realtime is not None
    assert app_historical is not None
    assert app_trading is not None
    assert app_realtime.title == "BrokerageService"
    print("OK test_split_entrypoints_import")


def main() -> int:
    test_service_role_wiring_realtime_only_starts_datalayer()
    test_service_role_wiring_trading_does_not_start_ingest_or_writer()
    test_split_entrypoints_import()
    print("✓ All service role wiring tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
