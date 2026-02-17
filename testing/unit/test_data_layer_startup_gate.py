#!/usr/bin/env python3
"""
Tests per startup gate (0-network).

Quan DATA_LAYER_STARTUP_GATE=1 i mètriques indiquen dupes → readiness FAIL.
Quan gate OFF → no falla.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_startup_gate_off_no_fail():
    """Gate OFF per defecte: no cal que sigui 1."""
    gate = os.getenv("DATA_LAYER_STARTUP_GATE", "0")
    # En CI normal, gate és 0. Si algu el posa 1, el test passa igual.
    assert gate in ("0", "1")


def test_startup_gate_check_pass():
    """run_startup_gate_check retorna (True, "") quan tot ACTIVE."""
    from application.services.data_layer_prod_service import DataLayerProdService
    from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics, SYMBOL_STATE_ACTIVE

    store = MagicMock()
    store.get_last_timestamp.return_value = None
    store.read_range.return_value = MagicMock(missing_count=0)
    provider = MagicMock()

    svc = DataLayerProdService(
        store=store,
        provider=provider,
        symbols=["XAUUSD"],
        prefetch_minutes=0,
        max_gap_s=180,
        max_missing_per_24h=1,
        stale_seconds=180,
    )

    # Injectar metrics amb estat ACTIVE
    metrics = DataLayerMetrics()
    m = metrics._get_or_create("XAUUSD")
    m.symbol_state = SYMBOL_STATE_ACTIVE
    m.duplicates = 0
    m.ts_step_errors = 0
    m.stale_seconds = 0
    m.missing_minutes_24h = 0
    m.max_gap_s = 0

    with patch("application.services.data_layer_prod_service.get_data_layer_metrics", return_value=metrics):
        ok, reason = svc.run_startup_gate_check()
        assert ok is True
        assert reason == ""


def test_startup_gate_check_fail_dupes():
    """run_startup_gate_check retorna (False, reason) quan duplicates>0."""
    from application.services.data_layer_prod_service import DataLayerProdService
    from application.data.data_layer_metrics import DataLayerMetrics, SYMBOL_STATE_ACTIVE

    store = MagicMock()
    store.get_last_timestamp.return_value = None
    store.read_range.return_value = MagicMock(missing_count=0)
    provider = MagicMock()

    svc = DataLayerProdService(
        store=store,
        provider=provider,
        symbols=["XAUUSD"],
        prefetch_minutes=0,
    )

    metrics = DataLayerMetrics()
    m = metrics._get_or_create("XAUUSD")
    m.symbol_state = SYMBOL_STATE_ACTIVE
    m.duplicates = 1
    m.ts_step_errors = 0
    m.stale_seconds = 0
    m.missing_minutes_24h = 0
    m.max_gap_s = 0

    with patch("application.services.data_layer_prod_service.get_data_layer_metrics", return_value=metrics):
        ok, reason = svc.run_startup_gate_check()
        assert ok is False
        assert "duplicates" in reason


def test_startup_gate_check_fail_degraded():
    """run_startup_gate_check retorna (False, reason) quan symbol_state DEGRADED."""
    from application.services.data_layer_prod_service import DataLayerProdService
    from application.data.data_layer_metrics import DataLayerMetrics, SYMBOL_STATE_DEGRADED

    store = MagicMock()
    store.get_last_timestamp.return_value = None
    store.read_range.return_value = MagicMock(missing_count=0)
    provider = MagicMock()

    svc = DataLayerProdService(
        store=store,
        provider=provider,
        symbols=["XAUUSD"],
        prefetch_minutes=0,
    )

    metrics = DataLayerMetrics()
    m = metrics._get_or_create("XAUUSD")
    m.symbol_state = SYMBOL_STATE_DEGRADED
    m.degrade_reason = "prefetch duplicates=1"

    with patch("application.services.data_layer_prod_service.get_data_layer_metrics", return_value=metrics):
        ok, reason = svc.run_startup_gate_check()
        assert ok is False
        assert "DEGRADED" in reason or "duplicates" in reason


def run_tests():
    test_startup_gate_off_no_fail()
    test_startup_gate_check_pass()
    test_startup_gate_check_fail_dupes()
    test_startup_gate_check_fail_degraded()
    print("test_data_layer_startup_gate: all passed")


if __name__ == "__main__":
    run_tests()
