#!/usr/bin/env python3
"""
Market hours FX 24/5 — unit tests (0-network)

Dissabte/diumenge matí → closed; Dilluns → open.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.market_hours import is_market_open
from application.market_hours.fx_24_5 import closed_intervals_between, count_closed_minutes_between


def test_saturday_closed():
    """Dissabte → closed."""
    # 2026-02-14 12:00 UTC = dissabte
    ts = int(datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    assert is_market_open("EURUSD", ts) is False
    assert is_market_open("XAUUSD", ts) is False
    print("✓ test_saturday_closed OK")


def test_sunday_morning_closed():
    """Diumenge matí (abans 22:00 UTC) → closed."""
    ts = int(datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    assert is_market_open("EURUSD", ts) is False
    print("✓ test_sunday_morning_closed OK")


def test_sunday_evening_open():
    """Diumenge 22:00 UTC → open."""
    ts = int(datetime(2026, 2, 15, 22, 0, 0, tzinfo=timezone.utc).timestamp())
    assert is_market_open("EURUSD", ts) is True
    print("✓ test_sunday_evening_open OK")


def test_monday_open():
    """Dilluns → open."""
    ts = int(datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    assert is_market_open("EURUSD", ts) is True
    assert is_market_open("GBPUSD", ts) is True
    print("✓ test_monday_open OK")


def test_friday_after_close_closed():
    """Divendres 23:00 UTC → closed (tancat des de 22:00)."""
    ts = int(datetime(2026, 2, 13, 23, 0, 0, tzinfo=timezone.utc).timestamp())
    assert is_market_open("EURUSD", ts) is False
    print("✓ test_friday_after_close_closed OK")


def test_closed_intervals_weekend():
    """closed_intervals_between retorna intervals al cap de setmana."""
    # Dissabte 00:00 - Diumenge 23:59
    from_ts = int(datetime(2026, 2, 14, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    to_ts = int(datetime(2026, 2, 16, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    intervals = closed_intervals_between("EURUSD", from_ts, to_ts)
    assert len(intervals) >= 1
    closed_mins = count_closed_minutes_between("EURUSD", from_ts, to_ts)
    assert closed_mins > 0
    print("✓ test_closed_intervals_weekend OK")


def main():
    test_saturday_closed()
    test_sunday_morning_closed()
    test_sunday_evening_open()
    test_monday_open()
    test_friday_after_close_closed()
    test_closed_intervals_weekend()
    print("\n✓ All market_hours FX closed weekend tests passed")


if __name__ == "__main__":
    main()
