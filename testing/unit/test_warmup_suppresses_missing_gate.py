#!/usr/bin/env python3
"""
Warmup window: store amb menys de warmup_minutes → no DEGRADED per missing_24h.

0-network. Valida que durant cold start (coverage < warmup) no s'aplica gate missing.
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
from application.data.data_layer_lifecycle import DATA_LAYER_WARMING_UP, get_data_layer_status, set_data_layer_status
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
        # Hauria de ser ACTIVE (no DEGRADED) perquè coverage < warmup
        assert eur.get("symbol_state") == "ACTIVE", f"Expected ACTIVE during warmup, got {eur.get('symbol_state')}"

        status, _ = get_data_layer_status()
        assert status == DATA_LAYER_WARMING_UP, f"Expected warming_up, got {status}"

        set_data_layer_metrics(None)
        set_data_layer_status("disabled")
        print("✓ warmup suppresses missing gate OK")


if __name__ == "__main__":
    test_warmup_suppresses_missing_gate()
