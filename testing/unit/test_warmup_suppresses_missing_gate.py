#!/usr/bin/env python3
"""
Warmup: observed_open_minutes_24h < warmup → no DEGRADED per missing_24h.

0-network. Valida que durant cold start (cobertura recent 24h < warmup) no s'aplica gate missing.
"""

import tempfile
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.data.mock_provider import MockBackfillProvider
from domain.models import Candle
from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics, get_data_layer_metrics
from application.data.data_layer_lifecycle import (
    DATA_LAYER_READY,
    DATA_LAYER_WARMING_UP,
    get_data_layer_status,
    set_data_layer_status,
)
from application.services.data_layer_prod_service import DataLayerProdService


def test_warmup_suppresses_missing_gate():
    """Store amb < warmup_minutes de cobertura → no DEGRADED per missing_24h."""
    print("Testing warmup suppresses missing gate...")

    with tempfile.TemporaryDirectory() as tmp:
        store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
        # Escriure només 10 minuts de dades (coverage=10)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=10)
        for i in range(10):
            ts = start + timedelta(minutes=i)
            c = Candle(
                symbol="EURUSD",
                timestamp=ts,
                open=1.08,
                high=1.08,
                low=1.08,
                close=1.08,
                volume=0,
                is_closed=True,
            )
            store.append(c)

        set_data_layer_metrics(DataLayerMetrics())
        set_data_layer_status("initializing")

        # warmup_minutes=120, coverage=10 → no hauria de marcar DEGRADED per missing
        svc = DataLayerProdService(
            store=store,
            provider=MockBackfillProvider(base_price=1.08, seed=1),
            symbols=["EURUSD"],
            prefetch_minutes=0,
            warmup_minutes=120,
            max_missing_per_24h=1,
            stale_seconds=3600,
            max_gap_s=180,
        )
        svc._update_gate_metrics()

        metrics = get_data_layer_metrics()
        assert metrics is not None
        snap = metrics.snapshot()
        eur = snap.get("symbols", {}).get("EURUSD", {})
        # Hauria de ser ACTIVE (no DEGRADED) perquè observed_open < warmup
        assert eur.get("symbol_state") == "ACTIVE", f"Expected ACTIVE during warmup, got {eur.get('symbol_state')}"
        obs = eur.get("observed_open_minutes_24h", 0)
        assert obs < 120, f"observed_open_minutes_24h={obs} hauria de ser < 120 per warmup"

        status, _ = get_data_layer_status()
        assert status == DATA_LAYER_WARMING_UP, f"Expected warming_up, got {status}"

        set_data_layer_metrics(None)
        set_data_layer_status("disabled")
        print("✓ warmup suppresses missing gate OK")


def test_observed_above_warmup_ready():
    """Quan observed_open >= warmup i missing <= llindar → READY."""
    print("Testing observed above warmup → READY...")

    with tempfile.TemporaryDirectory() as tmp:
        store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
        # 1440 minuts (24h) → missing=0, observed=1440 → READY
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=1440)
        for i in range(1440):
            ts = start + timedelta(minutes=i)
            c = Candle(
                symbol="EURUSD",
                timestamp=ts,
                open=1.08,
                high=1.08,
                low=1.08,
                close=1.08,
                volume=0,
                is_closed=True,
            )
            store.append(c)

        set_data_layer_metrics(DataLayerMetrics())
        set_data_layer_status("initializing")

        svc = DataLayerProdService(
            store=store,
            provider=MockBackfillProvider(base_price=1.08, seed=1),
            symbols=["EURUSD"],
            prefetch_minutes=0,
            warmup_minutes=120,
            max_missing_per_24h=1,
            stale_seconds=3600,
            max_gap_s=180,
        )
        svc._update_gate_metrics()

        status, _ = get_data_layer_status()
        assert status == DATA_LAYER_READY, f"Expected READY (full 24h), got {status}"

        set_data_layer_metrics(None)
        set_data_layer_status("disabled")
        print("✓ observed above warmup OK")


def test_startup_gate_warmup_ignores_missing():
    """Startup gate: in_warmup → PASS encara que missing alt."""
    print("Testing startup gate warmup ignores missing...")

    with tempfile.TemporaryDirectory() as tmp:
        store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
        # 10 minuts → observed baix → warmup
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=10)
        for i in range(10):
            ts = start + timedelta(minutes=i)
            c = Candle(symbol="EURUSD", timestamp=ts, open=1.08, high=1.08, low=1.08, close=1.08, volume=0, is_closed=True)
            store.append(c)

        set_data_layer_metrics(DataLayerMetrics())
        svc = DataLayerProdService(
            store=store,
            provider=MockBackfillProvider(base_price=1.08, seed=1),
            symbols=["EURUSD"],
            prefetch_minutes=0,
            warmup_minutes=120,
            max_missing_per_24h=1,
            stale_seconds=3600,
            max_gap_s=180,
        )
        ok, reason = svc.run_startup_gate_check()
        assert ok, f"Startup gate hauria de passar en warmup (missing ignorat): {reason}"

        set_data_layer_metrics(None)
        print("✓ startup gate warmup OK")


if __name__ == "__main__":
    test_warmup_suppresses_missing_gate()
    test_observed_above_warmup_ready()
    test_startup_gate_warmup_ignores_missing()
