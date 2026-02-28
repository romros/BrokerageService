"""
lab/runner/out_compare/compare_indicators.py — T8.21

Compara indicadors MT4 vs LAB barra-a-barra.

Ús:
    python3 lab/runner/out_compare/compare_indicators.py \\
        --lab  lab/runner/out_compare/indicators_lab_YYYY_YYYY.csv \\
        --mt4  lab/runner/out_compare/indicators_mt4_YYYY_YYYY.csv \\
        --out  lab/runner/out_compare/indicator_diff_report.json

Input CSV LAB (generat per export_indicators_csv.py):
    ts, date_utc, open, high, low, close,
    ema200_lab, rsi14_lab, atr14_lab, signal_lab

Input CSV MT4 (exportat manualment des d'MT4/SQ EA):
    ts_utc, date_utc, ema200_mt4, rsi14_mt4, atr14_mt4

    o alternativament (si el timestamp és UTC-5):
    ts_utcm5, date_utcm5, ema200_mt4, rsi14_mt4, atr14_mt4

Output:
    indicator_diff_report.json amb:
    - max_abs_diff per indicador
    - mean_abs_diff per indicador
    - first_diff_bar (primera barra on diff > threshold)
    - n_bars_compared
    - signal_match_rate (si ambdós tenen signal)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Threshold per considerar una diferència "significativa"
EMA_THRESHOLD  = 0.00010   # 1 pip EURUSD
RSI_THRESHOLD  = 0.10      # 0.1 RSI unitats
ATR_THRESHOLD  = 0.00010   # 1 pip EURUSD


# ---------------------------------------------------------------------------
# Lectura CSVs
# ---------------------------------------------------------------------------

def _read_csv_as_dict(path: Path) -> dict[int, dict]:
    """
    Llegeix CSV amb columna 'ts' (epoch UTC) com a clau.
    Retorna {ts: {col: val, ...}}.
    """
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            # Suportem 'ts' o 'ts_utc' o 'ts_utcm5' (UTC-5 → +5h)
            if "ts" in row:
                ts = int(row["ts"])
            elif "ts_utc" in row:
                ts = int(row["ts_utc"])
            elif "ts_utcm5" in row:
                ts = int(row["ts_utcm5"]) + 5 * 3600
            else:
                continue
            rows[ts] = row
    return rows


def _safe_float(val: str) -> Optional[float]:
    if val is None or val.strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Comparació
# ---------------------------------------------------------------------------

def compare_indicators(
    lab_path: Path,
    mt4_path: Path,
    out_path: Path,
) -> int:
    """
    Compara indicadors LAB vs MT4 barra-a-barra.
    Retorna 0=OK, 1=error.
    """
    lab = _read_csv_as_dict(lab_path)
    mt4 = _read_csv_as_dict(mt4_path)

    if not lab:
        print(f"ERROR: LAB CSV buit: {lab_path}")
        return 1
    if not mt4:
        print(f"ERROR: MT4 CSV buit: {mt4_path}")
        return 1

    # Join per ts
    common_ts = sorted(set(lab.keys()) & set(mt4.keys()))
    print(f"  lab_bars={len(lab)}  mt4_bars={len(mt4)}  common={len(common_ts)}")

    if not common_ts:
        print("ERROR: cap timestamp en comú entre LAB i MT4")
        return 1

    # Acumula diffs per indicador
    indicators = {
        "ema200": ("ema200_lab", "ema200_mt4", EMA_THRESHOLD),
        "rsi14":  ("rsi14_lab",  "rsi14_mt4",  RSI_THRESHOLD),
        "atr14":  ("atr14_lab",  "atr14_mt4",  ATR_THRESHOLD),
    }

    stats: dict[str, dict] = {k: {
        "diffs": [],
        "first_diff_ts": None,
        "first_diff_date": None,
        "n_nan": 0,
    } for k in indicators}

    signal_matches = 0
    signal_total = 0
    rows_detail = []

    for ts in common_ts:
        l = lab[ts]
        m = mt4[ts]
        date_utc = l.get("date_utc", "")

        row_detail: dict = {"ts": ts, "date_utc": date_utc}

        for ind_name, (lab_col, mt4_col, threshold) in indicators.items():
            lab_val = _safe_float(l.get(lab_col))
            mt4_val = _safe_float(m.get(mt4_col))

            if lab_val is None or mt4_val is None:
                stats[ind_name]["n_nan"] += 1
                row_detail[f"{ind_name}_lab"] = lab_val
                row_detail[f"{ind_name}_mt4"] = mt4_val
                row_detail[f"{ind_name}_diff"] = None
                continue

            diff = abs(lab_val - mt4_val)
            stats[ind_name]["diffs"].append(diff)
            row_detail[f"{ind_name}_lab"] = round(lab_val, 6)
            row_detail[f"{ind_name}_mt4"] = round(mt4_val, 6)
            row_detail[f"{ind_name}_diff"] = round(diff, 6)

            if diff > threshold and stats[ind_name]["first_diff_ts"] is None:
                stats[ind_name]["first_diff_ts"] = ts
                stats[ind_name]["first_diff_date"] = date_utc

        # Signal match
        lab_sig = _safe_float(l.get("signal_lab"))
        mt4_sig = _safe_float(m.get("signal_mt4"))
        if lab_sig is not None and mt4_sig is not None:
            signal_total += 1
            if int(lab_sig) == int(mt4_sig):
                signal_matches += 1
        row_detail["signal_lab"] = lab_sig
        row_detail["signal_mt4"] = mt4_sig

        rows_detail.append(row_detail)

    # Computa stats finals
    summary: dict = {
        "lab_file": str(lab_path),
        "mt4_file": str(mt4_path),
        "n_lab_bars": len(lab),
        "n_mt4_bars": len(mt4),
        "n_common_bars": len(common_ts),
        "indicators": {},
    }

    for ind_name, s in stats.items():
        diffs = s["diffs"]
        n = len(diffs)
        summary["indicators"][ind_name] = {
            "n_compared": n,
            "n_nan_skipped": s["n_nan"],
            "max_abs_diff": round(max(diffs), 8) if diffs else None,
            "mean_abs_diff": round(sum(diffs) / n, 8) if n > 0 else None,
            "p95_abs_diff": round(sorted(diffs)[int(n * 0.95)], 8) if n >= 20 else None,
            "first_diff_ts": s["first_diff_ts"],
            "first_diff_date": s["first_diff_date"],
            "n_bars_above_threshold": sum(1 for d in diffs if d > [EMA_THRESHOLD, RSI_THRESHOLD, ATR_THRESHOLD][["ema200", "rsi14", "atr14"].index(ind_name)]),
        }

    if signal_total > 0:
        summary["signal_match_rate_pct"] = round(signal_matches / signal_total * 100.0, 2)
        summary["signal_n_compared"] = signal_total
    else:
        summary["signal_match_rate_pct"] = None
        summary["signal_n_compared"] = 0

    # Top divergences (top 10 per EMA)
    top_diffs = sorted(
        [r for r in rows_detail if r.get("ema200_diff") is not None],
        key=lambda x: x["ema200_diff"],
        reverse=True,
    )[:10]
    summary["top_ema200_diffs"] = [
        {"date": r["date_utc"], "ts": r["ts"],
         "ema200_lab": r.get("ema200_lab"), "ema200_mt4": r.get("ema200_mt4"),
         "diff": r.get("ema200_diff")}
        for r in top_diffs
    ]

    # Escriu JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  → {out_path}")

    # Imprimeix resum
    _print_summary(summary)

    return 0


def _print_summary(summary: dict) -> None:
    print()
    print(f"INDICATOR PARITY REPORT")
    print(f"  LAB bars: {summary['n_lab_bars']}  MT4 bars: {summary['n_mt4_bars']}  Common: {summary['n_common_bars']}")
    print()
    header = f"  {'Indicador':<10} {'N':>5} {'MaxDiff':>12} {'MeanDiff':>12} {'P95Diff':>12} {'N>thr':>7} {'FirstDiff':<22}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for ind, s in summary["indicators"].items():
        n = s["n_compared"]
        mx = f"{s['max_abs_diff']:.6f}" if s["max_abs_diff"] is not None else "n/a"
        mn = f"{s['mean_abs_diff']:.6f}" if s["mean_abs_diff"] is not None else "n/a"
        p95 = f"{s['p95_abs_diff']:.6f}" if s["p95_abs_diff"] is not None else "n/a"
        nthr = s["n_bars_above_threshold"]
        first = s["first_diff_date"] or "—"
        print(f"  {ind:<10} {n:>5} {mx:>12} {mn:>12} {p95:>12} {nthr:>7} {first:<22}")

    if summary["signal_match_rate_pct"] is not None:
        print(f"\n  Signal match rate: {summary['signal_match_rate_pct']}% ({summary['signal_n_compared']} bars comparades)")

    if summary.get("top_ema200_diffs"):
        print("\n  Top 10 EMA200 divergences:")
        for r in summary["top_ema200_diffs"]:
            print(f"    {r['date']}  lab={r['ema200_lab']:.6f}  mt4={r['ema200_mt4']:.6f}  diff={r['diff']:.6f}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare indicators LAB vs MT4 (T8.21)")
    parser.add_argument("--lab", required=True, help="CSV indicators LAB")
    parser.add_argument("--mt4", required=True, help="CSV indicators MT4")
    parser.add_argument("--out", default="lab/runner/out_compare/indicator_diff_report.json",
                        help="Output JSON report path")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(compare_indicators(
        lab_path=Path(args.lab),
        mt4_path=Path(args.mt4),
        out_path=Path(args.out),
    ))
