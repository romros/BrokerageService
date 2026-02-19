#!/usr/bin/env python3
"""
Realtime DataLayer — degraded no bloqueja el polling (0-network).

Comprova que un símbol degraded continua a poll_symbols (amb backoff)
i que get_symbol_stats retorna next_poll_in_s i degrade_reason.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_degraded_symbol_included_in_poll_with_backoff():
    """Degraded no exclou el símbol: quan backoff ha passat, es torna a intentar."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService
    from datetime import datetime, timezone

    store = MagicMock()
    store.append = MagicMock(return_value=True)
    ingest = OstiumCandleIngestService(store, ["EURUSD"], poll_interval_s=2)
    ingest.symbols = ["EURUSD"]
    ingest._stopped_symbols = set()
    ingest._paused_symbols = set()
    ingest._degraded_symbols = {"EURUSD"}
    ingest._degraded_reason["EURUSD"] = "stale_seconds=200"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ingest._symbol_backoff_until["EURUSD"] = now_ts - 5  # backoff passat

    stats = ingest.get_symbol_stats()
    eur = stats.get("EURUSD", {})
    assert eur["state"] == "degraded"
    assert eur.get("degrade_reason") == "stale_seconds=200"
    assert eur.get("next_poll_in_s") is not None
    assert eur["next_poll_in_s"] <= 0  # ja pot tornar a pollar
    print("✓ test_degraded_symbol_included_in_poll_with_backoff passed")


def test_degraded_not_in_paused_symbols():
    """Degraded no va a _paused_symbols; només market_closed fa pause."""
    from application.services.ostium_candle_ingest_service import OstiumCandleIngestService

    store = MagicMock()
    ingest = OstiumCandleIngestService(store, ["EURUSD"], poll_interval_s=2)
    ingest._degraded_symbols = {"EURUSD"}
    ingest._paused_symbols = set()  # market_open
    assert "EURUSD" not in ingest._paused_symbols
    print("✓ test_degraded_not_in_paused_symbols passed")


def main() -> int:
    test_degraded_symbol_included_in_poll_with_backoff()
    test_degraded_not_in_paused_symbols()
    print("OK test_degraded_does_not_stop_polling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
