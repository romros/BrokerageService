#!/usr/bin/env python3
"""
Realtime DataLayer — autorecover quan arriba tick nou (0-network).

Comprova que _autorecover treu el símbol de degraded quan arriba un tick.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_autorecover_clears_degraded():
    """Quan arriba un tick i el símbol és degraded, _autorecover el torna a running."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService
    from application.data.data_layer_metrics import get_data_layer_metrics

    store = MagicMock()
    ingest = OstiumCandleIngestService(store, ["EURUSD"], poll_interval_s=2)
    ingest._degraded_symbols = {"EURUSD"}
    ingest._degraded_reason["EURUSD"] = "stale"
    ingest._symbol_backoff_until["EURUSD"] = 999999

    with patch("application.services.ostium_candle_ingest_service.get_data_layer_metrics") as mock_metrics:
        mock_m = MagicMock()
        mock_metrics.return_value = mock_m
        ingest._autorecover("EURUSD")

    assert "EURUSD" not in ingest._degraded_symbols
    assert "EURUSD" not in ingest._degraded_reason
    assert "EURUSD" not in ingest._symbol_backoff_until
    assert mock_m.set_symbol_state.called
    print("✓ test_autorecover_clears_degraded passed")


def main() -> int:
    test_autorecover_clears_degraded()
    print("OK test_autorecover_on_new_tick")
    return 0


if __name__ == "__main__":
    sys.exit(main())
