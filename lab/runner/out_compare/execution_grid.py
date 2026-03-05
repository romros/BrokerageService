"""
T8.45 — Execution Contract Grid (oracle real) fins 17/17.

Grid 2×2: entry_at (open[i] vs open[i+1]) × exit_at (open vs close).
Reutilitza RSI exact + best rounding (d1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
ARTIFACTS_T845 = OUT / "artifacts" / "T8.45" / "EURUSD" / "1m" / "2026-02-01_2026-02-02"

# Import harness (project root + out_compare per application i mt4_m1)
_PROJECT_ROOT = OUT.parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(OUT) not in sys.path:
    sys.path.insert(0, str(OUT))
from mt4_m1_rsi35_exit60_parity import (
    CANDLES_ORACLE_NAMES,
    EXIT_BARS,
    RSI_PERIOD,
    _resolve_oracle_path,
    load_mt4_candles,
    load_mt4_trades,
    compare_trades,
    simulate_trades,
)

MT4_ORACLE_DIR = OUT / "mt4_oracle"
MT4_TRADES = MT4_ORACLE_DIR / "trades_EURUSD_M1_UTCMinus05_20260201_20260202.csv"
FALLBACK_TRADES = OUT.parents[1] / "ostium" / "out_ind" / "rsi" / "output.rsi1m.csv"  # lab/ostium/...

# V1: entry=open[i], exit=open[i+60]
# V2: entry=open[i], exit=close[i+60]
# V3: entry=open[i+1], exit=open[i+60+1]
# V4: entry=open[i+1], exit=close[i+60+1]
EXEC_VARIANTS = [
    ("v1", 0, False, "entry_open_i_exit_open"),
    ("v2", 0, True, "entry_open_i_exit_close"),
    ("v3", 1, False, "entry_open_i1_exit_open"),
    ("v4", 1, True, "entry_open_i1_exit_close"),
]

EVAL_FROM_TS = 1769904000  # 2026-02-01 00:00 UTC
EVAL_TO_TS = 1770089460    # 2026-02-03 03:31 UTC (cobreix trade 17 exit, evita trades extra)


def main() -> int:
    artifacts_dir = ARTIFACTS_T845
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Load oracle candles
    candles_path = _resolve_oracle_path(CANDLES_ORACLE_NAMES)
    if candles_path is None or not candles_path.exists():
        print("ERROR: No candles oracle. Executa run_t843.")
        return 1

    lab_df = load_mt4_candles(candles_path)
    if lab_df is None or len(lab_df) == 0:
        print("ERROR: No s'han pogut carregar candles oracle")
        return 1

    # Load MT4 trades
    mt4_path = MT4_TRADES if MT4_TRADES.exists() else FALLBACK_TRADES
    mt4_trades = load_mt4_trades(mt4_path)
    if not mt4_trades:
        print("ERROR: No MT4 trades")
        return 1

    print(f"Oracle: {len(lab_df)} rows, MT4: {len(mt4_trades)} trades")
    print("Grid: entry_bar_offset × exit_use_close")

    grid_rows = []
    best_variant = None
    best_matched = -1
    best_count = -1

    for vid, entry_offset, exit_close, label in EXEC_VARIANTS:
        trades, _ = simulate_trades(
            lab_df,
            use_rsi_sq_exact=True,
            round_decimals=None,  # MT4 NormalizeDouble(6), no arrodoneix a d1
            round_half_up=True,
            eval_from_ts=EVAL_FROM_TS,
            eval_to_ts=EVAL_TO_TS,
            entry_bar_offset=entry_offset,
            exit_use_close=exit_close,
        )
        report = compare_trades(trades, mt4_trades, ts_tol_s=0)

        entry_mode = "open[i+1]" if entry_offset else "open[i]"
        exit_mode = "close" if exit_close else "open"
        row = {
            "variant_id": vid,
            "entry_mode": entry_mode,
            "exit_mode": exit_mode,
            "trade_count": len(trades),
            "matched": report["matched"],
            "mt4_count": report["mt4_count"],
        }
        grid_rows.append(row)

        # Save lab_trades for best + baseline (v1)
        if vid == "v1" or (len(trades) > best_count or report["matched"] > best_matched):
            pd.DataFrame(trades).to_csv(artifacts_dir / f"lab_trades_{vid}.csv", index=False)
            if report["mismatches"]:
                pd.DataFrame(report["mismatches"]).to_csv(
                    artifacts_dir / f"trade_mismatches_{vid}.csv", index=False
                )

        if report["matched"] > best_matched or (
            report["matched"] == best_matched and len(trades) > best_count
        ):
            best_matched = report["matched"]
            best_count = len(trades)
            best_variant = {
                "variant_id": vid,
                "entry_mode": entry_mode,
                "exit_mode": exit_mode,
                "lab_count": len(trades),
                "matched": report["matched"],
                "target": 17,
                "pass": len(trades) == 17 and report["matched"] >= 17,
            }

        print(f"  {vid}: entry={entry_mode} exit={exit_mode} → lab={len(trades)} matched={report['matched']}")

    pd.DataFrame(grid_rows).to_csv(artifacts_dir / "execution_grid.csv", index=False)
    with open(artifacts_dir / "best_execution_variant.json", "w", encoding="utf-8") as f:
        json.dump(best_variant, f, indent=2)

    print(f"\nBest: {best_variant['variant_id']} lab={best_variant['lab_count']} matched={best_variant['matched']}")
    if best_variant["pass"]:
        print("PASS (17/17)")
        return 0
    print("FAIL: cap variant dona 17/17")
    return 1


if __name__ == "__main__":
    sys.exit(main())
