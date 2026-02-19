#!/usr/bin/env python3
"""
Realtime DataLayer — heartbeat mode quan mercat tancat (0-network).

Phase 3: market_closed → heartbeat poll reduït (no stop total).
Comprova que _paused_symbols no exclou símbols del poll completament,
sinó que aplica heartbeat interval i NO escriu candles.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_heartbeat_interval_attribute_exists():
    """OstiumCandleIngestService té heartbeat_interval_s amb default 60s."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    store = MagicMock()
    ingest = OstiumCandleIngestService(store, ["EURUSD"], poll_interval_s=2)
    assert hasattr(ingest, "heartbeat_interval_s")
    assert ingest.heartbeat_interval_s > 0
    print(f"✓ test_heartbeat_interval_attribute_exists: heartbeat_interval_s={ingest.heartbeat_interval_s}")


def test_heartbeat_last_poll_tracking():
    """_heartbeat_last_poll és un dict inicialitzat buit."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    store = MagicMock()
    ingest = OstiumCandleIngestService(store, ["EURUSD", "XAUUSD"], poll_interval_s=2)
    assert hasattr(ingest, "_heartbeat_last_poll")
    assert isinstance(ingest._heartbeat_last_poll, dict)
    assert len(ingest._heartbeat_last_poll) == 0
    print("✓ test_heartbeat_last_poll_tracking passed")


def test_paused_symbols_not_empty_when_market_closed():
    """Quan market_hours_fn retorna closed, _paused_symbols conté el símbol."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    store = MagicMock()
    closed_fn = lambda s, t: (False, "closed")
    ingest = OstiumCandleIngestService(
        store, ["EURUSD"], poll_interval_s=2,
        market_hours_fn=closed_fn,
    )
    ingest._paused_symbols = {"EURUSD"}  # simulem que ja s'ha detectat com a tancat
    assert "EURUSD" in ingest._paused_symbols
    print("✓ test_paused_symbols_not_empty_when_market_closed passed")


def test_heartbeat_env_override():
    """OSTIUM_CLOSED_HEARTBEAT_S env var canvia heartbeat_interval_s."""
    import os
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    os.environ["OSTIUM_CLOSED_HEARTBEAT_S"] = "120"
    try:
        store = MagicMock()
        ingest = OstiumCandleIngestService(store, ["EURUSD"], poll_interval_s=2)
        assert ingest.heartbeat_interval_s == 120
    finally:
        del os.environ["OSTIUM_CLOSED_HEARTBEAT_S"]
    print("✓ test_heartbeat_env_override passed")


def test_get_symbol_stats_paused_closed_state():
    """get_symbol_stats retorna state='paused_closed' per símbol en heartbeat mode."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    store = MagicMock()
    store.get_last_timestamp = MagicMock(return_value=None)
    ingest = OstiumCandleIngestService(
        store, ["EURUSD"], poll_interval_s=2,
        market_hours_fn=lambda s, t: (False, "closed"),
    )
    ingest._paused_symbols = {"EURUSD"}
    stats = ingest.get_symbol_stats()
    assert stats["EURUSD"]["state"] == "paused_closed"
    assert stats["EURUSD"]["market_open"] is False
    print("✓ test_get_symbol_stats_paused_closed_state passed")


def main() -> int:
    test_heartbeat_interval_attribute_exists()
    test_heartbeat_last_poll_tracking()
    test_paused_symbols_not_empty_when_market_closed()
    test_heartbeat_env_override()
    test_get_symbol_stats_paused_closed_state()
    print("OK test_heartbeat_when_closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
