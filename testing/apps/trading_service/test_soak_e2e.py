#!/usr/bin/env python3
"""
Split vNext Phase 6 — Soak end-to-end (0-network, reproduïble).

Valida els 3 casos del quality gate en el trading loop:
  Cas A (OK):   gate=OK  → POST /orders/open retorna 200, adapter cridat
  Cas B (BAD):  gate=BAD → POST /orders/open retorna 422 DATA_QUALITY_GATE_BAD, adapter NO cridat
  Cas C (down): reader llança excepció (datalayer down) → 422 DATA_QUALITY_GATE_BAD (fail-closed)

Guarda artifact JSON a datafiles/e2e_runs/ amb timestamps i resultats.

0-network: usa TestClient + mocks, sense Docker ni xarxa real.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


# ─── Helpers mocks ────────────────────────────────────────────────────────────

def _make_ok_reader(symbol: str = "EURUSD") -> MagicMock:
    """Reader que retorna gate=OK amb headers complets."""
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


def _make_bad_reader(symbol: str = "EURUSD") -> MagicMock:
    """Reader que retorna gate=BAD (missing_headers)."""
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


def _make_down_reader() -> MagicMock:
    """Reader que llança excepció simulant datalayer down."""
    reader = MagicMock()

    async def get_ohlcv_with_gate(**kwargs):
        raise ConnectionError("realtime_datalayer unreachable (simulated)")

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def _make_mock_adapter() -> AsyncMock:
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.position_id = "paper:e2e-1"
    mock_result.order_id = "order-e2e-1"
    mock_result.executed_price = 1.0855
    mock_result.executed_size = 100.0
    mock_result.tx_hash = ""

    adapter = AsyncMock()
    adapter.open_position = AsyncMock(return_value=mock_result)
    return adapter


# ─── Casos de test ────────────────────────────────────────────────────────────

def run_cas_a_gate_ok() -> dict:
    """Cas A: gate=OK → 200, adapter cridat."""
    app = create_app()
    ok_reader = _make_ok_reader()
    mock_adapter = _make_mock_adapter()
    t0 = time.time()

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

    elapsed_ms = int((time.time() - t0) * 1000)
    passed = r.status_code == 200 and mock_adapter.open_position.called
    result = {
        "cas": "A_gate_ok",
        "status_code": r.status_code,
        "adapter_called": mock_adapter.open_position.called,
        "elapsed_ms": elapsed_ms,
        "passed": passed,
        "detail": r.json() if r.status_code != 200 else None,
    }
    assert passed, f"CAS A FAILED: {result}"
    print(f"  ✓ Cas A (gate=OK): status={r.status_code} adapter_called={mock_adapter.open_position.called} ({elapsed_ms}ms)")
    return result


def run_cas_b_gate_bad() -> dict:
    """Cas B: gate=BAD → 422 DATA_QUALITY_GATE_BAD, adapter NO cridat."""
    app = create_app()
    bad_reader = _make_bad_reader()
    mock_adapter = _make_mock_adapter()
    t0 = time.time()

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

    elapsed_ms = int((time.time() - t0) * 1000)
    data = r.json()
    has_error_code = "DATA_QUALITY_GATE_BAD" in str(data)
    passed = r.status_code == 422 and has_error_code and not mock_adapter.open_position.called
    result = {
        "cas": "B_gate_bad",
        "status_code": r.status_code,
        "error_code_present": has_error_code,
        "adapter_called": mock_adapter.open_position.called,
        "elapsed_ms": elapsed_ms,
        "passed": passed,
        "detail": data,
    }
    assert passed, f"CAS B FAILED: {result}"
    print(f"  ✓ Cas B (gate=BAD): status={r.status_code} error_code={has_error_code} adapter_called={mock_adapter.open_position.called} ({elapsed_ms}ms)")
    return result


def run_cas_c_datalayer_down() -> dict:
    """Cas C: datalayer down (reader llança exc) → 422 DATA_QUALITY_GATE_BAD (fail-closed)."""
    app = create_app()
    down_reader = _make_down_reader()
    mock_adapter = _make_mock_adapter()
    t0 = time.time()

    with TestClient(app) as client:
        set_broker_deps(
            data_layer_reader=down_reader,
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

    elapsed_ms = int((time.time() - t0) * 1000)
    data = r.json()
    has_error_code = "DATA_QUALITY_GATE_BAD" in str(data)
    passed = r.status_code == 422 and has_error_code and not mock_adapter.open_position.called
    result = {
        "cas": "C_datalayer_down",
        "status_code": r.status_code,
        "error_code_present": has_error_code,
        "adapter_called": mock_adapter.open_position.called,
        "elapsed_ms": elapsed_ms,
        "passed": passed,
        "detail": data,
    }
    assert passed, f"CAS C FAILED: {result}"
    print(f"  ✓ Cas C (datalayer down): status={r.status_code} error_code={has_error_code} adapter_called={mock_adapter.open_position.called} ({elapsed_ms}ms)")
    return result


# ─── Artifact ─────────────────────────────────────────────────────────────────

def _save_artifact(results: list[dict]) -> Path:
    """Guarda artifact JSON a datafiles/e2e_runs/."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "datafiles" / "e2e_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = out_dir / f"{ts}_soak_e2e.json"
    artifact = {
        "run_ts": ts,
        "run_ts_epoch": int(time.time()),
        "phase": "Phase6_soak_e2e",
        "mode": "0-network (TestClient + mocks)",
        "all_passed": all(r["passed"] for r in results),
        "results": results,
    }
    artifact_path.write_text(json.dumps(artifact, indent=2))
    return artifact_path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=== Phase 6: Soak e2e (0-network) ===")
    t_start = time.time()
    results = []

    print("\n[Cas A] gate=OK → ordre passa")
    results.append(run_cas_a_gate_ok())

    print("\n[Cas B] gate=BAD → 422 NO_TRADE")
    results.append(run_cas_b_gate_bad())

    print("\n[Cas C] datalayer down → 422 fail-closed")
    results.append(run_cas_c_datalayer_down())

    artifact_path = _save_artifact(results)
    elapsed = round(time.time() - t_start, 2)
    all_ok = all(r["passed"] for r in results)
    print(f"\nArtifact: {artifact_path}")
    print(f"Elapsed: {elapsed}s — {'OK all 3 casos passed' if all_ok else 'SOME FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
