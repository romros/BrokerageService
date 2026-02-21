#!/usr/bin/env python3
"""Realtime DataLayer — DAXEUR/SPXUSD 24/5 + break diari 17:00–18:00 NY (0-network)."""

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
    """17:00–18:00 NY (dia laborable) = closed (daily_break), next_open=18:00."""
    dt_ny = datetime(2026, 2, 18, 17, 30, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "closed", f"{sym} expected closed, got {r.state}"
        assert r.reason == "daily_break", f"{sym} expected daily_break, got {r.reason}"
        assert "18:00" in (r.next_open_local or ""), f"{sym} next_open hauria de ser 18:00 NY, got {r.next_open_local}"
    print("✓ test_indices_break_closed passed")


def test_indices_open():
    """Abans 17:00 NY (dia laborable) = open."""
    dt_ny = datetime(2026, 2, 18, 10, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "open", f"{sym} expected open, got {r.state}"
    print("✓ test_indices_open passed")


def test_indices_open_after_break():
    """18:00 NY (dia laborable) = open (break finalitzat)."""
    dt_ny = datetime(2026, 2, 18, 18, 0, 0, tzinfo=NY_TZ)  # Dimecres
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "open", f"{sym} expected open at 18:00, got {r.state}"
    print("✓ test_indices_open_after_break passed")


def test_indices_weekend_saturday_closed():
    """Dissabte (tot el dia) = closed (weekend)."""
    dt_ny = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)  # Dissabte
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "closed", f"{sym} expected closed on Saturday, got {r.state}"
        assert r.reason == "weekend", f"{sym} expected weekend, got {r.reason}"
        assert r.next_open_local is not None
        assert "18:00" in (r.next_open_local or ""), f"{sym} next_open hauria de ser diumenge 18:00 NY, got {r.next_open_local}"
    print("✓ test_indices_weekend_saturday_closed passed")


def test_indices_weekend_sunday_before_open():
    """Diumenge <18:00 NY = closed (weekend)."""
    dt_ny = datetime(2026, 2, 22, 12, 0, 0, tzinfo=NY_TZ)  # Diumenge
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "closed", f"{sym} expected closed Sunday before 18:00, got {r.state}"
        assert r.reason == "weekend", f"{sym} expected weekend, got {r.reason}"
    print("✓ test_indices_weekend_sunday_before_open passed")


def test_indices_weekend_sunday_at_open():
    """Diumenge 18:00 NY = open."""
    dt_ny = datetime(2026, 2, 22, 18, 0, 0, tzinfo=NY_TZ)  # Diumenge
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "open", f"{sym} expected open Sunday at 18:00, got {r.state}"
    print("✓ test_indices_weekend_sunday_at_open passed")


def test_indices_friday_closes_at_17():
    """Divendres 17:00 NY = closed (weekend, no daily_break)."""
    dt_ny = datetime(2026, 2, 27, 17, 0, 0, tzinfo=NY_TZ)  # Divendres
    ts = int(dt_ny.timestamp())
    for sym in ("DAXEUR", "SPXUSD"):
        r = get_market_state_ny(sym, ts)
        assert r.state == "closed", f"{sym} expected closed Friday at 17:00, got {r.state}"
        assert r.reason == "weekend", f"{sym} expected weekend on Friday close, got {r.reason}"
    print("✓ test_indices_friday_closes_at_17 passed")


def main() -> int:
    test_indices_break_closed()
    test_indices_open()
    test_indices_open_after_break()
    test_indices_weekend_saturday_closed()
    test_indices_weekend_sunday_before_open()
    test_indices_weekend_sunday_at_open()
    test_indices_friday_closes_at_17()
    print("OK test_market_hours_indices_break_ny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
