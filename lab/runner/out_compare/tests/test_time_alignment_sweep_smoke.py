"""
T8.33 — Smoke test per time_alignment_sweep.

Comprova que genera CSV/JSON i que selecciona best_offset de forma determinista.
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.out_compare.time_alignment_sweep import run_sweep, _select_best_offset


def _make_fixture_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Crea MT4, LAB, indicators mínims."""
    # MT4: 2 trades a 2007-01-12 00:00 UTC-5 = 2007-01-12 05:00 UTC
    mt4_path = tmp_path / "mt4.csv"
    with open(mt4_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Ticket", "Symbol", "Type", "Open time", "Open price", "Size",
                    "Close time", "Close price", "Profit/Loss", "Balance",
                    "Sample type", "Close type", "MAE ($)", "MFE ($)", "Time in trade", "Comment"])
        w.writerow([1, "EURUSD", "Buy", "2007.01.12 00:00:00", "1.29", "1",
                    "2007.01.15 00:00:00", "1.30", "100", "1000", "0", "PT", "0", "0", "72", ""])
        w.writerow([2, "EURUSD", "Buy", "2007.01.16 00:00:00", "1.30", "1",
                    "2007.01.18 00:00:00", "1.31", "100", "1100", "0", "PT", "0", "0", "48", ""])

    # LAB: 2 trades a 05:00 UTC (match directe)
    lab_path = tmp_path / "lab" / "trades.csv"
    lab_path.parent.mkdir(exist_ok=True)
    ts1 = int(datetime(2007, 1, 12, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ts2 = int(datetime(2007, 1, 16, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ex1 = int(datetime(2007, 1, 15, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ex2 = int(datetime(2007, 1, 18, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    with open(lab_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["entry_ts", "entry_price", "exit_ts", "exit_price", "pnl_pct", "reason"])
        w.writeheader()
        w.writerow({"entry_ts": ts1, "entry_price": 1.29, "exit_ts": ex1, "exit_price": 1.30, "pnl_pct": 0.1, "reason": "tp"})
        w.writerow({"entry_ts": ts2, "entry_price": 1.30, "exit_ts": ex2, "exit_price": 1.31, "pnl_pct": 0.1, "reason": "tp"})

    # Indicators: bars 2007-01-12 05:00, 2007-01-16 05:00 (signal=1)
    ind_path = tmp_path / "indicators.csv"
    bar_ts1 = 1168578000  # 2007-01-12 05:00 UTC
    bar_ts2 = 1168923600  # 2007-01-16 05:00 UTC
    with open(ind_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "date_utc", "open", "high", "low", "close", "ema200_lab", "rsi14_lab", "atr14_lab", "signal_lab"])
        w.writerow([bar_ts1, "2007-01-12 05:00:00", 1.28, 1.30, 1.27, 1.29, 1.27, 30.0, 0.01, 1])
        w.writerow([bar_ts2, "2007-01-16 05:00:00", 1.29, 1.31, 1.28, 1.30, 1.28, 32.0, 0.01, 1])

    return mt4_path, lab_path, ind_path


def test_sweep_generates_csv_json(tmp_path):
    """run_sweep genera time_alignment_sweep.csv, time_alignment_report.json, best_offset.txt."""
    mt4, lab, ind = _make_fixture_dir(tmp_path)
    out_dir = tmp_path / "out"
    run_sweep(mt4, lab, ind, out_dir, offset_min=-1, offset_max=1, offset_step=1, dry_run=False)

    assert (out_dir / "time_alignment_sweep.csv").exists()
    assert (out_dir / "time_alignment_report.json").exists()
    assert (out_dir / "best_offset.txt").exists()


def test_best_offset_deterministic(tmp_path):
    """Mateix input → mateix best_offset."""
    mt4, lab, ind = _make_fixture_dir(tmp_path)
    out_dir = tmp_path / "out"
    run_sweep(mt4, lab, ind, out_dir, offset_min=-2, offset_max=2, offset_step=1, dry_run=False)

    best1 = (out_dir / "best_offset.txt").read_text().strip()
    run_sweep(mt4, lab, ind, out_dir, offset_min=-2, offset_max=2, offset_step=1, dry_run=False)
    best2 = (out_dir / "best_offset.txt").read_text().strip()
    assert best1 == best2


def test_select_best_offset_logic():
    """_select_best_offset tria per max matched, min bad, min |offset|."""
    rows = [
        {"offset_hours": -1, "matched": 2, "contract_shift": 0, "exit_cascade": 0, "signal_mismatch": 0},
        {"offset_hours": 0, "matched": 2, "contract_shift": 0, "exit_cascade": 0, "signal_mismatch": 0},
        {"offset_hours": 1, "matched": 1, "contract_shift": 1, "exit_cascade": 0, "signal_mismatch": 0},
    ]
    assert _select_best_offset(rows) == 0  # tie-break min |offset| entre -1 i 0
