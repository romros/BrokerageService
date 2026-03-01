"""
T8.32 — Quick Parity Triage: micro-checks <20s per decidir tipus de divergència.

Micro-checks: TIME_ALIGNMENT, DATA_MISSING, CONTRACT_SHIFT, INDICATOR_VARIANT.
No recalcula indicators; usa trade_diff_report + indicators_LAB_full.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export

EXPECTED_BOUNDARY_HOUR = 5  # 05:00 UTC = D1 MT4 Dukascopy
RSI_THRESHOLD = 35.0
DAY_SECONDS = 86400


def _load_indicators(path: Path) -> tuple[dict[int, dict], list[int]]:
    """ts -> row; sorted_ts per indexar."""
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row["ts"])
                rows[ts] = {
                    "ts": ts,
                    "date_utc": row.get("date_utc", ""),
                    "close": float(row["close"]) if row.get("close") else None,
                    "ema200_lab": float(row["ema200_lab"]) if row.get("ema200_lab") else None,
                    "rsi14_lab": float(row["rsi14_lab"]) if row.get("rsi14_lab") else None,
                    "atr14_lab": float(row["atr14_lab"]) if row.get("atr14_lab") else None,
                    "signal_lab": int(row.get("signal_lab", 0) or 0),
                }
            except (KeyError, ValueError):
                continue
    sorted_ts = sorted(rows.keys())
    return rows, sorted_ts


def _get_divergence_bar(report_path: Path) -> Optional[int]:
    """bar_ts del first_divergence de trade_diff_report.json."""
    if not report_path.exists():
        return None
    data = json.loads(report_path.read_text(encoding="utf-8"))
    fd = data.get("first_divergence")
    if not fd:
        return None
    details = fd.get("details", {})
    return details.get("bar_ts")


def _micro_check_1_time_sanity(mt4_trades: list[dict], n: int) -> dict:
    """Distribució d'hores dels primers N MT4 entries."""
    hours = [t["entry_time"].hour for t in mt4_trades[:n]]
    hour_counts = {}
    for h in hours:
        hour_counts[h] = hour_counts.get(h, 0) + 1
    majority_at_boundary = (
        max(hour_counts.values(), default=0) / max(len(hours), 1) >= 0.6
        and hour_counts.get(EXPECTED_BOUNDARY_HOUR, 0) == max(hour_counts.values(), default=0)
    )
    return {
        "TIME_ALIGNMENT_SUSPECT": not majority_at_boundary,
        "n_trades_checked": len(hours),
        "hour_distribution": hour_counts,
        "expected_boundary_hour": EXPECTED_BOUNDARY_HOUR,
        "majority_at_boundary": majority_at_boundary,
    }


def _micro_check_2_gap(bar_ts: int, indicators: dict[int, dict], sorted_ts: list[int], window: int = 5) -> dict:
    """Finestra t-window..t+window; verifica files i NaNs."""
    if bar_ts not in indicators:
        return {"DATA_MISSING": True, "reason": "divergence_bar_not_in_indicators", "window_rows": 0}
    idx = sorted_ts.index(bar_ts) if bar_ts in sorted_ts else -1
    if idx < 0:
        return {"DATA_MISSING": True, "reason": "bar_ts_not_in_sorted", "window_rows": 0}
    start = max(0, idx - window)
    end = min(len(sorted_ts), idx + window + 1)
    window_ts = sorted_ts[start:end]
    missing = 0
    nans = 0
    for ts in window_ts:
        row = indicators.get(ts, {})
        if not row:
            missing += 1
        else:
            for k in ("close", "ema200_lab", "rsi14_lab"):
                v = row.get(k)
                if v is None or (isinstance(v, float) and str(v) == "nan"):
                    nans += 1
                    break
    return {
        "DATA_MISSING": missing > 2 or nans > len(window_ts) * 0.3,
        "window_rows": len(window_ts),
        "expected_rows": min(2 * window + 1, len(sorted_ts)),
        "missing_rows": missing,
        "rows_with_nan": nans,
        "divergence_bar_ts": bar_ts,
    }


