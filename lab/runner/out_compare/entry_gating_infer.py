"""
T8.38 — MT4 Entry Gating Inference + Grid.

1. Infer cadència MT4 (bars_between_entries, bars_held, bars_between_exit_and_next_entry)
2. Grid de gating params sobre senyals LAB
3. Tria best_gating_profile per max matched, min |n_lab - n_mt4|, min extra_entries
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export
from lab.runner.out_compare.trade_diff_analyzer import _ts_to_bar_start, load_indicators_csv
from lab.runner.backtest.entry_gating import GatingProfile, simulate_entries_with_gating

DAY_OFFSET_H = 5
TOL_BARS = 0  # match exacte de barra (mateix bar_ts)


def _bar_start_ts(dt: datetime, day_offset_h: int = 5) -> int:
    """Retorna epoch UTC del start de la barra D1."""
    return _ts_to_bar_start(dt, day_offset_h)


def infer_mt4_cadence(mt4_trades: list[dict], day_offset_h: int = 5) -> dict:
    """
    Calcula estadístiques de cadència MT4.
    """
    if len(mt4_trades) < 2:
        return {
            "n_trades": len(mt4_trades),
            "bars_between_entries": [],
            "bars_held": [],
            "bars_between_exit_and_next_entry": [],
            "median_bars_held": 0,
            "median_bars_between_entries": 0,
            "median_bars_after_exit": 0,
        }

    sorted_trades = sorted(mt4_trades, key=lambda t: t["entry_time"])
    bars_between_entries = []
    bars_held = []
    bars_after_exit = []

    for i in range(len(sorted_trades)):
        t = sorted_trades[i]
        entry_ts = _bar_start_ts(t["entry_time"], day_offset_h)
        exit_ts = _bar_start_ts(t["exit_time"], day_offset_h)
        bars_held.append(int((exit_ts - entry_ts) / 86400))

        if i > 0:
            prev = sorted_trades[i - 1]
            prev_exit_ts = _bar_start_ts(prev["exit_time"], day_offset_h)
            bars_between_entries.append(int((entry_ts - prev_exit_ts) / 86400))
            bars_after_exit.append(int((entry_ts - prev_exit_ts) / 86400))

    def median(xs):
        if not xs:
            return 0
        s = sorted(xs)
        m = len(s) // 2
        return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2

    return {
        "n_trades": len(mt4_trades),
        "bars_between_entries": bars_between_entries,
        "bars_held": bars_held,
        "bars_between_exit_and_next_entry": bars_after_exit,
        "median_bars_held": int(median(bars_held)),
        "median_bars_between_entries": int(median(bars_between_entries)) if bars_between_entries else 0,
        "median_bars_after_exit": int(median(bars_after_exit)) if bars_after_exit else 0,
    }


def load_signal_series(indicators_path: Path) -> tuple[list[int], list[int]]:
    """Retorna (bar_ts, signal_true)."""
    rows = load_indicators_csv(indicators_path)
    sorted_items = sorted(rows.items())
    bar_ts = [r[0] for r in sorted_items]
    signal_true = [r[1]["signal_lab"] for r in sorted_items]
    return bar_ts, signal_true


def score_profile(
    profile: GatingProfile,
    bar_ts: list[int],
    signal_true: list[int],
    hold_bars: int,
    mt4_entry_bar_ts: set[int],
) -> dict:
    """
    Simula entrades amb gating i puntua vs MT4.
    Retorna matched, n_entries_lab, extra_entries, score.
    """
    entries = simulate_entries_with_gating(bar_ts, signal_true, profile, hold_bars)
    lab_entry_ts = {bar_ts[i] for i in entries if i < len(bar_ts)}

    matched = len(lab_entry_ts & mt4_entry_bar_ts)
    extra = len(lab_entry_ts) - matched
    n_mt4 = len(mt4_entry_bar_ts)
    n_lab = len(lab_entry_ts)

    return {
        "matched": matched,
        "n_lab": n_lab,
        "n_mt4": n_mt4,
        "extra_entries": extra,
        "profile": profile.to_dict(),
    }


def run_inference(
    mt4_path: Path,
    indicators_path: Path,
    out_dir: Path,
    day_offset_h: int = 5,
) -> dict:
    """Pipeline complet: inferència + grid + best."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Inferència MT4
    mt4_trades = read_sq_export(mt4_path, "MT4")
    cadence = infer_mt4_cadence(mt4_trades, day_offset_h)
    cadence_path = out_dir / "mt4_cadence_report.json"
    with open(cadence_path, "w", encoding="utf-8") as f:
        json.dump(cadence, f, indent=2)
    print(f"  mt4_cadence_report.json: median_bars_held={cadence['median_bars_held']}, "
          f"median_bars_after_exit={cadence['median_bars_after_exit']}")

    hold_bars = max(1, cadence["median_bars_held"])

    # 2. Load LAB signals
    bar_ts, signal_true = load_signal_series(indicators_path)
    mt4_entry_bar_ts = {
        _bar_start_ts(t["entry_time"], day_offset_h)
        for t in mt4_trades
    }
    # Filtrar MT4 entries que estan dins el rang LAB
    ts_set = set(bar_ts)
    mt4_entry_bar_ts = {ts for ts in mt4_entry_bar_ts if ts in ts_set}

    # 3. Grid
    grid_min_bars = [0, 1, 2, 3, 5, 7]
    grid_max_week = [None, 1, 2]
    grid_confirm = [1, 2, 3]

    grid_results = []
    for min_after in grid_min_bars:
        for max_week in grid_max_week:
            for confirm in grid_confirm:
                profile = GatingProfile(
                    min_bars_after_exit=min_after,
                    min_bars_between_entries=0,
                    max_entries_per_week=max_week,
                    confirm_bars=confirm,
                )
                r = score_profile(profile, bar_ts, signal_true, hold_bars, mt4_entry_bar_ts)
                grid_results.append(r)

    # 4. Best per criteri: max matched, min |n_lab - n_mt4|, min extra, tie-break min cooldown
    def key(r):
        return (
            -r["matched"],
            abs(r["n_lab"] - r["n_mt4"]),
            r["extra_entries"],
            r["profile"]["min_bars_after_exit"],
        )

    best = min(grid_results, key=key)
    best_path = out_dir / "best_gating_profile.json"
    with open(best_path, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=2)

    # 5. Grid CSV
    grid_path = out_dir / "entry_gating_grid.csv"
    with open(grid_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "min_bars_after_exit", "max_entries_per_week", "confirm_bars",
            "matched", "n_lab", "n_mt4", "extra_entries",
        ])
        writer.writeheader()
        for r in grid_results:
            writer.writerow({
                "min_bars_after_exit": r["profile"]["min_bars_after_exit"],
                "max_entries_per_week": r["profile"]["max_entries_per_week"] or "",
                "confirm_bars": r["profile"]["confirm_bars"],
                "matched": r["matched"],
                "n_lab": r["n_lab"],
                "n_mt4": r["n_mt4"],
                "extra_entries": r["extra_entries"],
            })

    print(f"  best_gating_profile: matched={best['matched']}, n_lab={best['n_lab']}, "
          f"min_bars_after_exit={best['profile']['min_bars_after_exit']}, "
          f"confirm_bars={best['profile']['confirm_bars']}")

    return {
        "cadence": cadence,
        "best": best,
        "grid_path": str(grid_path),
        "best_path": str(best_path),
    }


def main():
    parser = argparse.ArgumentParser(description="T8.38 Entry gating inference")
    parser.add_argument("--mt4-csv", required=True, type=Path)
    parser.add_argument("--indicators", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--day-offset-h", type=int, default=5)
    args = parser.parse_args()

    print("[T8.38] Entry gating inference...")
    run_inference(args.mt4_csv, args.indicators, args.out_dir, args.day_offset_h)
    print("  OK")


if __name__ == "__main__":
    main()
