"""
T8.33 — TIME_ALIGNMENT_SWEEP: sweep d'offsets per maximitzar matching MT4↔LAB.

Aplica offset (hores) als timestamps MT4 i mesura matched, CONTRACT_SHIFT, EXIT_CASCADE, etc.
Selecciona best_offset determinista: max matched, min shift+cascade, min signal_mismatch, min |offset|.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export, read_lab_trades
from lab.runner.out_compare.trade_diff_analyzer import (
    load_indicators_csv,
    classify_unmatched,
    _find_lab_match,
    run_analysis,
    write_report_json,
    write_report_csv,
    TOL_1D,
)

CSV_COLUMNS = [
    "offset_hours", "matched", "unmatched_mt4", "unmatched_lab",
    "contract_shift", "exit_cascade", "signal_mismatch", "data_missing",
    "first_divergence_time",
]


def _apply_offset_to_mt4(mt4_trades: list[dict], offset_hours: int) -> list[dict]:
    """Retorna còpia de mt4_trades amb entry_time i exit_time desplaçats."""
    delta = timedelta(hours=offset_hours)
    out = []
    for t in mt4_trades:
        c = deepcopy(t)
        c["entry_time"] = c["entry_time"] + delta
        c["exit_time"] = c["exit_time"] + delta
        out.append(c)
    return out


def _run_sweep_iteration(
    mt4_trades: list[dict],
    lab_trades: list[dict],
    indicators: dict,
    tol: timedelta,
    offset_hours: int,
) -> dict:
    """Executa matching per un offset; retorna mètriques."""
    mt4_offset = _apply_offset_to_mt4(mt4_trades, offset_hours)
    lab_entry_times = {t["entry_time"] for t in lab_trades}

    matched = 0
    category_counts = {}
    first_divergence_time: Optional[str] = None

    for mt in mt4_offset:
        lab_match = _find_lab_match(mt["entry_time"], lab_trades, tol)
        if lab_match:
            matched += 1
        else:
            category, details = classify_unmatched(mt, lab_trades, indicators, lab_entry_times)
            category_counts[category] = category_counts.get(category, 0) + 1
            if first_divergence_time is None and details.get("has_indicators_row"):
                first_divergence_time = details.get("mt4_entry_utc", "")

    n_mt4 = len(mt4_trades)
    n_lab = len(lab_trades)
    unmatched_mt4 = n_mt4 - matched
    unmatched_lab = n_lab - matched  # 1:1 matching

    return {
        "offset_hours": offset_hours,
        "matched": matched,
        "unmatched_mt4": unmatched_mt4,
        "unmatched_lab": max(0, len(lab_trades) - matched),
        "contract_shift": category_counts.get("CONTRACT_SHIFT", 0),
        "exit_cascade": category_counts.get("EXIT_CASCADE", 0),
        "signal_mismatch": category_counts.get("SIGNAL_MISMATCH", 0),
        "data_missing": category_counts.get("DATA_MISSING", 0),
        "first_divergence_time": first_divergence_time or "",
    }


def _select_best_offset(rows: list[dict]) -> int:
    """
    Criteri: 1) max matched  2) min contract_shift+exit_cascade  3) min signal_mismatch  4) min |offset|
    """
    def score(r: dict) -> tuple:
        m = r["matched"]
        bad = r["contract_shift"] + r["exit_cascade"]
        sm = r["signal_mismatch"]
        abs_off = abs(r["offset_hours"])
        return (-m, bad, sm, abs_off)  # negatiu matched per maximitzar

    best = min(rows, key=score)
    return best["offset_hours"]


def run_sweep(
    mt4_path: Path,
    lab_path: Path,
    indicators_path: Path,
    out_dir: Path,
    offset_min: int = -12,
    offset_max: int = 12,
    offset_step: int = 1,
    tol_days: int = 1,
    dry_run: bool = False,
) -> dict:
    mt4_trades = read_sq_export(mt4_path, "MT4")
    lab_trades = read_lab_trades(lab_path)
    indicators = load_indicators_csv(indicators_path)
    tol = timedelta(days=tol_days)

    rows = []
    total = (offset_max - offset_min) // offset_step + 1
    for i, offset_h in enumerate(range(offset_min, offset_max + 1, offset_step)):
        print(f"STEP 1/3 offset {i + 1}/{total} ({offset_h:+d}h)...", end=" ")
        row = _run_sweep_iteration(mt4_trades, lab_trades, indicators, tol, offset_h)
        rows.append(row)
        print(f"matched={row['matched']}")

    best_offset = _select_best_offset(rows)
    report = {
        "offset_min": offset_min,
        "offset_max": offset_max,
        "offset_step": offset_step,
        "matching_tol_days": tol_days,
        "best_offset": best_offset,
        "selection_criteria": "max matched, min contract_shift+exit_cascade, min signal_mismatch, min |offset|",
        "rows": rows,
        "n_mt4": len(mt4_trades),
        "n_lab": len(lab_trades),
    }

    if dry_run:
        print(f"\n[DRY-RUN] best_offset={best_offset}")
        return report

    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "time_alignment_sweep.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    report_path = out_dir / "time_alignment_report.json"
    report_out = {k: v for k, v in report.items() if k != "rows"}
    report_out["rows_count"] = len(rows)
    report_path.write_text(json.dumps(report_out, indent=2, ensure_ascii=False), encoding="utf-8")

    best_path = out_dir / "best_offset.txt"
    best_path.write_text(str(best_offset), encoding="utf-8")

    # Opcional: trade_diff_report per best_offset
    print("STEP 2/3 Generant trade_diff_report_best_offset...")
    diff_report = run_analysis(
        mt4_path, lab_path, indicators_path, out_dir,
        tol=tol,
        offset_hours=best_offset,
    )
    write_report_json(diff_report, out_dir / "trade_diff_report_best_offset.json")
    write_report_csv(diff_report, out_dir / "trade_diff_report_best_offset.csv")
    print("  OK")

    print(f"\nbest_offset = {best_offset}")
    print(f"Artifacts → {out_dir}/")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.33 Time Alignment Sweep")
    parser.add_argument("--mt4-csv", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument(
        "--lab-trades",
        default="lab/runner/out_compare/contract_open_i_mt4_baropen/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv",
    )
    parser.add_argument("--indicators", default="lab/runner/out_compare/indicators_LAB_full.csv")
    parser.add_argument("--offset-min", type=int, default=-12)
    parser.add_argument("--offset-max", type=int, default=12)
    parser.add_argument("--offset-step", type=int, default=1)
    parser.add_argument("--matching-tol-days", type=int, default=1)
    parser.add_argument(
        "--outdir",
        default="lab/runner/out_compare/artifacts/T8.33/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    mt4_path = root / args.mt4_csv
    lab_path = root / args.lab_trades
    indicators_path = root / args.indicators
    out_dir = root / args.outdir

    if not mt4_path.exists():
        print(f"ERROR: MT4 CSV no trobat: {mt4_path}")
        return 1
    if not lab_path.exists():
        print(f"ERROR: LAB trades no trobat: {lab_path}")
        return 1
    if not indicators_path.exists():
        print("ERROR: Indicators CSV no trobat; run T8.31 export.")
        return 1

    run_sweep(
        mt4_path, lab_path, indicators_path, out_dir,
        offset_min=args.offset_min,
        offset_max=args.offset_max,
        offset_step=args.offset_step,
        tol_days=args.matching_tol_days,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
