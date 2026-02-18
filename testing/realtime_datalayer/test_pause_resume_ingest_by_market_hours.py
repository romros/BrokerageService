#!/usr/bin/env python3
"""
Realtime DataLayer — pause/resume ingest per market hours (0-network).

Simula canvi open↔closed i comprova que _paused_symbols s'actualitza.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.market_hours.fx_24_5 import get_market_state


def test_paused_symbols_logic():
    """_paused_symbols conté símbols amb market_closed."""
    # Dissabte — tancat
    ts_sat = int(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    # Dilluns — obert
    ts_mon = int(datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc).timestamp())

    active = ["EURUSD", "XAUUSD", "GOOGUSD"]
    degraded = set()

    def paused_for(ts):
        return {s for s in active if s not in degraded and not get_market_state(s, ts)[0]}

    paused_sat = paused_for(ts_sat)
    assert "EURUSD" in paused_sat
    assert "XAUUSD" in paused_sat
    assert "GOOGUSD" not in paused_sat  # unknown → market_open=True

    paused_mon = paused_for(ts_mon)
    assert len(paused_mon) == 0

    print("✓ test_paused_symbols_logic passed")


def main() -> int:
    test_paused_symbols_logic()
    print("OK test_pause_resume_ingest_by_market_hours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
