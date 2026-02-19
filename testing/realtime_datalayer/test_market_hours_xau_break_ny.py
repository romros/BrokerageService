#!/usr/bin/env python3
"""Realtime DataLayer — XAU break 16:59–18:10 NY (0-network)."""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import zoneinfo
from apps.realtime_datalayer.market_hours.engine import get_market_state_ny

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


def test_xau_break_closed():
    """16:59–18:10 NY = closed (daily_break)."""
    dt_ny = datetime(2026, 2, 18, 17, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed"
    assert r.reason == "daily_break"
    assert r.next_open_local is not None
    assert "18:10" in (r.next_open_local or "")
    print("✓ test_xau_break_closed passed")


def test_xau_open_before_break():
    """Abans de 16:59 NY = open."""
    dt_ny = datetime(2026, 2, 18, 10, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "open"
    assert r.reason == "open"
    print("✓ test_xau_open_before_break passed")


def main() -> int:
    test_xau_break_closed()
    test_xau_open_before_break()
    print("OK test_market_hours_xau_break_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
