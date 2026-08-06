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


def test_prod_gate_accepts_canonical_symbol_market_hours():
    """El gate genèric ha de poder usar el mateix calendari que l'ingestor."""
    from unittest.mock import MagicMock
    from application.services.data_layer_prod_service import DataLayerProdService

    closed = lambda symbol, ts: (False, "daily_break")
    service = DataLayerProdService(
        store=MagicMock(), provider=MagicMock(), symbols=["XAUUSD"],
        market_hours_fn=closed,
    )
    assert service._market_hours_fn("XAUUSD", 0) == (False, "daily_break")


def test_canonical_closed_minute_count_includes_xau_daily_break():
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from apps.realtime_datalayer.market_hours import count_closed_minutes_for_ingest

    ny = ZoneInfo("America/New_York")
    start = datetime(2026, 8, 5, 17, 0, tzinfo=ny)
    end = start + timedelta(hours=1)
    assert count_closed_minutes_for_ingest(
        "XAUUSD", int(start.timestamp()), int(end.timestamp())
    ) == 60


def main() -> int:
    test_market_closed_stale_not_degraded()
    test_unknown_symbol_no_stale_degradation()
    test_prod_gate_accepts_canonical_symbol_market_hours()
    test_canonical_closed_minute_count_includes_xau_daily_break()
    print("OK test_market_closed_not_degraded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