def _micro_check_3_shift(bar_ts: int, indicators: dict[int, dict], sorted_ts: list[int], window: int = 3) -> dict:
    """Signal a t±1, t±2, t±3; si true a adjacent però no a t → CONTRACT_SHIFT_LIKELY."""
    if bar_ts not in indicators:
        return {"CONTRACT_SHIFT_LIKELY": False, "reason": "no_data_at_divergence"}
    idx = sorted_ts.index(bar_ts) if bar_ts in sorted_ts else -1
    if idx < 0:
        return {"CONTRACT_SHIFT_LIKELY": False, "reason": "bar_not_found"}
    signal_at_t = indicators[bar_ts].get("signal_lab", 0) == 1
    signal_at_adjacent = False
    shift_bars = None
    for d in range(1, window + 1):
        for offset in (d, -d):
            i2 = idx + offset
            if 0 <= i2 < len(sorted_ts):
                ts2 = sorted_ts[i2]
                if indicators.get(ts2, {}).get("signal_lab", 0) == 1:
                    signal_at_adjacent = True
                    shift_bars = offset
                    break
        if signal_at_adjacent:
            break
    return {
        "CONTRACT_SHIFT_LIKELY": not signal_at_t and signal_at_adjacent,
        "signal_at_divergence_bar": signal_at_t,
        "signal_at_adjacent": signal_at_adjacent,
        "shift_bars": shift_bars,
        "divergence_bar_ts": bar_ts,
    }


def _micro_check_4_rsi_snapshot(bar_ts: int, indicators: dict[int, dict], sorted_ts: list[int], window: int = 3) -> dict:
    """RSI, EMA, close a t i t±3; si RSI lluny del llindar però crosses a prop."""
    if bar_ts not in indicators:
        return {"rsi_at_t": None, "window": []}
    idx = sorted_ts.index(bar_ts) if bar_ts in sorted_ts else -1
    if idx < 0:
        return {"rsi_at_t": None, "window": []}
    row_t = indicators[bar_ts]
    rsi_t = row_t.get("rsi14_lab")
    close_t = row_t.get("close")
    ema_t = row_t.get("ema200_lab")
    window_rows = []
    for d in range(-window, window + 1):
        i2 = idx + d
        if 0 <= i2 < len(sorted_ts):
            ts2 = sorted_ts[i2]
            r = indicators.get(ts2, {})
            window_rows.append({
                "offset_bars": d,
                "ts": ts2,
                "date_utc": r.get("date_utc", ""),
                "close": r.get("close"),
                "ema200": r.get("ema200_lab"),
                "rsi14": r.get("rsi14_lab"),
                "signal_lab": r.get("signal_lab", 0),
            })
    rsi_far_from_threshold = rsi_t is not None and abs(rsi_t - RSI_THRESHOLD) > 10
    crosses_nearby = any(
        (r.get("rsi14") is not None and r.get("rsi14") < RSI_THRESHOLD)
        for r in window_rows
    )
    return {
        "rsi_at_t": rsi_t,
        "close_at_t": close_t,
        "ema_at_t": ema_t,
        "rsi_threshold": RSI_THRESHOLD,
        "rsi_far_from_threshold": rsi_far_from_threshold,
        "rsi_crosses_nearby": crosses_nearby,
        "INDICATOR_VARIANT_SUSPECT": rsi_far_from_threshold and crosses_nearby,
        "window": window_rows,
    }


def _decide_next_step(checks: dict) -> str:
    """Decideix NEXT_STEP segons els flags."""
    if checks.get("triage_gap_check", {}).get("DATA_MISSING"):
        return "DATA_REPAIR"
    if checks.get("triage_time_sanity", {}).get("TIME_ALIGNMENT_SUSPECT"):
        return "TIME_ALIGNMENT_SWEEP"
    if checks.get("triage_indicator_snapshot", {}).get("INDICATOR_VARIANT_SUSPECT"):
        return "RSI_VARIANT_SWEEP"
    if checks.get("triage_shift_check", {}).get("CONTRACT_SHIFT_LIKELY"):
        return "CONTRACT_SHIFT"
    return "DATA_REPAIR"  # fallback conservador


