"""
T8.35 — MT4 Boundary & Concurrency Sanity Check.

Inferència best_day_offset_h i detecció de solapaments (max_concurrency).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export


def _bar_start_ts(ts: float, h: int) -> float:
    """bar_start per day_offset_h: ts_shifted = ts - h*3600, day = floor/86400*86400, bar_start = day + h*3600."""
    ts_shifted = ts - h * 3600
    day = int(ts_shifted // 86400) * 86400
    return day + h * 3600


def step1_offset_scores(trades: list[dict], tolerance_seconds: int) -> tuple[dict[int, int], int]:
    """Per cada h 0..23, compta entries alineats. Retorna (offset_scores, best_day_offset_h)."""
    offset_scores = {h: 0 for h in range(24)}
    for t in trades:
        ts = t["entry_time"].timestamp()
        for h in range(24):
            bar_start = _bar_start_ts(ts, h)
            delta = abs(ts - bar_start)
            if delta <= tolerance_seconds:
                offset_scores[h] += 1
    best_h = max(offset_scores, key=lambda x: offset_scores[x])
    return offset_scores, best_h


def step1_best_with_tiebreak(
    offset_scores: dict[int, int],
    expected_h: int,
) -> int:
    """Tie-break: min abs(h - expected_h), després min h."""
    max_score = max(offset_scores.values())
    candidates = [h for h in range(24) if offset_scores[h] == max_score]
    return min(candidates, key=lambda h: (abs(h - expected_h), h))


def step2_concurrency(trades: list[dict]) -> tuple[int, int, list[dict]]:
    """max_concurrency, n_overlaps, overlap_examples (top N)."""
    sorted_trades = sorted(trades, key=lambda t: t["entry_time"])
    events = []
    for i, t in enumerate(sorted_trades):
        events.append((t["entry_time"].timestamp(), 1, i))
        events.append((t["exit_time"].timestamp(), -1, i))
    events.sort(key=lambda e: (e[0], e[1]))

    cur = 0
    max_conc = 0
    for ts, delta, _ in events:
        cur += delta
        max_conc = max(max_conc, cur)

    overlaps = []
    for i in range(len(sorted_trades)):
        ti = sorted_trades[i]
        ei = ti["entry_time"].timestamp()
        xi = ti["exit_time"].timestamp()
        for j in range(i + 1, len(sorted_trades)):
            tj = sorted_trades[j]
            ej = tj["entry_time"].timestamp()
            xj = tj["exit_time"].timestamp()
            if ej >= xi:
                break
            if ei < xj:
                overlap_s = min(xi, xj) - max(ei, ej)
                if overlap_s > 0:
                    overlaps.append({
                        "trade_id_a": i + 1,
                        "trade_id_b": j + 1,
                        "entry_a": ti["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "exit_a": ti["exit_time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "entry_b": tj["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "exit_b": tj["exit_time"].strftime("%Y-%m-%d %H:%M:%S"),
                        "overlap_seconds": int(overlap_s),
                    })

    overlaps.sort(key=lambda x: -x["overlap_seconds"])
    return max_conc, len(overlaps), overlaps


def derive_next_step(
    best_day_offset_h: int,
    expected_day_offset_h: int,
    max_concurrency: int,
) -> tuple[str, str]:
    """(next_step, notes)."""
    if best_day_offset_h != expected_day_offset_h:
        return "DAY_OFFSET_SWEEP", f"best_day_offset_h={best_day_offset_h} != expected {expected_day_offset_h}"
    if max_concurrency > 1:
        return "CONCURRENCY_POLICY_FIX", f"max_concurrency={max_concurrency} > 1"
    return "RSI_VARIANT_SWEEP", "boundary i concurrency consistents amb LAB"


def run_check(
    mt4_path: Path,
    out_dir: Path,
    expected_day_offset_h: int = 5,
    tolerance_seconds: int = 60,
    top_overlaps: int = 10,
) -> dict:
    print("STEP 1/2 Inferència best_day_offset_h...")
    trades = read_sq_export(mt4_path, "MT4")
    offset_scores, _ = step1_offset_scores(trades, tolerance_seconds)
    best_day_offset_h = step1_best_with_tiebreak(offset_scores, expected_day_offset_h)
    print(f"  best_day_offset_h = {best_day_offset_h}")

    print("STEP 2/2 Concurrency / overlaps...")
    max_concurrency, n_overlaps, overlap_examples = step2_concurrency(trades)
    print(f"  max_concurrency = {max_concurrency}, n_overlaps = {n_overlaps}")

    next_step, notes = derive_next_step(best_day_offset_h, expected_day_offset_h, max_concurrency)

    report = {
        "best_day_offset_h": best_day_offset_h,
        "offset_scores": offset_scores,
        "max_concurrency": max_concurrency,
        "n_overlaps": n_overlaps,
        "next_step": next_step,
        "notes": notes,
        "n_trades": len(trades),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "mt4_sanity_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = out_dir / "mt4_overlap_examples.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["trade_id_a", "trade_id_b", "entry_a", "exit_a", "entry_b", "exit_b", "overlap_seconds"],
        )
        w.writeheader()
        w.writerows(overlap_examples[:top_overlaps])

    print(f"\nNEXT_STEP = {next_step}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.35 MT4 Sanity Check")
    parser.add_argument("--mt4", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument("--expected-day-offset-h", type=int, default=5)
    parser.add_argument("--tolerance-seconds", type=int, default=60)
    parser.add_argument(
        "--outdir",
        default="lab/runner/out_compare/artifacts/T8.35/eurusd_ema200_rsi35_atr_d1/EURUSD/1d",
    )
    parser.add_argument("--top-overlaps", type=int, default=10)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    mt4_path = root / args.mt4
    out_dir = root / args.outdir

    if not mt4_path.exists():
        print(f"ERROR: MT4 CSV no trobat: {mt4_path}")
        return 1

    run_check(
        mt4_path,
        out_dir,
        expected_day_offset_h=args.expected_day_offset_h,
        tolerance_seconds=args.tolerance_seconds,
        top_overlaps=args.top_overlaps,
    )
    print(f"Artifacts → {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
