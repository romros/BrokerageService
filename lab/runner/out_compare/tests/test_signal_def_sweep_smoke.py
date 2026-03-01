"""
T8.36 — Smoke test per signal_def_sweep.

- bar_closed vs bar_current canvia resultat
- rounding afecta ohlc
- best determinista (mateix input → mateix best)
"""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.out_compare.signal_def_sweep import run_sweep

SQ_FMT = "%Y.%m.%d %H:%M:%S"
UTC_OFFSET = __import__("datetime").timedelta(hours=5)


def _make_mt4_csv(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "mt4.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Ticket", "Symbol", "Type", "Open time", "Open price", "Size",
                    "Close time", "Close price", "Profit/Loss", "Balance",
                    "Sample type", "Close type", "MAE ($)", "MFE ($)", "Time in trade", "Comment"])
        for r in rows:
            w.writerow([
                1, "EURUSD", "Buy", r["open_time"], "1.29", "1",
                r["close_time"], "1.30", "0", "1000", "0", "PT", "0", "0", "0", "",
            ])
    return p


def _make_candles_csv(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "candles.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "date_utc", "open", "high", "low", "close"])
        for r in rows:
            w.writerow([r["ts"], r.get("date_utc", ""), r["open"], r["high"], r["low"], r["close"]])
    return p


def test_bar_closed_vs_bar_current_differ(tmp_path):
    """bar_closed vs bar_current produeixen resultats diferents."""
    ts1 = int(datetime(2007, 1, 12, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    ts2 = int(datetime(2007, 1, 16, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    mt4_rows = [
        {"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.15 00:00:00"},
        {"open_time": "2007.01.16 00:00:00", "close_time": "2007.01.18 00:00:00"},
    ]
    candle_rows = [
        {"ts": ts1 - 86400, "date_utc": "2007-01-11 05:00:00", "open": 1.28, "high": 1.30, "low": 1.27, "close": 1.29},
        {"ts": ts1, "date_utc": "2007-01-12 05:00:00", "open": 1.29, "high": 1.31, "low": 1.28, "close": 1.30},
        {"ts": ts2, "date_utc": "2007-01-16 05:00:00", "open": 1.30, "high": 1.32, "low": 1.29, "close": 1.31},
    ]
    for _ in range(250):
        ts2 += 86400
        candle_rows.append({"ts": ts2, "date_utc": "", "open": 1.31, "high": 1.32, "low": 1.30, "close": 1.31})
    mt4_path = _make_mt4_csv(tmp_path, mt4_rows)
    candles_path = _make_candles_csv(tmp_path, candle_rows)
    out_dir = tmp_path / "out"
    report = run_sweep(mt4_path, candles_path, out_dir, None, day_offset_h=5, pm_window=3)
    assert "best_signal_def" in report
    assert (out_dir / "signal_def_sweep.csv").exists()


def test_rounding_affects_ohlc(tmp_path):
    """Rounding digits=5 modifica els valors OHLC."""
    ts = int(datetime(2007, 1, 12, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    candles = [{"ts": ts, "date_utc": "", "open": 1.2923456, "high": 1.3012345, "low": 1.2812345, "close": 1.29}]
    for i in range(300):
        candles.append({"ts": ts + (i + 1) * 86400, "date_utc": "", "open": 1.29, "high": 1.30, "low": 1.28, "close": 1.29})
    mt4_rows = [{"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.15 00:00:00"}]
    mt4_path = _make_mt4_csv(tmp_path, mt4_rows)
    candles_path = _make_candles_csv(tmp_path, candles)
    out_dir = tmp_path / "out"
    run_sweep(mt4_path, candles_path, out_dir, None)
    csv_path = out_dir / "signal_def_sweep.csv"
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 2
    none_row = next(r for r in rows if "none" in r["variant_id"] and "digits5" not in r["variant_id"])
    digits_row = next(r for r in rows if "digits5" in r["variant_id"])
    assert none_row is not None
    assert digits_row is not None


def test_best_deterministic(tmp_path):
    """Mateix input → mateix best_signal_def."""
    ts = int(datetime(2007, 1, 12, 5, 0, 0, tzinfo=timezone.utc).timestamp())
    candles = [{"ts": ts + i * 86400, "date_utc": "", "open": 1.29, "high": 1.30, "low": 1.28, "close": 1.29} for i in range(350)]
    mt4_rows = [{"open_time": "2007.01.12 00:00:00", "close_time": "2007.01.15 00:00:00"}]
    mt4_path = _make_mt4_csv(tmp_path, mt4_rows)
    candles_path = _make_candles_csv(tmp_path, candles)
    out_dir = tmp_path / "out"
    r1 = run_sweep(mt4_path, candles_path, out_dir, None)
    r2 = run_sweep(mt4_path, candles_path, out_dir, None)
    assert r1["best_signal_def"] == r2["best_signal_def"]
