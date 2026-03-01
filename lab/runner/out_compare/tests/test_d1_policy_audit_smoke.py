"""
T8.34 — Smoke test per d1_policy_audit.

Comprova: drop_sunday elimina correctament; merge_sunday_into_monday conserva close dilluns i incorpora rang.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.out_compare.d1_policy_audit import (
    policy_drop_sunday,
    policy_merge_sunday_into_monday,
    _ts_to_sunday_ny,
)


def _make_fixture() -> list[dict]:
    """3 bars: Fri, Sat, Sun (NY). 2007-01-05 05:00 UTC = Fri 00:00 NY, 2007-01-06 = Sat, 2007-01-07 = Sun."""
    ts_fri = int(datetime(2007, 1, 5, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ts_sat = int(datetime(2007, 1, 6, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ts_sun = int(datetime(2007, 1, 7, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ts_mon = int(datetime(2007, 1, 8, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    return [
        {"ts": ts_fri, "open": 1.28, "high": 1.30, "low": 1.27, "close": 1.29, "is_sunday_ny": False},
        {"ts": ts_sat, "open": 1.29, "high": 1.31, "low": 1.28, "close": 1.30, "is_sunday_ny": False},
        {"ts": ts_sun, "open": 1.30, "high": 1.32, "low": 1.29, "close": 1.31, "is_sunday_ny": True},
        {"ts": ts_mon, "open": 1.31, "high": 1.33, "low": 1.30, "close": 1.32, "is_sunday_ny": False},
    ]


def test_drop_sunday_eliminates_sunday():
    """drop_sunday elimina barres diumenge."""
    rows = _make_fixture()
    out = policy_drop_sunday(rows)
    assert len(out) == 3
    ts_out = [r["ts"] for r in out]
    ts_sun = int(datetime(2007, 1, 7, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    assert ts_sun not in ts_out


def test_merge_sunday_conserves_monday_close():
    """merge_sunday_into_monday conserva close de dilluns."""
    rows = _make_fixture()
    out = policy_merge_sunday_into_monday(rows)
    ts_mon = int(datetime(2007, 1, 8, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    mon = next(r for r in out if r["ts"] == ts_mon)
    assert mon["close"] == 1.32


def test_merge_sunday_incorporates_range():
    """merge incorpora open diumenge, high=max, low=min."""
    rows = _make_fixture()
    out = policy_merge_sunday_into_monday(rows)
    ts_mon = int(datetime(2007, 1, 8, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    mon = next(r for r in out if r["ts"] == ts_mon)
    assert mon["open"] == 1.30
    assert mon["high"] == 1.33
    assert mon["low"] == 1.29
