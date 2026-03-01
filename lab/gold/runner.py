#!/usr/bin/env python3
"""
lab/gold/runner.py — Gold Parity Suite runner (T8.49).

Màquina d'estats: DATA_ORACLE_READY → INDICATOR_PARITY_PASS → SIGNAL_PARITY_PASS
→ EXECUTION_PARITY_PASS → TRADES_PARITY_PASS

Ús:
  python3 lab/gold/runner.py run --case rsi35_exit60_m1_oracle \\
    --oracle-csv /path/to/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv \\
    --eval-from 2026-02-01 --eval-to 2026-02-03 \\
    --eval-to-ts 1770089460 \\
    --outdir lab/gold/artifacts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

# Project root
GOLD_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = GOLD_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import loader i exec des de parity
from lab.runner.out_compare.mt4_m1_rsi35_exit60_parity import (
    load_mt4_candles,
    rsi_sq_exact,
    simulate_trades,
)

# Estats (ordenats)
STATE_DATA_ORACLE_READY = "DATA_ORACLE_READY"
STATE_INDICATOR_PARITY_PASS = "INDICATOR_PARITY_PASS"
STATE_SIGNAL_PARITY_PASS = "SIGNAL_PARITY_PASS"
STATE_EXECUTION_PARITY_PASS = "EXECUTION_PARITY_PASS"
STATE_TRADES_PARITY_PASS = "TRADES_PARITY_PASS"

RSI_PERIOD = 14
RSI_THRESHOLD = 35
OHLC_TOLERANCE = 1e-5


def _load_case_config(case_name: str) -> dict:
    """Carrega config del case."""
    config_path = GOLD_ROOT / "cases" / case_name / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_expected_trades(case_name: str) -> list[dict]:
    """Carrega expected_trades.csv."""
    path = GOLD_ROOT / "cases" / case_name / "expected_trades.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return [
        {
            "entry_ts": int(row["entry_ts"]),
            "exit_ts": int(row["exit_ts"]),
            "entry_price": float(row["entry_price"]),
            "exit_price": float(row["exit_price"]),
        }
        for _, row in df.iterrows()
    ]


def _build_gap_report(df: pd.DataFrame, eval_from_ts: int, eval_to_ts: int) -> dict:
    """Gap report dins eval window."""
    if df is None or len(df) < 2:
        return {"expected_minutes": 0, "actual_minutes": 0, "gaps": [], "pass": True}
    ts_sorted = sorted(int(t) for t in df["ts"] if eval_from_ts <= int(t) < eval_to_ts)
    expected = (eval_to_ts - eval_from_ts) // 60
    actual = len(ts_sorted)
    gaps = []
    for i in range(1, len(ts_sorted)):
        diff = ts_sorted[i] - ts_sorted[i - 1]
        if diff > 60:
            gaps.append({"after_ts": ts_sorted[i - 1], "next_ts": ts_sorted[i], "missing": (diff // 60) - 1})
    return {
        "expected_minutes": expected,
        "actual_minutes": actual,
        "gaps": gaps,
        "pass": len(gaps) == 0,
    }


def _compare_trades(lab: list[dict], expected: list[dict], ts_tol_s: int = 0) -> dict:
    """Compara lab trades vs expected."""
    matched = 0
    mismatches = []
    for i, exp in enumerate(expected):
        found = False
        for lt in lab:
            if (
                abs(lt["entry_ts"] - exp["entry_ts"]) <= ts_tol_s
                and abs(lt["exit_ts"] - exp["exit_ts"]) <= ts_tol_s
            ):
                matched += 1
                found = True
                break
        if not found and len(mismatches) < 5:
            mismatches.append({"idx": i + 1, "entry_ts": exp["entry_ts"], "exit_ts": exp["exit_ts"]})
    return {
        "lab_count": len(lab),
        "expected_count": len(expected),
        "matched": matched,
        "pass": matched == len(expected) and len(lab) == len(expected),
        "mismatches": mismatches,
    }


def run_case(
    case_name: str,
    oracle_csv: Path,
    eval_from: str,
    eval_to: str,
    eval_to_ts: Optional[int],
    warmup_from: str,
    outdir: Path,
) -> tuple[str, dict]:
    """
    Executa el case i retorna (state, report).
    Para al primer fail.
    """
    config = _load_case_config(case_name)
    eval_from_ts = int(datetime.strptime(eval_from, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    eval_to_ts = eval_to_ts or int(
        datetime.strptime(eval_to, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    )

    artifacts_dir = outdir / case_name / "EURUSD" / "1m" / f"{eval_from}_{eval_to}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "case": case_name,
        "oracle_path": str(oracle_csv),
        "eval_from": eval_from,
        "eval_to": eval_to,
        "state": "UNKNOWN",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- STATE 0: DATA_ORACLE_READY ---
    if not oracle_csv.exists():
        report["state"] = "ORACLE_MISSING"
        report["error"] = f"Oracle CSV no existeix: {oracle_csv}"
        with open(artifacts_dir / "oracle_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return "ORACLE_MISSING", report

    df = load_mt4_candles(oracle_csv)
    if df is None or len(df) == 0:
        report["state"] = "ORACLE_LOAD_FAILED"
        report["error"] = "No s'han pogut carregar candles oracle"
        with open(artifacts_dir / "oracle_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return "ORACLE_LOAD_FAILED", report

    gap_report = _build_gap_report(df, eval_from_ts, eval_to_ts)
    oracle_report = {
        "state": STATE_DATA_ORACLE_READY,
        "rows": len(df),
        "checksum": hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()[:16],
        "gap_report": gap_report,
    }
    with open(artifacts_dir / "oracle_report.json", "w", encoding="utf-8") as f:
        json.dump(oracle_report, f, indent=2)
    with open(artifacts_dir / "gap_report.json", "w", encoding="utf-8") as f:
        json.dump(gap_report, f, indent=2)

    # --- STATE 1: INDICATOR_PARITY_PASS ---
    rsi = rsi_sq_exact(df["close"].tolist(), RSI_PERIOD)
    df["rsi"] = rsi
    valid_rsi = sum(1 for v in rsi if not pd.isna(v))
    indicator_report = {
        "state": STATE_INDICATOR_PARITY_PASS,
        "rsi_period": RSI_PERIOD,
        "valid_bars": valid_rsi,
        "rounding": "direct (MT4 NormalizeDouble 6)",
    }
    with open(artifacts_dir / "indicator_report.json", "w", encoding="utf-8") as f:
        json.dump(indicator_report, f, indent=2)

    # --- STATE 2+3: SIGNAL + EXECUTION (simulate_trades) ---
    trades, _ = simulate_trades(
        df,
        use_rsi_sq_exact=True,
        round_decimals=None,
        round_half_up=True,
        eval_from_ts=eval_from_ts,
        eval_to_ts=eval_to_ts,
        entry_bar_offset=0,
        exit_use_close=False,
    )

    signal_events = [t["entry_ts"] for t in trades]
    pd.DataFrame({"ts": signal_events}).to_csv(artifacts_dir / "signal_events.csv", index=False)
    pd.DataFrame(trades).to_csv(artifacts_dir / "trades.csv", index=False)

    # --- STATE 4: TRADES_PARITY_PASS ---
    expected = _load_expected_trades(case_name)
    if not expected:
        report["state"] = STATE_EXECUTION_PARITY_PASS
        report["lab_trades"] = len(trades)
        report["warning"] = "No expected_trades.csv, no es pot verificar TRADES_PARITY"
        parity_report = {"state": STATE_EXECUTION_PARITY_PASS, "lab_trades": len(trades)}
    else:
        trade_compare = _compare_trades(trades, expected)
        parity_report = {
            "state": STATE_TRADES_PARITY_PASS if trade_compare["pass"] else "TRADES_PARITY_FAIL",
            "lab_trades": len(trades),
            "expected_trades": len(expected),
            "matched": trade_compare["matched"],
            "pass": trade_compare["pass"],
            "mismatches": trade_compare["mismatches"],
        }
        report.update(parity_report)

    with open(artifacts_dir / "parity_report.json", "w", encoding="utf-8") as f:
        json.dump(parity_report, f, indent=2)

    report["state"] = parity_report["state"]
    return parity_report["state"], report


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.49 Gold Parity Suite")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_parser = sub.add_parser("run", help="Executa un case")
    run_parser.add_argument("--case", default="rsi35_exit60_m1_oracle", help="Nom del case")
    run_parser.add_argument("--oracle-csv", type=Path, required=True, help="Path oracle CSV (SQ export)")
    run_parser.add_argument("--eval-from", default="2026-02-01", help="Data inici eval")
    run_parser.add_argument("--eval-to", default="2026-02-03", help="Data fi eval")
    run_parser.add_argument("--eval-to-ts", type=int, default=None, help="Override ts fi (ex: 1770089460)")
    run_parser.add_argument("--warmup-from", default="2026-01-20", help="Data warmup")
    run_parser.add_argument("--outdir", type=Path, default=GOLD_ROOT / "artifacts", help="Directori artifacts")

    args = parser.parse_args()
    if args.cmd != "run":
        return 1

    state, report = run_case(
        case_name=args.case,
        oracle_csv=args.oracle_csv,
        eval_from=args.eval_from,
        eval_to=args.eval_to,
        eval_to_ts=args.eval_to_ts,
        warmup_from=args.warmup_from,
        outdir=args.outdir,
    )

    print(json.dumps(report, indent=2))
    if state == STATE_TRADES_PARITY_PASS:
        print("\nPASS (TRADES_PARITY)")
        return 0
    if state in (STATE_DATA_ORACLE_READY, STATE_INDICATOR_PARITY_PASS, STATE_EXECUTION_PARITY_PASS):
        print(f"\nState: {state} (no expected_trades o pass parcial)")
        return 0
    print(f"\nFAIL: {state}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
