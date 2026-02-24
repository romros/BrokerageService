#!/usr/bin/env python3
"""
Split vNext Phase 5 — Quality Gate enforçat al trading loop (0-network).

Verifica que POST /orders/open aplica el quality gate fail-closed:
- gate=BAD → 422 DATA_QUALITY_GATE_BAD (cap executor cridat)
- gate=OK → execució continua fins al venue adapter
- sense data_layer_reader → gate no s'aplica (backward compat)
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Evitar paper execution (requereix Lighter) — lifespan usa else branch
os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient
from application.main import create_app
from application.api.broker_routes import set_broker_deps
from application.data.quality_gate import QualityGateResult


def _make_bad_gate_reader(symbol: str = "EURUSD") -> MagicMock:
    """Reader mock que retorna gate=BAD."""
    reader = MagicMock()
    bad_gate = QualityGateResult(
        status="bad",
        reason="missing_headers",
        quality_meta={"error": "X-Data-Coverage-From absent"},
    )

    async def get_ohlcv_with_gate(**kwargs):
        return {}, {}, bad_gate

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def _make_ok_gate_reader() -> MagicMock:
    """Reader mock que retorna gate=OK."""
    reader = MagicMock()
    import time
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
        return {"candles": []}, {
            "X-Data-Coverage-From": str(now_ts - 3600),
            "X-Data-Coverage-To": str(now_ts - 30),
            "X-Data-Missing-Minutes": "0",
            "X-Data-Max-Gap-S": "0",
            "X-Data-Source": "primary",
        }, ok_gate

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def test_quality_gate_bad_blocks_order_open():
    """gate=BAD → 202 Fast-ACK, operation acaba en error. T5.19: gate corre en background."""
    import time
    app = create_app()

    mock_adapter = AsyncMock()
    mock_adapter.open_position = AsyncMock()

    bad_reader = _make_bad_gate_reader("EURUSD")

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=bad_reader,
            adapter_factory=lambda venue: mock_adapter,
            mode="paper",
            venue="paper",
        )
        r = client.post("/api/v1/broker/orders/open", json={
            "venue": "paper",
            "symbol": "EURUSD",
            "side": "long",
            "collateral": 100.0,
            "leverage": 2.0,
        })

        assert r.status_code == 202, f"Expected 202 Fast-ACK, got {r.status_code}: {r.text}"
        data = r.json()
        op_id = data.get("operation_id")
        assert op_id
        # Poll fins error (gate corre en background; següent request executa el task)
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{op_id}")
            if r_op.status_code == 200:
                op = r_op.json()
                if op.get("status") == "error":
                    assert "DATA_QUALITY_GATE_BAD" in str(op.get("error", "")), op
                    assert not mock_adapter.open_position.called
                    print(f"✓ test_quality_gate_bad_blocks_order_open passed")
                    return
            time.sleep(0.05)
    raise AssertionError(f"Operation {op_id} no va a error")


def test_quality_gate_bad_does_not_call_venue():
    """gate=BAD → venue adapter.open_position() NO és cridat mai. T5.19: 202 + poll error."""
    import time
    app = create_app()

    mock_adapter = AsyncMock()
    mock_adapter.open_position = AsyncMock(return_value=MagicMock(
        success=True, position_id="paper:1", order_id="o1",
        executed_price=1.08, executed_size=100.0,
    ))

    bad_reader = _make_bad_gate_reader("XAUUSD")

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=bad_reader,
            adapter_factory=lambda venue: mock_adapter,
            mode="paper",
            venue="paper",
        )
        r = client.post("/api/v1/broker/orders/open", json={
            "venue": "paper",
            "symbol": "XAUUSD",
            "side": "short",
            "collateral": 50.0,
            "leverage": 1.0,
        })
        assert r.status_code == 202
        op_id = r.json().get("operation_id")
        assert op_id
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{op_id}")
            if r_op.status_code == 200 and r_op.json().get("status") == "error":
                break
            time.sleep(0.05)

    assert not mock_adapter.open_position.called, "open_position NO s'ha de cridar quan gate=BAD"
    print("✓ test_quality_gate_bad_does_not_call_venue passed")


def test_quality_gate_ok_allows_order_open():
    """gate=OK → 202 + poll confirmed, adapter.open_position() és cridat. T5.19 Fast-ACK."""
    import time
    app = create_app()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.position_id = "paper:42"
    mock_result.order_id = "order-1"
    mock_result.executed_price = 1.0855
    mock_result.executed_size = 100.0
    mock_result.tx_hash = ""

    mock_adapter = AsyncMock()
    mock_adapter.open_position = AsyncMock(return_value=mock_result)

    ok_reader = _make_ok_gate_reader()

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=ok_reader,
            adapter_factory=lambda venue: mock_adapter,
            mode="paper",
            venue="paper",
        )
        r = client.post("/api/v1/broker/orders/open", json={
            "venue": "paper",
            "symbol": "EURUSD",
            "side": "long",
            "collateral": 100.0,
            "leverage": 2.0,
        })

        assert r.status_code == 202, f"Expected 202 Fast-ACK, got {r.status_code}: {r.text}"
        op_id = r.json().get("operation_id")
        assert op_id
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{op_id}")
            if r_op.status_code == 200 and r_op.json().get("status") == "confirmed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"Operation {op_id} no confirmed")

    assert mock_adapter.open_position.called, "open_position HAURIA de ser cridat quan gate=OK"
    print(f"✓ test_quality_gate_ok_allows_order_open passed")


def test_quality_gate_not_applied_without_reader():
    """Sense data_layer_reader, el gate no s'aplica. T5.19: 202 + poll confirmed."""
    import time
    app = create_app()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.position_id = "paper:10"
    mock_result.order_id = "o10"
    mock_result.executed_price = 1.08
    mock_result.executed_size = 50.0
    mock_result.tx_hash = ""

    mock_adapter = AsyncMock()
    mock_adapter.open_position = AsyncMock(return_value=mock_result)

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=None,  # sense reader → gate no s'aplica
            adapter_factory=lambda venue: mock_adapter,
            mode="paper",
            venue="paper",
        )
        r = client.post("/api/v1/broker/orders/open", json={
            "venue": "paper",
            "symbol": "EURUSD",
            "side": "long",
            "collateral": 100.0,
            "leverage": 2.0,
        })

        assert r.status_code == 202, f"Expected 202 Fast-ACK, got {r.status_code}: {r.text}"
        op_id = r.json().get("operation_id")
        for _ in range(50):
            r_op = client.get(f"/api/v1/broker/operations/{op_id}")
            if r_op.status_code == 200 and r_op.json().get("status") == "confirmed":
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"Operation {op_id} no confirmed")

    assert mock_adapter.open_position.called, "open_position HAURIA de ser cridat sense reader"
    print("✓ test_quality_gate_not_applied_without_reader passed")


def test_data_quality_guard_never_throws_for_gate():
    """assert_data_quality_ok: gate=BAD → DataQualityGateBadError (no propagació d'altres exc)."""
    import asyncio
    from application.services.data_quality_guard import assert_data_quality_ok
    from application.errors import DataQualityGateBadError

    bad_reader = _make_bad_gate_reader("EURUSD")

    with asyncio.Runner() as runner:
        try:
            runner.run(assert_data_quality_ok(bad_reader, symbol="EURUSD"))
            assert False, "Hauria d'haver llançat DataQualityGateBadError"
        except DataQualityGateBadError as e:
            assert e.symbol == "EURUSD"
            assert "missing_headers" in e.reason
    print("✓ test_data_quality_guard_never_throws_for_gate passed")


def main() -> int:
    test_quality_gate_bad_blocks_order_open()
    test_quality_gate_bad_does_not_call_venue()
    test_quality_gate_ok_allows_order_open()
    test_quality_gate_not_applied_without_reader()
    test_data_quality_guard_never_throws_for_gate()
    print("OK test_quality_gate_enforced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
