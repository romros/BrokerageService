#!/usr/bin/env python3
"""
Missing ignora minuts tancats — unit tests (0-network)

missing_minutes_24h no penalitza minuts en intervals closed.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.market_hours.fx_24_5 import count_closed_minutes_between


def test_weekend_has_closed_minutes():
    """Cap de setmana té molts minuts tancats."""
    from_ts = int(datetime(2026, 2, 14, 0, 0, 0, tzinfo=timezone.utc).timestamp())  # dissabte
    to_ts = from_ts + 48 * 3600
    closed = count_closed_minutes_between("EURUSD", from_ts, to_ts)
    assert closed > 1000
    print("✓ test_weekend_has_closed_minutes OK")


def test_weekday_few_closed():
    """Dilluns-Dijous té 0 minuts tancats (en 24h)."""
    from_ts = int(datetime(2026, 2, 16, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    to_ts = from_ts + 24 * 3600
    closed = count_closed_minutes_between("EURUSD", from_ts, to_ts)
    assert closed == 0
    print("✓ test_weekday_few_closed OK")


def main():
    test_weekend_has_closed_minutes()
    test_weekday_few_closed()
    print("\n✓ All missing_ignores_closed_minutes tests passed")


if __name__ == "__main__":
    main()
