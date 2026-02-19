#!/usr/bin/env python3
"""Realtime DataLayer — DAX/SPX break 16:59–18:00 NY (0-network)."""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import zoneinfo
from apps.realtime_datalayer.market_hours.engine import get_market_state_ny

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


def test_indices_break_closed():
    """16:59–18:00 NY = closed (daily_break)."""
    dt_ny = datetime(2026, 2, 18, 17, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "closed", f"{sym} expected closed"
        assert r.reason == "daily_break"
        assert "18:00" in (r.next_open_local or "")
    print("✓ test_indices_break_closed passed")


def test_indices_open():
    """Abans 16:59 = open."""
    dt_ny = datetime(2026, 2, 18, 10, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("DAXEUR", ts)
    assert r.state == "open"
    print("✓ test_indices_open passed")


def main() -> int:
    test_indices_break_closed()
    test_indices_open()
    print("OK test_market_hours_indices_break_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
