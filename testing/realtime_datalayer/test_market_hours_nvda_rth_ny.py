#!/usr/bin/env python3
"""
Realtime DataLayer — NVDA RTH 09:31–15:59 NY (0-network).
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import zoneinfo
from apps.realtime_datalayer.market_hours.engine import get_market_state_ny

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


def test_nvda_rth_open():
    """09:31–15:59 NY = open."""
    dt_ny = datetime(2026, 2, 18, 12, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "open"
    assert r.reason == "open"
    print("✓ test_nvda_rth_open passed")


def test_nvda_rth_closed_morning():
    """Abans 09:31 = rth_closed."""
    dt_ny = datetime(2026, 2, 18, 8, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed"
    assert r.reason == "rth_closed"
    assert "09:31" in (r.next_open_local or "")
    print("✓ test_nvda_rth_closed_morning passed")


def test_nvda_rth_closed_after():
    """Després 15:59 = rth_closed."""
    dt_ny = datetime(2026, 2, 18, 16, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed"
    assert r.reason == "rth_closed"
    print("✓ test_nvda_rth_closed_after passed")


def main() -> int:
    test_nvda_rth_open()
    test_nvda_rth_closed_morning()
    test_nvda_rth_closed_after()
    print("OK test_market_hours_nvda_rth_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
