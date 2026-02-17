#!/usr/bin/env python3
"""
data_status inclou market_open — unit tests (0-network)

Camp market_open i market_state_reason presents i coherents.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics


def test_snapshot_includes_market_open():
    """SymbolMetrics snapshot inclou market_open i market_state_reason."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        metrics = DataLayerMetrics()
        metrics.update_gate_metrics(
            "EURUSD",
            stale_seconds=0,
            missing_minutes_24h=0,
            market_open=True,
            market_state_reason="open",
        )
        metrics.update_gate_metrics(
            "XAUUSD",
            stale_seconds=0,
            missing_minutes_24h=0,
            market_open=False,
            market_state_reason="closed",
        )
        snap = metrics.snapshot()
        eur = snap["symbols"].get("EURUSD", {})
        xau = snap["symbols"].get("XAUUSD", {})
        assert eur.get("market_open") is True
        assert eur.get("market_state_reason") == "open"
        assert xau.get("market_open") is False
        assert xau.get("market_state_reason") == "closed"
    print("✓ test_snapshot_includes_market_open OK")


def test_default_market_open_true():
    """Per defecte market_open=True si no s'ha actualitzat."""
    metrics = DataLayerMetrics()
    metrics.update_gate_metrics("BTCUSD", stale_seconds=0)
    snap = metrics.snapshot()
    btc = snap["symbols"].get("BTCUSD", {})
    assert btc.get("market_open", True) is True
    assert "market_state_reason" in btc
    print("✓ test_default_market_open_true OK")


def main():
    test_snapshot_includes_market_open()
    test_default_market_open_true()
    print("\n✓ All data_status_includes_market_open tests passed")


if __name__ == "__main__":
    main()
