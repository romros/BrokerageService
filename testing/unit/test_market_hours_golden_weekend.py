#!/usr/bin/env python3
"""
Golden tests de cap de setmana — TOTS els perfils (0-network).

Evita regressions del bug "XAUUSD/DAXEUR/SPXUSD/NVDAUSD oberts el dissabte".

Casos canònics:
  - Dissabte 01:00 ET → closed per TOTS els perfils
  - Diumenge 17:30 ET → FX open / XAU+índexs closed (obren 18:00 ET)
  - Diumenge 18:00 ET → XAU+índexs open
  - Diumenge 17:00 ET → FX open (s'obre exactament a 17:00 ET)
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


def _check(sym: str, dt_ny: datetime, expected_state: str, expected_reason: str = None, label: str = "") -> None:
    ts = int(dt_ny.timestamp())
    r = get_market_state_ny(sym, ts)
    assert r.state == expected_state, (
        f"[{label}] {sym} @ {dt_ny.strftime('%a %H:%M ET')}: "
        f"expected state={expected_state!r}, got {r.state!r} (reason={r.reason!r})"
    )
    if expected_reason is not None:
        assert r.reason == expected_reason, (
            f"[{label}] {sym} @ {dt_ny.strftime('%a %H:%M ET')}: "
            f"expected reason={expected_reason!r}, got {r.reason!r}"
        )


def test_golden_saturday_01h_all_closed():
    """Dissabte 01:00 ET → closed per TOTS els perfils (antic bug: XAU/índexs eren open)."""
    dt = datetime(2026, 2, 21, 1, 0, 0, tzinfo=NY_TZ)  # Dissabte
    for sym in ("EURUSD", "USDJPY", "GBPUSD", "XAUUSD", "DAXEUR", "SPXUSD", "GOOGUSD", "NVDAUSD"):
        _check(sym, dt, "closed", label="Dis 01:00 ET")
    print("✓ test_golden_saturday_01h_all_closed passed")


def test_golden_saturday_12h_all_closed():
    """Dissabte 12:00 ET → closed per TOTS els perfils."""
    dt = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)
    for sym in ("EURUSD", "USDJPY", "GBPUSD", "XAUUSD", "DAXEUR", "SPXUSD", "GOOGUSD", "NVDAUSD"):
        _check(sym, dt, "closed", label="Dis 12:00 ET")
    print("✓ test_golden_saturday_12h_all_closed passed")


def test_golden_sunday_1730_fx_open_xau_closed():
    """Diumenge 17:30 ET: FX open (17:00 ET) però XAU/índexs closed (obren 18:00 ET)."""
    dt = datetime(2026, 2, 22, 17, 30, 0, tzinfo=NY_TZ)  # Diumenge
    # FX: obert (obre a les 17:00 ET diumenge)
    for sym in ("EURUSD", "USDJPY", "GBPUSD"):
        _check(sym, dt, "open", label="Diu 17:30 ET FX")
    # XAU/índexs: tancat (obren 18:00 ET)
    for sym in ("XAUUSD", "DAXEUR", "SPXUSD"):
        _check(sym, dt, "closed", "weekend", label="Diu 17:30 ET XAU/idx")
    # Equities: tancat (RTH weekday only)
    for sym in ("GOOGUSD", "NVDAUSD"):
        _check(sym, dt, "closed", "weekend", label="Diu 17:30 ET equities")
    print("✓ test_golden_sunday_1730_fx_open_xau_closed passed")


def test_golden_sunday_1800_xau_opens():
    """Diumenge 18:00 ET: XAU i índexs obren."""
    dt = datetime(2026, 2, 22, 18, 0, 0, tzinfo=NY_TZ)  # Diumenge
    for sym in ("XAUUSD", "DAXEUR", "SPXUSD"):
        _check(sym, dt, "open", label="Diu 18:00 ET XAU/idx open")
    print("✓ test_golden_sunday_1800_xau_opens passed")


def test_golden_sunday_fx_opens_at_1700():
    """Diumenge 17:00 ET: FX obre exactament."""
    dt = datetime(2026, 2, 22, 17, 0, 0, tzinfo=NY_TZ)  # Diumenge
    for sym in ("EURUSD", "USDJPY", "GBPUSD"):
        _check(sym, dt, "open", label="Diu 17:00 ET FX open")
    # XAU/índexs encara tancats (obren 18:00)
    for sym in ("XAUUSD", "DAXEUR", "SPXUSD"):
        _check(sym, dt, "closed", label="Diu 17:00 ET XAU closed")
    print("✓ test_golden_sunday_fx_opens_at_1700 passed")


def test_golden_next_open_xau_saturday():
    """XAUUSD dissabte → next_open apunta a diumenge 18:00 ET."""
    dt = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)  # Dissabte
    ts = int(dt.timestamp())
    r = get_market_state_ny("XAUUSD", ts)
    assert r.state == "closed"
    assert r.next_open_local is not None, "next_open_local hauria de ser present el dissabte"
    assert "18:00" in r.next_open_local, f"next_open hauria de ser 18:00 NY, got {r.next_open_local!r}"
    print(f"✓ test_golden_next_open_xau_saturday passed (next_open={r.next_open_local})")


def test_golden_next_open_nvda_saturday():
    """NVDAUSD dissabte → next_open apunta a dilluns 09:31 ET."""
    dt = datetime(2026, 2, 21, 12, 0, 0, tzinfo=NY_TZ)  # Dissabte
    ts = int(dt.timestamp())
    r = get_market_state_ny("NVDAUSD", ts)
    assert r.state == "closed"
    assert r.next_open_local is not None, "next_open_local hauria de ser present el dissabte"
    assert "09:31" in r.next_open_local, f"next_open hauria de ser 09:31 NY, got {r.next_open_local!r}"
    print(f"✓ test_golden_next_open_nvda_saturday passed (next_open={r.next_open_local})")


def main() -> int:
    test_golden_saturday_01h_all_closed()
    test_golden_saturday_12h_all_closed()
    test_golden_sunday_1730_fx_open_xau_closed()
    test_golden_sunday_1800_xau_opens()
    test_golden_sunday_fx_opens_at_1700()
    test_golden_next_open_xau_saturday()
    test_golden_next_open_nvda_saturday()
    print("OK test_market_hours_golden_weekend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
