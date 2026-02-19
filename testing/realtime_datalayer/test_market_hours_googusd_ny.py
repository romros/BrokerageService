#!/usr/bin/env python3
"""
Realtime DataLayer — GOOGUSD us_equities_ny RTH 09:30–16:00 NY (0-network).

Valida que GOOGUSD queda paused_closed fora d'horari NYSE.
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


def test_googusd_rth_open():
    """10:00 NY weekday = open."""
    dt_ny = datetime(2026, 2, 18, 10, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("GOOGUSD", ts)
    assert r.state == "open", f"Expected open, got {r.state}"
    assert r.reason == "open", f"Expected reason=open, got {r.reason}"
    print("✓ test_googusd_rth_open passed")


def test_googusd_rth_open_at_open():
    """09:30 NY = open (punt exacte d'obertura)."""
    dt_ny = datetime(2026, 2, 18, 9, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("GOOGUSD", ts)
    assert r.state == "open", f"Expected open at 09:30, got {r.state}"
    print("✓ test_googusd_rth_open_at_open passed")


def test_googusd_rth_closed_morning():
    """Abans 09:30 = rth_closed amb next_open=09:30."""
    dt_ny = datetime(2026, 2, 18, 8, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("GOOGUSD", ts)
    assert r.state == "closed", f"Expected closed, got {r.state}"
    assert r.reason == "rth_closed", f"Expected rth_closed, got {r.reason}"
    assert r.next_open_local is not None, "next_open_local hauria de ser present"
    assert "09:30" in (r.next_open_local or ""), f"next_open_local hauria de ser 09:30 NY, got {r.next_open_local}"
    print("✓ test_googusd_rth_closed_morning passed")


def test_googusd_rth_closed_after_close():
    """16:00 NY (o posterior) = rth_closed amb next_open proper dia laboral 09:30."""
    dt_ny = datetime(2026, 2, 18, 16, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("GOOGUSD", ts)
    assert r.state == "closed", f"Expected closed at 16:30, got {r.state}"
    assert r.reason == "rth_closed", f"Expected rth_closed, got {r.reason}"
    assert r.next_open_local is not None, "next_open_local hauria de ser present"
    assert "09:30" in (r.next_open_local or ""), f"next_open_local hauria de ser 09:30 NY, got {r.next_open_local}"
    print("✓ test_googusd_rth_closed_after_close passed")


def test_googusd_weekend_closed():
    """Dissabte = weekend closed amb next_open = dilluns 09:30."""
    # 2026-02-21 = Dissabte
    dt_ny = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("GOOGUSD", ts)
    assert r.state == "closed", f"Expected closed on weekend, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    assert r.next_open_local is not None, "next_open_local hauria de ser present el cap de setmana"
    assert "09:30" in (r.next_open_local or ""), f"next_open_local hauria de ser 09:30 NY, got {r.next_open_local}"
    print("✓ test_googusd_weekend_closed passed")


def test_googusd_state_does_not_regress_nvdausd():
    """NVDAUSD segueix usant ostium_rth_equities (09:31–15:59), no us_equities_ny."""
    # 09:30 NY = obert per GOOGUSD però tancat per NVDAUSD (09:31 és l'inici NVDA)
    dt_ny = datetime(2026, 2, 18, 9, 30, 0, tzinfo=NY_TZ)
    ts = int(dt_ny.timestamp())
    goog = get_market_state_ny("GOOGUSD", ts)
    nvda = get_market_state_ny("NVDAUSD", ts)
    assert goog.state == "open", f"GOOGUSD hauria de ser open a les 09:30, got {goog.state}"
    assert nvda.state == "closed", f"NVDAUSD hauria de ser closed a les 09:30 (s'obre 09:31), got {nvda.state}"
    print("✓ test_googusd_state_does_not_regress_nvdausd passed")


def main() -> int:
    test_googusd_rth_open()
    test_googusd_rth_open_at_open()
    test_googusd_rth_closed_morning()
    test_googusd_rth_closed_after_close()
    test_googusd_weekend_closed()
    test_googusd_state_does_not_regress_nvdausd()
    print("OK test_market_hours_googusd_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
