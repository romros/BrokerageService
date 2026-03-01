"""
T8.31 — Trade Diff Analyzer: matched/unmatched MT4 vs LAB, classificació causes.

Llegeix MT4 trades, LAB trades (best contract), indicators LAB.
Classifica unmatched: DATA_MISSING, SIGNAL_MISMATCH, CONTRACT_SHIFT, EXIT_CASCADE.

Outputs: trade_diff_report.json, trade_diff_report.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Afegir project root al path si cal (lab/runner/out_compare/ → 3 parents)
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Reutilitzem compare_trades
from lab.runner.out_compare.compare_trades import read_sq_export, read_lab_trades

TOL_1D = timedelta(days=1)
CONTRACT_SHIFT_MAX_DAYS = 7
CATEGORIES = ("DATA_MISSING", "SIGNAL_MISMATCH", "CONTRACT_SHIFT", "EXIT_CASCADE", "UNKNOWN")


def load_indicators_csv(path: Path) -> dict[int, dict]:
    """ts -> {close, ema200, rsi14, atr14, signal_lab, date_utc}"""
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(row["ts"])
                rows[ts] = {
                    "ts": ts,
                    "close": float(row["close"]) if row.get("close") else None,
                    "ema200_lab": float(row["ema200_lab"]) if row.get("ema200_lab") else None,
                    "rsi14_lab": float(row["rsi14_lab"]) if row.get("rsi14_lab") else None,
                    "atr14_lab": float(row["atr14_lab"]) if row.get("atr14_lab") else None,
                    "signal_lab": int(row.get("signal_lab", 0) or 0),
                    "date_utc": row.get("date_utc", ""),
                }
            except (KeyError, ValueError):
                continue
    return rows


def _ts_to_bar_start(entry_time: datetime, day_offset_h: int = 5) -> int:
    """Retorna epoch UTC del start de la barra D1 que conté entry_time (day_offset_h=5)."""
    dt = entry_time.replace(tzinfo=timezone.utc)
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    bar_start = day.replace(hour=day_offset_h, minute=0, second=0, microsecond=0)
    if dt < bar_start:
        bar_start = bar_start - timedelta(days=1)
    return int(bar_start.timestamp())


def _find_lab_match(mt4_entry: datetime, lab_trades: list[dict], tol: timedelta) -> Optional[dict]:
    for lt in lab_trades:
        if abs((mt4_entry - lt["entry_time"]).total_seconds()) <= tol.total_seconds():
            return lt
    return None


def _lab_entry_match_rate(lab_trades: list[dict], mt4_trades: list[dict], tol: timedelta) -> float:
    """% de LAB trades que tenen match MT4 (coherent amb compare_trades)."""
    if not lab_trades:
        return 0.0
    mt4_times = [t["entry_time"] for t in mt4_trades]
    matched = 0
    for lt in lab_trades:
        for mt in mt4_times:
            if abs((lt["entry_time"] - mt).total_seconds()) <= tol.total_seconds():
                matched += 1
                break
    return round(matched / len(lab_trades) * 100.0, 2)


def _find_nearest_signal(
    bar_ts: int,
    indicators: dict[int, dict],
    max_days: int = CONTRACT_SHIFT_MAX_DAYS,
) -> tuple[Optional[int], int]:
    """Retorna (ts del bar amb signal, dies de distància)."""
    if bar_ts in indicators and indicators[bar_ts]["signal_lab"] == 1:
        return bar_ts, 0
    sorted_ts = sorted(indicators.keys())
    if not sorted_ts:
        return None, 999
    # Cerca dins ±max_days
    day_s = 86400
    for d in range(1, max_days + 1):
        for offset in (d * day_s, -d * day_s):
            cand = bar_ts + offset
            if cand in indicators and indicators[cand]["signal_lab"] == 1:
                return cand, d
    return None, 999


def classify_unmatched(
    mt4_trade: dict,
    lab_trades: list[dict],
    indicators: dict[int, dict],
    lab_entry_times: set[datetime],
) -> tuple[str, dict]:
    """
    Classifica un trade MT4 unmatched.
    Retorna (category, details).
    """
    entry_time = mt4_trade["entry_time"]
    bar_ts = _ts_to_bar_start(entry_time)

    details = {
        "mt4_entry_utc": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
        "bar_ts": bar_ts,
        "has_indicators_row": bar_ts in indicators,
        "signal_lab": None,
        "close": None,
        "ema200": None,
        "rsi14": None,
        "atr14": None,
        "signal_should_trigger": None,
        "nearest_signal_ts": None,
        "nearest_signal_days": None,
    }

    if bar_ts not in indicators:
        return "DATA_MISSING", details

    row = indicators[bar_ts]
    details["close"] = row["close"]
    details["ema200"] = row["ema200_lab"]
    details["rsi14"] = row["rsi14_lab"]
    details["atr14"] = row["atr14_lab"]
    details["signal_lab"] = row["signal_lab"]
    # signal_lab ja indica si la barra hauria de tenir senyal (Close[prev]>EMA[prev] && RSI[prev]<35)
    details["signal_should_trigger"] = row["signal_lab"] == 1

    # signal_lab=0: no tenim signal a aquesta barra → SIGNAL_MISMATCH (MT4 sí, nosaltres no)
    # signal_lab=1: tenim signal → LAB hauria entrat; si no match, pot ser CONTRACT_SHIFT o EXIT_CASCADE
    nearest_ts, nearest_days = _find_nearest_signal(bar_ts, indicators)
    details["nearest_signal_ts"] = nearest_ts
    details["nearest_signal_days"] = nearest_days if nearest_ts else None

    if row["signal_lab"] == 0:
        if nearest_ts and nearest_days <= CONTRACT_SHIFT_MAX_DAYS:
            return "CONTRACT_SHIFT", details  # Signal a barra adjacent
        return "SIGNAL_MISMATCH", details  # No tenim signal, MT4 sí

    # signal_lab=1: tenim signal però no hi ha match
    window = timedelta(days=14)
    lab_in_window = [
        lt for lt in lab_trades
        if abs((lt["entry_time"] - entry_time).total_seconds()) <= window.total_seconds()
    ]
    if lab_in_window:
        return "EXIT_CASCADE", {**details, "lab_trades_nearby": len(lab_in_window)}
    return "CONTRACT_SHIFT", details  # Signal aquí, LAB pot haver entrat a barra adjacent


def run_analysis(
    mt4_csv: Path,
    lab_trades_csv: Path,
    indicators_csv: Path,
    out_dir: Path,
    tol: timedelta = TOL_1D,
) -> dict:
    mt4_trades = read_sq_export(mt4_csv, "MT4")
    lab_trades = read_lab_trades(lab_trades_csv)
    indicators = load_indicators_csv(indicators_csv)

    lab_entry_times = {t["entry_time"] for t in lab_trades}

    results = []
    matched = 0
    first_divergence: Optional[dict] = None

    for i, mt in enumerate(mt4_trades):
        entry_time = mt["entry_time"]
        lab_match = _find_lab_match(entry_time, lab_trades, tol)
        if lab_match:
            matched += 1
            results.append({
                "mt4_idx": i + 1,
                "mt4_entry_utc": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "MATCHED",
                "lab_entry_utc": lab_match["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
                "category": None,
                "details": None,
            })
        else:
            category, details = classify_unmatched(mt, lab_trades, indicators, lab_entry_times)
            results.append({
                "mt4_idx": i + 1,
                "mt4_entry_utc": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "UNMATCHED",
                "lab_entry_utc": None,
                "category": category,
                "details": details,
            })
            if first_divergence is None and details.get("has_indicators_row"):
                first_divergence = {
                    "mt4_idx": i + 1,
                    "mt4_entry_utc": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "category": category,
                    "details": details,
                }

    n_mt4 = len(mt4_trades)
    mt4_match_rate = round(matched / n_mt4 * 100.0, 2) if n_mt4 else 0.0
    lab_match_rate = _lab_entry_match_rate(lab_trades, mt4_trades, tol)

    category_counts = {}
    for r in results:
        if r["category"]:
            category_counts[r["category"]] = category_counts.get(r["category"], 0) + 1

    report = {
        "n_mt4_trades": n_mt4,
        "n_lab_trades": len(lab_trades),
        "n_matched": matched,
        "n_unmatched": n_mt4 - matched,
        "entry_match_rate_mt4": mt4_match_rate,
        "entry_match_rate_lab": lab_match_rate,
        "tolerance": str(tol),
        "first_divergence": first_divergence,
        "category_counts": category_counts,
        "trades": results,
        "recommendation": _recommendation(category_counts),
    }
    return report


def _recommendation(category_counts: dict) -> str:
    if not category_counts:
        return "No hi ha trades unmatched."
    data_missing = category_counts.get("DATA_MISSING", 0)
    signal_mismatch = category_counts.get("SIGNAL_MISMATCH", 0)
    contract_shift = category_counts.get("CONTRACT_SHIFT", 0)
    total = sum(category_counts.values())
    if data_missing > total * 0.5:
        return "Majoria DATA_MISSING → cal BI5 repair o additional backfill (55 mesos 2007-2011)."
    if signal_mismatch + contract_shift > total * 0.5:
        return "Majoria SIGNAL_MISMATCH/CONTRACT_SHIFT → cal oracle indicadors MT4 (EA) o ajustar definició RSI/EMA."
    return "Causes mixtes. Revisar first_divergence i details per trade."


def write_report_json(report: dict, out_path: Path) -> None:
    def _serialize(obj):
        if isinstance(obj, (datetime, timedelta)):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} not serializable")

    out_path.write_text(
        json.dumps(report, indent=2, default=_serialize, ensure_ascii=False),
        encoding="utf-8",
    )


def write_report_csv(report: dict, out_path: Path) -> None:
    rows = []
    for t in report["trades"]:
        d = t.get("details") or {}
        rows.append({
            "mt4_idx": t["mt4_idx"],
            "mt4_entry_utc": t["mt4_entry_utc"],
            "status": t["status"],
            "lab_entry_utc": t.get("lab_entry_utc") or "",
            "category": t.get("category") or "",
            "has_data": d.get("has_indicators_row", ""),
            "signal_lab": d.get("signal_lab", ""),
            "nearest_signal_days": d.get("nearest_signal_days", ""),
        })
    if not rows:
        return
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.31 Trade Diff Analyzer")
    parser.add_argument("--mt4-csv", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument(
        "--lab-trades",
        default="lab/runner/out_compare/contract_open_i_mt4_baropen/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv",
    )
    parser.add_argument("--indicators", default="lab/runner/out_compare/indicators_LAB_full.csv")
    parser.add_argument("--out-dir", default="lab/runner/out_compare")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    mt4_path = root / args.mt4_csv
    lab_path = root / args.lab_trades
    indicators_path = root / args.indicators
    out_dir = root / args.out_dir

    if not mt4_path.exists():
        print(f"ERROR: MT4 CSV no trobat: {mt4_path}")
        return 1
    if not lab_path.exists():
        print(f"ERROR: LAB trades no trobat: {lab_path}")
        return 1
    if not indicators_path.exists():
        print(f"ERROR: Indicators CSV no trobat: {indicators_path}")
        print("  Executa primer: python3 -m application.tools.export_indicators_csv ...")
        return 1

    report = run_analysis(mt4_path, lab_path, indicators_path, out_dir)
    write_report_json(report, out_dir / "trade_diff_report.json")
    write_report_csv(report, out_dir / "trade_diff_report.csv")

    print(f"\nT8.31 Trade Diff Report")
    print(f"  MT4: {report['n_mt4_trades']}  LAB: {report['n_lab_trades']}")
    print(f"  Matched: {report['n_matched']}  Unmatched: {report['n_unmatched']}")
    print(f"  entry_match_rate (MT4): {report['entry_match_rate_mt4']}%")
    print(f"  entry_match_rate (LAB): {report['entry_match_rate_lab']}%")
    print(f"  Categories: {report['category_counts']}")
    if report.get("first_divergence"):
        fd = report["first_divergence"]
        print(f"\n  First divergence: MT4 #{fd['mt4_idx']} {fd['mt4_entry_utc']}")
        print(f"    category: {fd['category']}")
        d = fd.get("details", {})
        if d:
            print(f"    has_data: {d.get('has_indicators_row')}  signal_lab: {d.get('signal_lab')}")
            print(f"    close: {d.get('close')}  ema200: {d.get('ema200')}  rsi14: {d.get('rsi14')}")
    print(f"\n  Recommendation: {report['recommendation']}")
    print(f"  → {out_dir}/trade_diff_report.json")
    print(f"  → {out_dir}/trade_diff_report.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
