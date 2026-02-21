#!/usr/bin/env python3
"""Realtime DataLayer — XAUUSD 24/5 + break diari 17:00–18:00 NY (0-network)."""

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
    """17:00–18:00 NY (dies laborables) = closed (daily_break), next_open=18:00."""
    dt_ny = datetime(2026, 2, 18, 17, 30, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed", f"Expected closed, got {r.state}"
    assert r.reason == "daily_break", f"Expected daily_break, got {r.reason}"
    assert r.next_open_local is not None
    assert "18:00" in (r.next_open_local or ""), f"next_open hauria de ser 18:00 NY, got {r.next_open_local}"
    print("✓ test_xau_break_closed passed")


def test_xau_open_before_break():
    """Abans de 17:00 NY (dia laborable) = open."""
    dt_ny = datetime(2026, 2, 18, 10, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "open", f"Expected open, got {r.state}"
    assert r.reason == "open"
    print("✓ test_xau_open_before_break passed")


def test_xau_open_after_break():
    """18:00 NY (dia laborable) = open (break finalitzat)."""
    dt_ny = datetime(2026, 2, 18, 18, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "open", f"Expected open at 18:00, got {r.state}"
    print("✓ test_xau_open_after_break passed")


def test_xau_weekend_saturday_closed():
    """Dissabte (tot el dia) = closed (weekend)."""
    dt_ny = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)  # Dissabte
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed", f"Expected closed on Saturday, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    assert r.next_open_local is not None
    assert "18:00" in (r.next_open_local or ""), f"next_open hauria de ser diumenge 18:00 NY, got {r.next_open_local}"
    print("✓ test_xau_weekend_saturday_closed passed")


def test_xau_weekend_sunday_before_open():
    """Diumenge <18:00 NY = closed (weekend)."""
    dt_ny = datetime(2026, 2, 22, 12, 0, 0, tzinfo=NY_TZ)  # Diumenge
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed", f"Expected closed Sunday before 18:00, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    assert r.next_open_local is not None
    assert "18:00" in (r.next_open_local or ""), f"next_open hauria de ser 18:00 NY, got {r.next_open_local}"
    print("✓ test_xau_weekend_sunday_before_open passed")


def test_xau_weekend_sunday_at_open():
    """Diumenge 18:00 NY = open."""
    dt_ny = datetime(2026, 2, 22, 18, 0, 0, tzinfo=NY_TZ)  # Diumenge
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "open", f"Expected open Sunday at 18:00, got {r.state}"
    print("✓ test_xau_weekend_sunday_at_open passed")


def test_xau_friday_closes_at_17():
    """Divendres 17:00 NY = closed (weekend, no daily_break)."""
    dt_ny = datetime(2026, 2, 27, 17, 0, 0, tzinfo=NY_TZ)  # Divendres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed", f"Expected closed Friday at 17:00, got {r.state}"
    assert r.reason == "weekend", f"Expected weekend, got {r.reason}"
    print("✓ test_xau_friday_closes_at_17 passed")


def test_xau_friday_open_before_close():
    """Divendres 16:00 NY = open."""
    dt_ny = datetime(2026, 2, 27, 16, 0, 0, tzinfo=NY_TZ)  # Divendres
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "open", f"Expected open Friday at 16:00, got {r.state}"
    print("✓ test_xau_friday_open_before_close passed")


def main() -> int:
    test_xau_break_closed()
    test_xau_open_before_break()
    test_xau_open_after_break()
    test_xau_weekend_saturday_closed()
    test_xau_weekend_sunday_before_open()
    test_xau_weekend_sunday_at_open()
    test_xau_friday_closes_at_17()
    test_xau_friday_open_before_close()
    print("OK test_market_hours_xau_break_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
