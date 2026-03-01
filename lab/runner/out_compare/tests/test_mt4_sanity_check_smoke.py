"""
T8.35 — Smoke test per mt4_sanity_check.

Cas 1: entries exactes a boundary → best_day_offset_h correcte
Cas 2: dos trades solapats → max_concurrency == 2, n_overlaps == 1
Cas 3: no overlaps → max_concurrency == 1
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.out_compare.mt4_sanity_check import (
    run_check,
    step1_offset_scores,
    step1_best_with_tiebreak,
    step2_concurrency,
)


SQ_FMT = "%Y.%m.%d %H:%M:%S"
UTC_OFFSET = __import__("datetime").timedelta(hours=5)


def _parse_sq(s: str) -> datetime:
    dt = datetime.strptime(s.strip(), SQ_FMT)
    return (dt + UTC_OFFSET).replace(tzinfo=timezone.utc)


def _make_mt4_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Crea MT4 CSV amb format SQ."""
    p = tmp_path / "mt4.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Ticket", "Symbol", "Type", "Open time", "Open price", "Size",
                    "Close time", "Close price", "Profit/Loss", "Balance",
                    "Sample type", "Close type", "MAE ($)", "MFE ($)", "Time in trade", "Comment"])
        for r in rows:
            w.writerow([
                r.get("ticket", 1), r.get("symbol", "EURUSD"), "Buy",
                r["open_time"], r.get("open_price", "1.29"), "1",
                r["close_time"], r.get("close_price", "1.30"), "0", "1000",
                "0", "PT", "0", "0", "0", "",
            ])
    return p


def test_entries_at_boundary_best_offset(tmp_path):
    """Entries exactes a 05:00 UTC → best_day_offset_h = 5."""
    rows = [
        {"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.15 00:00:00"},
        {"open_time": "2007.01.16 00:00:00", "close_time": "2007.01.18 00:00:00"},
    ]
    mt4_path = _make_mt4_csv(tmp_path, rows)
    out_dir = tmp_path / "out"
    report = run_check(mt4_path, out_dir, expected_day_offset_h=5, tolerance_seconds=60)
    assert report["best_day_offset_h"] == 5


def test_two_overlapping_trades(tmp_path):
    """Dos trades solapats → max_concurrency == 2, n_overlaps >= 1."""
    rows = [
        {"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.20 00:00:00"},
        {"open_time": "2007.01.15 00:00:00", "close_time": "2007.01.18 00:00:00"},
    ]
    mt4_path = _make_mt4_csv(tmp_path, rows)
    out_dir = tmp_path / "out"
    report = run_check(mt4_path, out_dir)
    assert report["max_concurrency"] == 2
    assert report["n_overlaps"] >= 1


def test_no_overlaps_max_concurrency_one(tmp_path):
    """Trades sense solapament → max_concurrency == 1."""
    rows = [
        {"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.14 00:00:00"},
        {"open_time": "2007.01.16 00:00:00", "close_time": "2007.01.18 00:00:00"},
    ]
    mt4_path = _make_mt4_csv(tmp_path, rows)
    out_dir = tmp_path / "out"
    report = run_check(mt4_path, out_dir)
    assert report["max_concurrency"] == 1
    assert report["n_overlaps"] == 0
