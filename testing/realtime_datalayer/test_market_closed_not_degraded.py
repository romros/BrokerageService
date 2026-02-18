#!/usr/bin/env python3
"""
Realtime DataLayer — market_closed no degrada (0-network).

Quan market_closed i no hi ha ticks/candles recents, l'estat és market_closed,
no DEGRADED. Health no baixa per això.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.data_layer_metrics import DataLayerMetrics, set_data_layer_metrics
from application.market_hours.fx_24_5 import get_market_state, stale_degradation_applies


def test_market_closed_stale_not_degraded():
    """Amb market_closed i stale alt, no es marca DEGRADED."""
    # Dissabte 12:00 UTC — mercat tancat
    ts_sat = int(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    assert get_market_state("XAUUSD", ts_sat) == (False, "closed")
    assert not stale_degradation_applies("XAUUSD", ts_sat)

    metrics = DataLayerMetrics()
    set_data_layer_metrics(metrics)
    try:
        metrics.update_gate_metrics(
            "XAUUSD",
            last_candle_ts=ts_sat - 3600,
            stale_seconds=2000,
            market_open=False,
            market_state_reason="closed",
        )
        snapshot = metrics.snapshot()
        xau = snapshot["symbols"]["XAUUSD"]
        assert xau["market_open"] is False
        assert xau["market_state_reason"] == "closed"
        assert xau.get("symbol_state") != "DEGRADED" or "stale" not in str(xau.get("degrade_reason", ""))
    finally:
        set_data_layer_metrics(None)

    print("✓ test_market_closed_stale_not_degraded passed")


def test_unknown_symbol_no_stale_degradation():
    """Indices/equities (unknown): stale_degradation_applies = False."""
    ts = int(datetime.now(timezone.utc).timestamp())
    assert get_market_state("GOOGUSD", ts) == (True, "unknown")
    assert not stale_degradation_applies("GOOGUSD", ts)
    print("✓ test_unknown_symbol_no_stale_degradation passed")


def main() -> int:
    test_market_closed_stale_not_degraded()
    test_unknown_symbol_no_stale_degradation()
    print("OK test_market_closed_not_degraded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
