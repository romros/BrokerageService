#!/usr/bin/env python3
"""
Realtime DataLayer — NVDAUSD RTH 09:31–15:59 NY (weekday only, 0-network).
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
    """09:31–15:59 NY (dia laborable) = open."""
    dt_ny = datetime(2026, 2, 18, 12, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "open", f"Expected open, got {r.state}"
    assert r.reason == "open"
    print("✓ test_nvda_rth_open passed")


def test_nvda_rth_at_open():
    """09:31 NY = open (punt exacte d'obertura, diferent de GOOGUSD 09:30)."""
    dt_ny = datetime(2026, 2, 18, 9, 31, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "open", f"Expected open at 09:31, got {r.state}"
    print("✓ test_nvda_rth_at_open passed")


def test_nvda_rth_closed_morning():
    """Abans 09:31 = rth_closed amb next_open=09:31."""
    dt_ny = datetime(2026, 2, 18, 8, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed", f"Expected closed, got {r.state}"
    assert r.reason == "rth_closed", f"Expected rth_closed, got {r.reason}"
    assert "09:31" in (r.next_open_local or ""), f"next_open hauria de ser 09:31 NY, got {r.next_open_local}"
    print("✓ test_nvda_rth_closed_morning passed")


def test_nvda_rth_closed_after():
    """Després 15:59 = rth_closed."""
    dt_ny = datetime(2026, 2, 18, 16, 30, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed", f"Expected closed at 16:30, got {r.state}"
    assert r.reason == "rth_closed", f"Expected rth_closed, got {r.reason}"
    print("✓ test_nvda_rth_closed_after passed")


def test_nvda_weekend_saturday_closed():
    """Dissabte = closed (weekend), no RTH."""
    dt_ny = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)  # Dissabte
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed", f"Expected closed on Saturday, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    assert r.next_open_local is not None
    assert "09:31" in (r.next_open_local or ""), f"next_open hauria de ser dilluns 09:31 NY, got {r.next_open_local}"
    print("✓ test_nvda_weekend_saturday_closed passed")


def test_nvda_weekend_sunday_closed():
    """Diumenge = closed (weekend), no RTH."""
    dt_ny = datetime(2026, 2, 22, 12, 0, 0, tzinfo=NY_TZ)  # Diumenge
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed", f"Expected closed on Sunday, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    print("✓ test_nvda_weekend_sunday_closed passed")


def main() -> int:
    test_nvda_rth_open()
    test_nvda_rth_at_open()
    test_nvda_rth_closed_morning()
    test_nvda_rth_closed_after()
    test_nvda_weekend_saturday_closed()
    test_nvda_weekend_sunday_closed()
    print("OK test_market_hours_nvda_rth_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