def run_triage(
    mt4_path: Path,
    indicators_path: Path,
    report_dir: Path,
    trade_diff_report_path: Path,
    n: int = 5,
) -> dict:
    mt4_trades = read_sq_export(mt4_path, "MT4")
    indicators, sorted_ts = _load_indicators(indicators_path)
    bar_ts = _get_divergence_bar(trade_diff_report_path)

    checks = {}


    print("STEP 1/4 Time sanity...")
    checks["triage_time_sanity"] = _micro_check_1_time_sanity(mt4_trades, n)
    print("  OK")

    print("STEP 2/4 Gap check...")
    if bar_ts is not None:
        checks["triage_gap_check"] = _micro_check_2_gap(bar_ts, indicators, sorted_ts)
        # window_around_divergence.csv
        idx = sorted_ts.index(bar_ts) if bar_ts in sorted_ts else -1
        if idx >= 0:
            window_ts = sorted_ts[max(0, idx - 5) : min(len(sorted_ts), idx + 6)]
            csv_path = report_dir / "window_around_divergence.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "date_utc", "close", "ema200_lab", "rsi14_lab", "atr14_lab", "signal_lab"])
                for ts in window_ts:
                    r = indicators.get(ts, {})
                    w.writerow([
                        ts, r.get("date_utc", ""),
                        r.get("close"), r.get("ema200_lab"), r.get("rsi14_lab"),
                        r.get("atr14_lab"), r.get("signal_lab", 0),
                    ])
    else:
        checks["triage_gap_check"] = {"DATA_MISSING": True, "reason": "no_trade_diff_report"}
    print("  OK")

    print("STEP 3/4 Contract shift...")
    if bar_ts is not None:
        checks["triage_shift_check"] = _micro_check_3_shift(bar_ts, indicators, sorted_ts)
    else:
        checks["triage_shift_check"] = {"CONTRACT_SHIFT_LIKELY": False, "reason": "no_divergence_bar"}
    print("  OK")

    print("STEP 4/4 RSI snapshot...")
    if bar_ts is not None:
        snap = _micro_check_4_rsi_snapshot(bar_ts, indicators, sorted_ts)
        # No serialitzar window sencer al JSON (massa gran); simplificar
        snap["window"] = [
            {"offset_bars": r["offset_bars"], "date_utc": r["date_utc"], "rsi14": r["rsi14"], "signal_lab": r["signal_lab"]}
            for r in snap.get("window", [])
        ]
        checks["triage_indicator_snapshot"] = snap
    else:
        checks["triage_indicator_snapshot"] = {"rsi_at_t": None}
    print("  OK")

    next_step = _decide_next_step(checks)
    report = {
        "NEXT_STEP": next_step,
        "divergence_bar_ts": bar_ts,
        "checks": checks,
    }

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.32 Quick Parity Triage")
    parser.add_argument("--mt4", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument("--lab-trades", default="auto")
    parser.add_argument("--indicators", default="auto")
    parser.add_argument("--report", default="lab/runner/out_compare/artifacts/T8.32/triage_report.json")
    parser.add_argument("--n", type=int, default=5, help="Primers N trades per time sanity")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    mt4_path = root / args.mt4
    report_path = root / args.report

    if args.indicators == "auto":
        indicators_path = root / "lab/runner/out_compare/indicators_LAB_full.csv"
    else:
        indicators_path = root / args.indicators

    if not mt4_path.exists():
        print(f"ERROR: MT4 CSV no trobat: {mt4_path}")
        return 1
    if not indicators_path.exists():
        print("ERROR: No indicators found; run T8.31 export or pass --indicators path.")
        return 1

    trade_diff_path = root / "lab/runner/out_compare/trade_diff_report.json"
    if not trade_diff_path.exists():
        print("WARN: trade_diff_report.json no trobat; run T8.31 primer. Usant bar_ts=None.")

    report_dir = report_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    report = run_triage(mt4_path, indicators_path, report_dir, trade_diff_path, n=args.n)

    for name, data in report["checks"].items():
        out = report_dir / f"{name}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    report_out = {k: v for k, v in report.items() if k != "checks"}
    report_out["check_files"] = list(report["checks"].keys())
    report_path.write_text(json.dumps(report_out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nNEXT_STEP = {report['NEXT_STEP']}")
    print(f"Artifacts → {report_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
