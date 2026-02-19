#!/usr/bin/env python3
"""Realtime DataLayer — closed no penalitza health (0-network)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.data_layer_lifecycle import set_data_layer_status, DATA_LAYER_READY
from application.data.data_layer_metrics import get_data_layer_metrics
from application.app_factory import create_app
from fastapi.testclient import TestClient


def test_closed_symbol_not_degraded():
    """Quan tots els símbols OPEN són ACTIVE, health=ok encara que hi hagi closed DEGRADED."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/symbols")
        set_data_layer_status(DATA_LAYER_READY)
        metrics = get_data_layer_metrics()
        if metrics:
            m = metrics._get_or_create("XAUUSD")
            m.market_open = False
            m.symbol_state = "DEGRADED"
            m = metrics._get_or_create("EURUSD")
            m.market_open = True
            m.symbol_state = "ACTIVE"
        r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    print("✓ test_closed_symbol_not_degraded passed")


def main() -> int:
    test_closed_symbol_not_degraded()
    print("OK test_closed_does_not_degrade_health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
