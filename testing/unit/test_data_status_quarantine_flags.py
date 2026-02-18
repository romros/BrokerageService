#!/usr/bin/env python3
"""
data_status exposa quarantine flags — unit tests (0-network)

Quan Ostium ingest enabled: symbols_data inclou ingest_allowed, primary_eligible,
quarantined, quarantine_reason. XAUUSD quarantined → primary_eligible=False.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.data_layer_metrics import (
    DataLayerMetrics,
    get_data_layer_metrics,
    set_data_layer_metrics,
    SYMBOL_STATE_ACTIVE,
)
from application.data.data_layer_lifecycle import (
    set_data_layer_status,
    DATA_LAYER_READY,
)
from application.api.broker_routes import set_broker_deps
from fastapi.testclient import TestClient

from foundation.config.constants import (
    OSTIUM_SYMBOLS_ENV,
    OSTIUM_QUARANTINE_SYMBOLS_ENV,
)


def test_data_status_exposes_quarantine_flags():
    """data_status (Ostium enabled) inclou ingest_allowed, primary_eligible, quarantined, quarantine_reason."""
    orig_sym = os.environ.pop(OSTIUM_SYMBOLS_ENV, None)
    orig_quar = os.environ.pop(OSTIUM_QUARANTINE_SYMBOLS_ENV, None)
    try:
        os.environ[OSTIUM_SYMBOLS_ENV] = "EURUSD,GBPUSD"
        os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = "XAUUSD,XAU"

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["DATAFILES_ROOT"] = tmpdir

            metrics = DataLayerMetrics()
            metrics._get_or_create("EURUSD")
            metrics._get_or_create("XAUUSD")
            metrics.set_symbol_state("EURUSD", SYMBOL_STATE_ACTIVE)
            metrics.set_symbol_state("XAUUSD", SYMBOL_STATE_ACTIVE)
            metrics.update_gate_metrics("EURUSD", stale_seconds=0, missing_minutes_24h=0)
            metrics.update_gate_metrics("XAUUSD", stale_seconds=0, missing_minutes_24h=0)

            set_data_layer_metrics(metrics)
            set_data_layer_status(DATA_LAYER_READY)
            set_broker_deps(ostium_ingest_enabled=True)

            # Mock get_data_layer_metrics per retornar les nostres mètriques (evita pipeline)
            with patch("application.data.data_layer_metrics.get_data_layer_metrics", return_value=metrics):
                from application.main import app
                client = TestClient(app)
                r = client.get("/api/v1/broker/data_status")
            assert r.status_code == 200, r.text
            data = r.json()

            symbols = data.get("symbols") or {}
            assert "primary_allowed_by_symbol" in data

            # EURUSD: allowlist, no quarantine → ingest_allowed, primary_eligible depèn registry
            eur = symbols.get("EURUSD", {})
            assert "ingest_allowed" in eur
            assert "primary_eligible" in eur
            assert "quarantined" in eur
            assert "quarantine_reason" in eur
            assert eur.get("ingest_allowed") is True
            assert eur.get("quarantined") is False

            # XAUUSD: quarantine config → quarantined=True, primary_eligible=False
            xau = symbols.get("XAUUSD", {})
            assert xau.get("quarantined") is True
            assert xau.get("ingest_allowed") is False
            assert xau.get("primary_eligible") is False
            assert xau.get("quarantine_reason") == "config"

            assert data["primary_allowed_by_symbol"].get("XAUUSD") is False
    finally:
        set_data_layer_metrics(None)
        if orig_sym is not None:
            os.environ[OSTIUM_SYMBOLS_ENV] = orig_sym
        if orig_quar is not None:
            os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = orig_quar
    print("✓ test_data_status_exposes_quarantine_flags OK")


def main():
    test_data_status_exposes_quarantine_flags()
    print("\n✓ All data_status quarantine flags tests passed")


if __name__ == "__main__":
    main()
