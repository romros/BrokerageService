"""
T8.36 — Signal Definition Sweep: grid de variants (RSI method, indexing, price source, rounding).

Score per variant: signal_true_at_t, signal_true_within_pm1, signal_true_within_pm3.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export
from lab.runner.out_compare.trade_diff_analyzer import _ts_to_bar_start

RSI_THRESHOLD = 35.0


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def _round_price(v: float, digits: int | None) -> float:
    return round(v, digits) if digits is not None else v


def _ema_sma_seed(close: list[float], period: int) -> list[float]:
    n = len(close)
    out = [float("nan")] * n
    if n < period:
        return out
    mult = 2.0 / (period + 1)
    out[period - 1] = sum(close[:period]) / period
    for i in range(period, n):
        out[i] = close[i] * mult + out[i - 1] * (1.0 - mult)
    return out


def _rsi_wilder(close: list[float], period: int) -> list[float]:
    n = len(close)
    out = [float("nan")] * n
    if n < period + 1:
        return out
    delta = [0.0] + [close[i] - close[i - 1] for i in range(1, n)]
    gain = [max(0, d) for d in delta]
    loss = [max(0, -d) for d in delta]
    avg_g = sum(gain[1 : period + 1]) / period
    avg_l = sum(loss[1 : period + 1]) / period
    out[period] = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        out[i] = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    return out


def _rsi_ema_gains(close: list[float], period: int) -> list[float]:
    """RSI amb smoothing EMA (alpha=2/(period+1)) per gains/losses."""
    n = len(close)
    out = [float("nan")] * n
    if n < period + 1:
        return out
    delta = [0.0] + [close[i] - close[i - 1] for i in range(1, n)]
    gain = [max(0, d) for d in delta]
    loss = [max(0, -d) for d in delta]
    alpha = 2.0 / (period + 1)
    avg_g = sum(gain[1 : period + 1]) / period
    avg_l = sum(loss[1 : period + 1]) / period
    out[period] = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    for i in range(period + 1, n):
        avg_g = alpha * gain[i] + (1 - alpha) * avg_g
        avg_l = alpha * loss[i] + (1 - alpha) * avg_l
        out[i] = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    return out


def _atr_wilder(high: list[float], low: list[float], close: list[float], period: int) -> list[float]:
    n = len(close)
    out = [float("nan")] * n
    if n < period:
        return out
    prev_c = [close[0]] + close[:-1]
    tr = [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(high, low, prev_c)]
    tr[0] = high[0] - low[0]
    out[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def load_candles(path: Path, rounding_digits: int | None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                ts = int(r["ts"])
                o = _safe_float(r.get("open")) or 0.0
                h = _safe_float(r.get("high")) or 0.0
                l_ = _safe_float(r.get("low")) or 0.0
                c = _safe_float(r.get("close"))
                if c is None:
                    continue
                o = _round_price(o, rounding_digits)
                h = _round_price(h, rounding_digits)
                l_ = _round_price(l_, rounding_digits)
                c = _round_price(c, rounding_digits)
                rows.append({"ts": ts, "date_utc": r.get("date_utc", ""), "open": o, "high": h, "low": l_, "close": c})
            except (KeyError, ValueError):
                continue
    return rows


def apply_price_source(rows: list[dict], price_source: str) -> list[dict]:
    if price_source == "close":
        return rows
    out = []
    for r in rows:
        o = dict(r)
        o["close"] = (r["high"] + r["low"] + r["close"]) / 3.0
        out.append(o)
    return out


def compute_variant(
    rows: list[dict],
    rsi_method: str,
    idx_mode: str,
) -> list[dict]:
    close = [r["close"] for r in rows]
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    ema_arr = _ema_sma_seed(close, 200)
    rsi_arr = _rsi_ema_gains(close, 14) if rsi_method == "ema_gains" else _rsi_wilder(close, 14)
    atr_arr = _atr_wilder(high, low, close, 14)
    out = []
    for i, r in enumerate(rows):
        o = dict(r)
        o["ema200"] = ema_arr[i] if not math.isnan(ema_arr[i]) else None
        o["rsi14"] = rsi_arr[i] if not math.isnan(rsi_arr[i]) else None
        o["atr14"] = atr_arr[i] if not math.isnan(atr_arr[i]) else None
        if idx_mode == "bar_closed":
            idx = i - 1 if i > 0 else 0
        else:
            idx = i
        c = close[idx] if idx < len(close) else close[0]
        e = ema_arr[idx] if idx < len(ema_arr) and not math.isnan(ema_arr[idx]) else c
        rs = rsi_arr[idx] if idx < len(rsi_arr) and not math.isnan(rsi_arr[idx]) else 50.0
        o["signal"] = 1 if (c > e and rs < RSI_THRESHOLD) else 0
        out.append(o)
    return out


def _find_bar_index(sorted_ts: list[int], bar_ts: int) -> int:
    idx = bisect.bisect_right(sorted_ts, bar_ts) - 1
    return max(0, idx)


def score_variant(
    rows: list[dict],
    sorted_ts: list[int],
    ts_to_idx: dict[int, int],
    mt4_trades: list[dict],
    day_offset_h: int,
    pm_window: int,
) -> tuple[int, int, int]:
    signal_true_at_t = 0
    signal_true_within_pm1 = 0
    signal_true_within_pm3 = 0
    for mt in mt4_trades:
        bar_ts = _ts_to_bar_start(mt["entry_time"], day_offset_h=day_offset_h)
        idx = _find_bar_index(sorted_ts, bar_ts)
        if idx >= len(rows):
            continue
        at_t = rows[idx].get("signal", 0) == 1
        within_pm1 = at_t
        within_pm3 = at_t
        for d in range(1, pm_window + 1):
            for i2 in (idx + d, idx - d):
                if 0 <= i2 < len(rows) and rows[i2].get("signal", 0) == 1:
                    if d <= 1:
                        within_pm1 = True
                    if d <= 3:
                        within_pm3 = True
                    break
        if at_t:
            signal_true_at_t += 1
        if within_pm1:
            signal_true_within_pm1 += 1
        if within_pm3:
            signal_true_within_pm3 += 1
    return signal_true_at_t, signal_true_within_pm1, signal_true_within_pm3


def _score_aggregate(st: int, sp1: int, sp3: int) -> int:
    return 10 * st + 3 * sp1 + 1 * sp3


def _baseline_distance(variant_id: str) -> int:
    """Nombre de params que difereixen de baseline (menor = millor en tiebreak)."""
    baseline = ("wilder", "bar_closed", "close", "none")
    parts = variant_id.split("_")
    rsi = parts[0]
    idx = parts[1]
    src = parts[2]
    rnd = parts[3]
    return sum(1 for a, b in zip((rsi, idx, src, rnd), baseline) if a != b)


def run_sweep(
    mt4_path: Path,
    candles_path: Path,
    out_dir: Path,
    trade_diff_path: Path | None,
    day_offset_h: int = 5,
    pm_window: int = 3,
) -> dict:
    print("STEP 1/4 Load inputs...")
    mt4_trades = read_sq_export(mt4_path, "MT4")
    first_divergence_ts = None
    if trade_diff_path and trade_diff_path.exists():
        data = json.loads(trade_diff_path.read_text(encoding="utf-8"))
        fd = data.get("first_divergence", {})
        details = fd.get("details", {})
        first_divergence_ts = details.get("bar_ts")
    print("  OK")

    rsi_methods = ["wilder", "ema_gains"]
    idx_modes = ["bar_closed", "bar_current"]
    price_sources = ["close", "typical"]
    roundings = [("none", None), ("digits5", 5)]

    print("STEP 2/4 Build variants (16)...")
    variants = []
    for rsi in rsi_methods:
        for idx in idx_modes:
            for src in price_sources:
                for rnd_name, rnd_val in roundings:
                    variants.append({
                        "rsi_method": rsi,
                        "idx_mode": idx,
                        "price_source": src,
                        "rounding": rnd_name,
                        "rounding_digits": rnd_val,
                    })
    print("  OK")

    base_rows = load_candles(candles_path, None)
    sorted_ts = sorted(r["ts"] for r in base_rows)
    ts_to_idx = {r["ts"]: i for i, r in enumerate(base_rows)}

    results = []
    for i, v in enumerate(variants):
        print(f"STEP 3/4 Evaluate variant {i + 1}/16...")
        rows = load_candles(candles_path, v["rounding_digits"])
        rows = apply_price_source(rows, v["price_source"])
        rows = compute_variant(rows, v["rsi_method"], v["idx_mode"])
        st, sp1, sp3 = score_variant(rows, sorted_ts, ts_to_idx, mt4_trades, day_offset_h, pm_window)
        variant_id = f"{v['rsi_method']}_{v['idx_mode']}_{v['price_source']}_{v['rounding']}"
        score = _score_aggregate(st, sp1, sp3)
        results.append({
            "variant_id": variant_id,
            "rsi_method": v["rsi_method"],
            "idx_mode": v["idx_mode"],
            "price_source": v["price_source"],
            "rounding": v["rounding"],
            "rounding_digits": v["rounding_digits"],
            "mt4_entries_total": len(mt4_trades),
            "signal_true_at_t": st,
            "signal_true_within_pm1": sp1,
            "signal_true_within_pm3": sp3,
            "score": score,
            "rows": rows,
        })

    print("STEP 4/4 Write artifacts + best...")
    best = max(results, key=lambda r: (r["score"], -_baseline_distance(r["variant_id"])))
    baseline = next(r for r in results if r["variant_id"] == "wilder_bar_closed_close_none")

    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "signal_def_sweep.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        cols = ["variant_id", "rsi_method", "idx_mode", "price_source", "rounding",
                "mt4_entries_total", "signal_true_at_t", "signal_true_within_pm1",
                "signal_true_within_pm3", "score"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in cols})

    if best["idx_mode"] != "bar_closed":
        next_step = "APPLY_IDX_MODE_TO_RUNNER"
    elif best["price_source"] != "close" or best["rsi_method"] != "wilder":
        next_step = "APPLY_RSI_SOURCE_TO_RUNNER"
    elif best["score"] <= baseline["score"]:
        next_step = "ORACLE_OR_DATA_GAPS"
    else:
        next_step = "APPLY_BEST_SIGNAL_DEF"

    best_json = {
        "best_signal_def": best["variant_id"],
        "params": {
            "rsi_method": best["rsi_method"],
            "idx_mode": best["idx_mode"],
            "price_source": best["price_source"],
            "rounding": best["rounding"],
        },
        "score": best["score"],
        "signal_true_at_t": best["signal_true_at_t"],
        "justification": f"max score={best['score']} (at_t={best['signal_true_at_t']}, pm1={best['signal_true_within_pm1']}, pm3={best['signal_true_within_pm3']})",
        "baseline": baseline["variant_id"],
        "baseline_score": baseline["score"],
        "baseline_signal_true_at_t": baseline["signal_true_at_t"],
        "NEXT_STEP": next_step,
    }
    (out_dir / "best_signal_def.json").write_text(
        json.dumps(best_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "best_signal_def.txt").write_text(best["variant_id"], encoding="utf-8")

    windows_dir = out_dir / "first_divergence_windows"
    windows_dir.mkdir(exist_ok=True)
    if first_divergence_ts and first_divergence_ts in ts_to_idx:
        idx = ts_to_idx[first_divergence_ts]
        for name, res in [("baseline", baseline), ("best", best)]:
            rows = res["rows"]
            start = max(0, idx - 5)
            end = min(len(rows), idx + 6)
            with open(windows_dir / f"{name}_window.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "date_utc", "open", "high", "low", "close", "ema200", "rsi14", "atr14", "signal", "mt4_entry_here"])
                for i in range(start, end):
                    r = rows[i]
                    mt4_here = 1 if r["ts"] == first_divergence_ts else 0
                    w.writerow([
                        r["ts"], r.get("date_utc", ""), r["open"], r["high"], r["low"], r["close"],
                        r.get("ema200"), r.get("rsi14"), r.get("atr14"), r.get("signal", 0), mt4_here,
                    ])

    print(f"\nbest_signal_def = {best['variant_id']}")
    print(f"score = {best['score']} (baseline {baseline['score']})")
    print(f"signal_true_at_t: baseline={baseline['signal_true_at_t']}, best={best['signal_true_at_t']}")
    return best_json


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.36 Signal Definition Sweep")
    parser.add_argument("--mt4", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument("--candles", default="lab/runner/out_compare/indicators_LAB_full.csv")
    parser.add_argument("--day-offset-h", type=int, default=5)
    parser.add_argument("--pm-window", type=int, default=3)
    parser.add_argument(
        "--outdir",
        default="lab/runner/out_compare/artifacts/T8.36/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    mt4_path = root / args.mt4
    candles_path = root / args.candles if args.candles != "auto" else root / "lab/runner/out_compare/indicators_LAB_full.csv"
    out_dir = root / args.outdir
    trade_diff_path = root / "lab/runner/out_compare/trade_diff_report.json"

    if not mt4_path.exists():
        print(f"ERROR: MT4 CSV no trobat: {mt4_path}")
        return 1
    if not candles_path.exists():
        print(f"ERROR: Candles/indicators CSV no trobat: {candles_path}")
        return 1

    run_sweep(mt4_path, candles_path, out_dir, trade_diff_path, args.day_offset_h, args.pm_window)
    print(f"Artifacts → {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
