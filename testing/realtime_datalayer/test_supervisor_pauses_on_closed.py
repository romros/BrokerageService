#!/usr/bin/env python3
"""Realtime DataLayer — supervisor pausa per símbol quan closed (0-network)."""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import zoneinfo
from apps.realtime_datalayer.market_hours import get_market_state_for_ingest

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


def test_nvda_paused_outside_rth():
    """NVDA fora de 09:31–15:59 NY → market_open=False."""
    dt_ny = datetime(2026, 2, 18, 8, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    open_, reason = get_market_state_for_ingest("NVDAUSD", ts)
    assert open_ is False
    assert reason == "rth_closed"
    print("✓ test_nvda_paused_outside_rth passed")


def test_xau_paused_during_break():
    """XAU durant break 16:59–18:10 NY → market_open=False."""
    dt_ny = datetime(2026, 2, 18, 17, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    open_, reason = get_market_state_for_ingest("XAUUSD", ts)
    assert open_ is False
    assert reason == "daily_break"
    print("✓ test_xau_paused_during_break passed")


def main() -> int:
    test_nvda_paused_outside_rth()
    test_xau_paused_during_break()
    print("OK test_supervisor_pauses_on_closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
