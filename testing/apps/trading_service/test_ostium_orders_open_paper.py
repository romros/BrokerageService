#!/usr/bin/env python3
"""
T3 — Ostium orders/open PAPER (0-network).

Verifica que:
- POST /api/v1/broker/orders/open amb venue=ostium retorna 200 i position_id
- GET /api/v1/broker/positions?venue=ostium retorna la posició paper oberta

0-network: TestClient + FakeOstiumClient, sense Docker ni xarxa.
Execució: ./test.sh testing/apps/trading_service/test_ostium_orders_open_paper.py
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MODE"] = "paper"
os.environ["VENUE"] = "ostium"
os.environ["TRADING_CANARY_MODE"] = "ostium"  # effective_venue=ostium per usar l'adapter ostium

from fastapi.testclient import TestClient
from application.main import create_app
from application.api.broker_routes import set_broker_deps
from application.data.quality_gate import QualityGateResult
from infrastructure.venues.ostium.ostium_client import FakeOstiumClient
from infrastructure.venues.ostium.ostium_execution_adapter import OstiumExecutionAdapter


def _make_ok_gate_reader() -> MagicMock:
    """Reader que retorna gate=OK (per no bloquejar open)."""
    reader = MagicMock()
    now_ts = int(time.time())
    ok_gate = QualityGateResult(
        status="ok",
        reason="ok",
        quality_meta={
            "source": "primary",
            "freshness_sec": 30,
            "missing_minutes": 0,
            "max_gap_s": 0,
            "completeness": 1.0,
            "candles_count": 10,
        },
    )

    async def get_ohlcv_with_gate(**kwargs):
        return (
            {"candles": [{"ts": now_ts - i * 60, "o": 1.08, "h": 1.085, "l": 1.079, "c": 1.082, "v": 100} for i in range(10)]},
            {
                "X-Data-Coverage-From": str(now_ts - 3600),
                "X-Data-Coverage-To": str(now_ts - 30),
                "X-Data-Missing-Minutes": "0",
                "X-Data-Max-Gap-S": "0",
                "X-Data-Source": "primary",
            },
            ok_gate,
        )

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def test_ostium_paper_open_then_positions():
    """POST /orders/open venue=ostium (PAPER) → 202 + poll confirmed; GET /positions → 1 posició. T5.19 Fast-ACK."""
    app = create_app()
    ok_reader = _make_ok_gate_reader()
    fake_client = FakeOstiumClient(mid_price=1.085)
    ostium_adapter = OstiumExecutionAdapter(client=fake_client)

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=ok_reader,
            adapter_factory=lambda v: ostium_adapter if v == "ostium" else None,
            mode="paper",
            venue="ostium",
        )
        # Open — 202 Fast-ACK
        r_open = client.post(
            "/api/v1/broker/orders/open",
            json={
                "venue": "ostium",
                "symbol": "EURUSD",
                "side": "long",
                "collateral": 5.0,
                "leverage": 2.0,
            },
        )
        assert r_open.status_code == 202, r_open.json()
        data_open = r_open.json()
        assert data_open.get("success") is True and data_open.get("pending") is True
        operation_id = data_open.get("operation_id")
        assert operation_id
        position_id = ""
        # Poll fins confirmed
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{operation_id}")
            if r_op.status_code == 200:
                op = r_op.json()
                if op.get("status") == "confirmed":
                    position_id = op.get("position_id", "")
                    assert position_id and position_id.startswith("ostium:"), f"position_id={position_id}"
                    break
                if op.get("status") == "error":
                    raise AssertionError(f"Operation error: {op.get('error')}")
            time.sleep(0.05)
        else:
            raise AssertionError(f"Operation {operation_id} no confirmed")

        # Positions
        r_pos = client.get("/api/v1/broker/positions?venue=ostium")
        assert r_pos.status_code == 200, r_pos.json()
        data_pos = r_pos.json()
        assert "positions" in data_pos
        positions = data_pos["positions"]
        assert len(positions) == 1, f"expected 1 position, got {len(positions)}"
        assert positions[0].get("position_id") == position_id
        assert positions[0].get("symbol") == "EURUSD"
        assert positions[0].get("side") == "LONG"
        assert positions[0].get("collateral") == 5.0
        assert positions[0].get("leverage") == 2.0
        assert positions[0].get("notional") == 10.0

    print("✓ Ostium PAPER: open → position_id; GET positions → 1 posició OK")


if __name__ == "__main__":
    test_ostium_paper_open_then_positions()
