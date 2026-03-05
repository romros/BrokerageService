"""
T8.46 — Signal Event Diff (oracle real) fins identificar el bar del 17è trade.

Genera signal_events_lab, signal_events_sq (expected=MT4), signal_event_diff,
gap_report, first_divergence amb classificació.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
ARTIFACTS_T846 = OUT / "artifacts" / "T8.46" / "EURUSD" / "1m" / "2026-02-01_2026-02-02"

if str(OUT) not in sys.path:
    sys.path.insert(0, str(OUT))
from mt4_m1_rsi35_exit60_parity import (
    CANDLES_ORACLE_NAMES,
    RSI_PERIOD,
    RSI_THRESHOLD,
    _resolve_oracle_path,
    load_mt4_candles,
    load_mt4_trades,
    get_rounded,
    rsi_sq_exact,
    _is_weekend_blocked,
)

MT4_ORACLE_DIR = OUT / "mt4_oracle"
MT4_TRADES = MT4_ORACLE_DIR / "trades_EURUSD_M1_UTCMinus05_20260201_20260202.csv"
FALLBACK_TRADES = OUT.parents[1] / "ostium" / "out_ind" / "rsi" / "output.rsi1m.csv"

EVAL_FROM_TS = 1769904000  # 2026-02-01 00:00 UTC
EVAL_TO_TS = 1770089460    # 2026-02-03 03:31 UTC (cobreix trade 17 exit 03:30, evita trades extra)
# MT4 usa NormalizeDouble(6), no arrodoneix a 1 decimal abans de RSI < 35.
# round_decimals=None = paritat MT4 (comparació directa rsi_raw).
ROUND_DECIMALS = None
MISMATCH_ENTRY_TS = [1770010200, 1770041760, 1770085800]  # T8.44


def _build_gap_report(df: pd.DataFrame) -> dict:
    """Minuts esperats vs reals dins eval window, primer gap."""
    if df is None or len(df) < 2:
        return {"expected_minutes": 0, "actual_minutes": 0, "first_gap": None}
    ts_sorted = sorted(int(t) for t in df["ts"] if EVAL_FROM_TS <= int(t) < EVAL_TO_TS)
    expected = (EVAL_TO_TS - EVAL_FROM_TS) // 60
    actual = len(ts_sorted)
    gaps = []
    for i in range(1, len(ts_sorted)):
        diff = ts_sorted[i] - ts_sorted[i - 1]
        if diff > 60:
            gaps.append({
                "after_ts": ts_sorted[i - 1],
                "next_ts": ts_sorted[i],
                "missing_minutes": (diff // 60) - 1,
            })
    return {
        "expected_minutes": expected,
        "actual_minutes": actual,
        "missing_minutes": expected - actual,
        "first_gap": gaps[0] if gaps else None,
        "total_gaps": len(gaps),
    }


def _classify_divergence(
    ts: int,
    signal_lab: bool,
    signal_expected: bool,
    rsi_raw: float,
    rsi_rounded: float,
    bar_idx: int,
    warmup_bars: int,
    gap_report: dict,
) -> tuple[str, str]:
    """Classifica la causa de la divergència."""
    if signal_lab == signal_expected:
        return "NONE", ""

    # ROUNDING_MODE_MISMATCH: raw prop del llindar (34..36), rounding canvia el signal
    if 34.0 <= rsi_raw <= 36.0:
        r0 = get_rounded(rsi_raw, 0, half_up=True)
        r1 = get_rounded(rsi_raw, 1, half_up=True)
        s0 = r0 < RSI_THRESHOLD
        s1 = r1 < RSI_THRESHOLD
        if s0 != s1 or (signal_expected and not signal_lab and rsi_raw < 35.0):
            return "ROUNDING_MODE_MISMATCH", f"rsi_raw={rsi_raw:.4f} d0→{r0}(s={s0}) d1→{r1}(s={s1})"

    # WARMUP_MISMATCH: dins dels primers N bars d'eval
    if bar_idx < warmup_bars:
        return "WARMUP_MISMATCH", f"bar_idx={bar_idx} < warmup={warmup_bars}"

    # MISSING_MINUTE_MISMATCH: hi ha gaps dins eval i ts proper al gap
    if gap_report.get("first_gap"):
        fg = gap_report["first_gap"]
        if fg["after_ts"] >= EVAL_FROM_TS and abs(ts - fg["after_ts"]) <= 600:
            return "MISSING_MINUTE_MISMATCH", f"ts proper a gap after_ts={fg['after_ts']}"
        if abs(ts - fg["next_ts"]) <= 600:
            return "MISSING_MINUTE_MISMATCH", f"ts proper a gap next_ts={fg['next_ts']}"

    # SHIFT_MISMATCH: podria ser t±1
    if 33.0 <= rsi_raw <= 37.0:
        return "SHIFT_MISMATCH", f"rsi_raw={rsi_raw:.2f} possible t±1"
    return "SHIFT_MISMATCH", "possible t±1 bar"


def main() -> int:
    artifacts_dir = ARTIFACTS_T846
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    candles_path = _resolve_oracle_path(CANDLES_ORACLE_NAMES)
    if candles_path is None or not candles_path.exists():
        print("ERROR: No candles oracle. Executa run_t843.")
        return 1

    df = load_mt4_candles(candles_path)
    if df is None or len(df) == 0:
        print("ERROR: No s'han pogut carregar candles oracle")
        return 1

    mt4_path = MT4_TRADES if MT4_TRADES.exists() else FALLBACK_TRADES
    mt4_trades = load_mt4_trades(mt4_path)
    if not mt4_trades:
        print("ERROR: No MT4 trades")
        return 1

    mt4_entry_ts = {t["entry_ts"] for t in mt4_trades}

    # Gap report
    gap_report = _build_gap_report(df)
    with open(artifacts_dir / "gap_report.json", "w", encoding="utf-8") as f:
        json.dump(gap_report, f, indent=2)
    print(f"Gap report: expected={gap_report['expected_minutes']} min, actual={gap_report['actual_minutes']}, gaps={gap_report['total_gaps']}")

    # RSI sobre tota la sèrie
    closes = df["close"].tolist()
    rsi = rsi_sq_exact(closes, RSI_PERIOD)
    n = len(df)

    # Signal events LAB (dins eval). signal_events_sq = expected = MT4 entry_ts
    signal_events_lab = []
    signal_events_expected = sorted(ts for ts in mt4_entry_ts if EVAL_FROM_TS <= ts < EVAL_TO_TS)
    diff_rows = []
    first_div = None
    warmup_bars = RSI_PERIOD + 10
    bars_in_eval = 0

    for i in range(1, n):
        ts = int(df.iloc[i]["ts"])
        if ts < EVAL_FROM_TS or ts >= EVAL_TO_TS:
            continue
        if _is_weekend_blocked(ts):
            continue

        bars_in_eval += 1
        rsi_prev = rsi[i - 1]
        if pd.isna(rsi_prev):
            diff_rows.append({"ts": ts, "signal_lab": False, "signal_expected": ts in mt4_entry_ts, "rsi_raw": None, "rsi_rounded": None})
            continue

        if ROUND_DECIMALS is not None:
            rsi_r = get_rounded(rsi_prev, ROUND_DECIMALS, half_up=True)
            signal_lab = rsi_r < RSI_THRESHOLD
        else:
            rsi_r = rsi_prev
            signal_lab = rsi_prev < RSI_THRESHOLD
        signal_expected = ts in mt4_entry_ts

        if signal_lab:
            signal_events_lab.append(ts)

        diff_rows.append({
            "ts": ts,
            "signal_lab": signal_lab,
            "signal_expected": signal_expected,
            "rsi_raw": round(rsi_prev, 6),
            "rsi_rounded": round(rsi_r, 6),
        })

        if first_div is None and signal_lab != signal_expected:
            cause, reason = _classify_divergence(
                ts, signal_lab, signal_expected, rsi_prev, rsi_r if ROUND_DECIMALS is not None else rsi_prev,
                bars_in_eval - 1, warmup_bars, gap_report
            )
            first_div = {
                "ts": ts,
                "bar_idx": i,
                "bars_in_eval": bars_in_eval - 1,
                "signal_lab": signal_lab,
                "signal_expected": signal_expected,
                "rsi_raw": round(rsi_prev, 6),
                "rsi_rounded": round(rsi_r, 6),
                "cause": cause,
                "reason": reason,
            }

    pd.DataFrame({"ts": signal_events_lab}).to_csv(artifacts_dir / "signal_events_lab.csv", index=False)
    pd.DataFrame({"ts": signal_events_expected}).to_csv(artifacts_dir / "signal_events_sq.csv", index=False)
    diff_df = pd.DataFrame(diff_rows)
    diff_df.to_csv(artifacts_dir / "signal_event_diff.csv", index=False)

    # Finestra ±5 min al voltant dels 3 mismatches
    for mts in MISMATCH_ENTRY_TS:
        window = [r for r in diff_rows if abs(r["ts"] - mts) <= 300]
        if window:
            pd.DataFrame(window).to_csv(artifacts_dir / f"diff_window_{mts}.csv", index=False)

    # Proposta fix mínim
    fix = None
    if first_div and first_div["cause"] == "ROUNDING_MODE_MISMATCH":
        fix = "round_decimals=None per paritat MT4 (NormalizeDouble 6, sense arrodonir a d1)"
    elif first_div and first_div["cause"] == "WARMUP_MISMATCH":
        fix = "augmentar warmup o verificar seed RSI als primers bars"
    elif first_div and first_div["cause"] == "MISSING_MINUTE_MISMATCH":
        fix = "inserir minuts absents al CSV o fer fallback"
    elif first_div and first_div["cause"] == "SHIFT_MISMATCH":
        fix = "verificar entry_bar_offset (open[i] vs open[i+1])"

    report = {"first_divergence": first_div, "gap_report": gap_report}
    if fix:
        report["proposed_fix"] = fix
    with open(artifacts_dir / "first_divergence.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if first_div:
        print(f"First divergence: ts={first_div['ts']} cause={first_div['cause']} {first_div['reason']}")
    else:
        print("No divergence found (signal_lab == signal_expected for all bars)")

    print(f"LAB signal events: {len(signal_events_lab)}, expected (MT4): {len(signal_events_expected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
