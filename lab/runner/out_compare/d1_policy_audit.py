"""
T8.34 — D1 Series Shape Audit: policies Sunday bar (baseline, drop_sunday, merge_sunday_into_monday).

Recomputa EMA/RSI/ATR + signal per cada policy i mesura impacte al signal landscape.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.compare_trades import read_sq_export
from lab.runner.out_compare.trade_diff_analyzer import _ts_to_bar_start


def _ema_sma_seed(close: list[float], period: int) -> list[float]:
    """EMA amb seed SMA, mateix que indicators_mt4_like."""
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
    """RSI Wilder."""
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


def _atr_wilder(high: list[float], low: list[float], close: list[float], period: int) -> list[float]:
    """ATR Wilder."""
    n = len(close)
    out = [float("nan")] * n
    if n < period:
        return out
    prev_c = [close[0]] + close[:-1]
    tr = [
        max(h - l, abs(h - pc), abs(l - pc))
        for h, l, pc in zip(high, low, prev_c)
    ]
    tr[0] = high[0] - low[0]
    out[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out

NY_TZ = ZoneInfo("America/New_York")
RSI_THRESHOLD = 35.0
DAY_OFFSET_H = 5


def _ts_to_sunday_ny(ts: int) -> bool:
    """True si el bar ts (05:00 UTC) cau en diumenge a NY."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    dt_ny = dt.astimezone(NY_TZ)
    return dt_ny.weekday() == 6


def _safe_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def load_indicators_rows(path: Path) -> list[dict]:
    """Carrega indicators CSV com a llista de dicts."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                ts = int(r["ts"])
                o = _safe_float(r.get("open"))
                h = _safe_float(r.get("high"))
                l_ = _safe_float(r.get("low"))
                c = _safe_float(r.get("close"))
                if c is None:
                    continue
                rows.append({
                    "ts": ts,
                    "date_utc": r.get("date_utc", ""),
                    "open": o or c,
                    "high": h or c,
                    "low": l_ or c,
                    "close": c,
                    "is_sunday_ny": _ts_to_sunday_ny(ts),
                })
            except (KeyError, ValueError):
                continue
    return rows


def policy_baseline(rows: list[dict]) -> list[dict]:
    """Tal qual."""
    return [dict(r) for r in rows]


def policy_drop_sunday(rows: list[dict]) -> list[dict]:
    """Elimina barres diumenge NY."""
    return [dict(r) for r in rows if not r["is_sunday_ny"]]


def policy_merge_sunday_into_monday(rows: list[dict]) -> list[dict]:
    """Fusiona OHLC diumenge dins dilluns, elimina diumenge."""
    ts_to_idx = {r["ts"]: i for i, r in enumerate(rows)}
    out = [dict(r) for r in rows]
    to_drop = set()
    for r in rows:
        if not r["is_sunday_ny"]:
            continue
        ts = r["ts"]
        next_rows = [x for x in out if x["ts"] > ts and x["ts"] not in to_drop]
        if not next_rows:
            to_drop.add(ts)
            continue
        mon = min(next_rows, key=lambda x: x["ts"])
        mon["open"] = r["open"]
        mon["high"] = max(r["high"], mon["high"])
        mon["low"] = min(r["low"], mon["low"])
        to_drop.add(ts)
    return [r for r in out if r["ts"] not in to_drop]


def recompute_indicators(rows: list[dict]) -> list[dict]:
    """EMA200, RSI14, ATR14 + signal_lab (Close[i-1]>EMA[i-1] && RSI[i-1]<35)."""
    close = [r["close"] for r in rows]
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    ema_arr = _ema_sma_seed(close, 200)
    rsi_arr = _rsi_wilder(close, 14)
    atr_arr = _atr_wilder(high, low, close, 14)
    out = []
    for i, r in enumerate(rows):
        o = dict(r)
        def _v(x):
            return None if (isinstance(x, float) and math.isnan(x)) else x
        o["ema200_lab"] = _v(ema_arr[i])
        o["rsi14_lab"] = _v(rsi_arr[i])
        o["atr14_lab"] = _v(atr_arr[i])
        if i == 0:
            o["signal_lab"] = 0
        else:
            close_prev = close[i - 1]
            ema_prev = ema_arr[i - 1]
            rsi_prev = rsi_arr[i - 1]
            if math.isnan(ema_prev):
                ema_prev = close_prev
            if math.isnan(rsi_prev):
                rsi_prev = 50.0
            o["signal_lab"] = 1 if (close_prev > ema_prev and rsi_prev < RSI_THRESHOLD) else 0
        out.append(o)
    return out


def _policy_to_indicators(rows: list[dict]) -> dict[int, dict]:
    """Rows -> dict ts -> {signal_lab, rsi14_lab, ...}."""
    return {
        r["ts"]: {
            "ts": r["ts"],
            "date_utc": r.get("date_utc", ""),
            "close": r.get("close"),
            "ema200_lab": r.get("ema200_lab"),
            "rsi14_lab": r.get("rsi14_lab"),
            "atr14_lab": r.get("atr14_lab"),
            "signal_lab": r.get("signal_lab", 0),
        }
        for r in rows
    }


def _find_bar_index(sorted_ts: list[int], bar_ts: int) -> int:
    """Index del bar que conté bar_ts; si no existeix, bar més proper."""
    idx = bisect.bisect_right(sorted_ts, bar_ts) - 1
    if idx < 0:
        return 0
    return idx


def score_policy(
    indicators: dict[int, dict],
    sorted_ts: list[int],
    mt4_trades: list[dict],
    unmatched_bar_ts: set[int],
) -> dict:
    """Compta signal_true_at_t, signal_true_within_pm1 per MT4 entries i unmatched."""
    signal_true_at_t = 0
    signal_true_within_pm1 = 0
    n_checked = 0
    for mt in mt4_trades:
        bar_ts = _ts_to_bar_start(mt["entry_time"], day_offset_h=DAY_OFFSET_H)
        idx = _find_bar_index(sorted_ts, bar_ts)
        n_checked += 1
        at_t = indicators.get(sorted_ts[idx], {}).get("signal_lab", 0) == 1 if idx < len(sorted_ts) else False
        at_m1 = indicators.get(sorted_ts[idx - 1], {}).get("signal_lab", 0) == 1 if idx > 0 else False
        at_p1 = indicators.get(sorted_ts[idx + 1], {}).get("signal_lab", 0) == 1 if idx + 1 < len(sorted_ts) else False
        if at_t:
            signal_true_at_t += 1
        if at_t or at_m1 or at_p1:
            signal_true_within_pm1 += 1

    unmatched_at_t = 0
    unmatched_within_pm1 = 0
    for bar_ts in unmatched_bar_ts:
        if bar_ts not in sorted_ts:
            idx = _find_bar_index(sorted_ts, bar_ts)
        else:
            idx = sorted_ts.index(bar_ts)
        at_t = indicators.get(sorted_ts[idx], {}).get("signal_lab", 0) == 1 if idx < len(sorted_ts) else False
        at_m1 = indicators.get(sorted_ts[idx - 1], {}).get("signal_lab", 0) == 1 if idx > 0 else False
        at_p1 = indicators.get(sorted_ts[idx + 1], {}).get("signal_lab", 0) == 1 if idx + 1 < len(sorted_ts) else False
        if at_t:
            unmatched_at_t += 1
        if at_t or at_m1 or at_p1:
            unmatched_within_pm1 += 1

    return {
        "signal_true_at_t": signal_true_at_t,
        "signal_true_within_pm1": signal_true_within_pm1,
        "n_mt4_checked": n_checked,
        "unmatched_signal_at_t": unmatched_at_t,
        "unmatched_signal_within_pm1": unmatched_within_pm1,
        "n_unmatched_bars": len(unmatched_bar_ts),
    }


def run_audit(
    indicators_path: Path,
    mt4_path: Path,
    trade_diff_path: Path,
    out_dir: Path,
) -> dict:
    rows_raw = load_indicators_rows(indicators_path)
    mt4_trades = read_sq_export(mt4_path, "MT4")

    unmatched_bar_ts = set()
    first_divergence_bar_ts = None
    if trade_diff_path.exists():
        data = json.loads(trade_diff_path.read_text(encoding="utf-8"))
        for t in data.get("trades", []):
            if t.get("status") == "UNMATCHED":
                d = t.get("details") or {}
                bt = d.get("bar_ts")
                if bt:
                    unmatched_bar_ts.add(bt)
        fd = data.get("first_divergence", {})
        fd_details = fd.get("details", {})
        if fd_details.get("bar_ts"):
            first_divergence_bar_ts = fd_details["bar_ts"]
            unmatched_bar_ts.add(first_divergence_bar_ts)

    out_dir.mkdir(parents=True, exist_ok=True)

    policies = {
        "baseline": policy_baseline,
        "drop_sunday": policy_drop_sunday,
        "merge_sunday_into_monday": policy_merge_sunday_into_monday,
    }
    n_sunday_raw = sum(1 for r in rows_raw if r["is_sunday_ny"])

    results = []
    for name, policy_fn in policies.items():
        print(f"  Policy {name}...")
        rows = policy_fn(rows_raw)
        rows = recompute_indicators(rows)
        ind = _policy_to_indicators(rows)
        sorted_ts = sorted(ind.keys())
        sc = score_policy(ind, sorted_ts, mt4_trades, unmatched_bar_ts)

        fd_rsi = fd_signal = None
        if first_divergence_bar_ts is not None:
            idx = _find_bar_index(sorted_ts, first_divergence_bar_ts)
            if idx < len(sorted_ts):
                row = ind.get(sorted_ts[idx], {})
                fd_rsi = row.get("rsi14_lab")
                fd_signal = row.get("signal_lab", 0) == 1

        row = {
            "policy": name,
            "n_sunday_bars": n_sunday_raw,
            "n_bars": len(rows),
            "signal_true_at_t": sc["signal_true_at_t"],
            "signal_true_within_pm1": sc["signal_true_within_pm1"],
            "first_divergence_rsi_at_t": fd_rsi,
            "first_divergence_signal_at_t": fd_signal,
            "unmatched_signal_at_t": sc["unmatched_signal_at_t"],
            "unmatched_signal_within_pm1": sc["unmatched_signal_within_pm1"],
        }
        results.append(row)

        window_path = out_dir / f"first_divergence_window_{name}.csv"
        if first_divergence_bar_ts is not None:
            idx = _find_bar_index(sorted_ts, first_divergence_bar_ts)
            start = max(0, idx - 5)
            end = min(len(sorted_ts), idx + 6)
            with open(window_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "date_utc", "close", "ema200_lab", "rsi14_lab", "atr14_lab", "signal_lab"])
                for i in range(start, end):
                    r = ind[sorted_ts[i]]
                    w.writerow([
                        r["ts"], r["date_utc"], r["close"], r["ema200_lab"], r["rsi14_lab"],
                        r["atr14_lab"], r["signal_lab"],
                    ])

    best = max(results, key=lambda r: (r["signal_true_at_t"], r["signal_true_within_pm1"]))
    if best["signal_true_at_t"] > results[0]["signal_true_at_t"] or best["signal_true_within_pm1"] > results[0]["signal_true_within_pm1"]:
        next_step = f"RERUN_BACKTEST_WITH_POLICY={best['policy']}"
    else:
        next_step = "RSI_VARIANT_SWEEP"

    report = {
        "policies": results,
        "best_policy": best["policy"],
        "NEXT_STEP": next_step,
        "first_divergence_bar_ts": first_divergence_bar_ts,
    }
    csv_path = out_dir / "d1_policy_audit.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    json_path = out_dir / "d1_policy_audit.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nNEXT_STEP = {next_step}")
    print(f"best_policy = {best['policy']}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.34 D1 Policy Audit")
    parser.add_argument("--indicators", default="lab/runner/out_compare/indicators_LAB_full.csv")
    parser.add_argument("--mt4", default="lab/runner/out_compare/simpleexample_out_MT4.csv")
    parser.add_argument("--trade-diff", default="lab/runner/out_compare/trade_diff_report.json")
    parser.add_argument(
        "--outdir",
        default="lab/runner/out_compare/artifacts/T8.34/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    indicators_path = root / args.indicators
    mt4_path = root / args.mt4
    trade_diff_path = root / args.trade_diff
    out_dir = root / args.outdir

    if not indicators_path.exists():
        print("ERROR: Indicators CSV no trobat.")
        return 1
    if not mt4_path.exists():
        print("ERROR: MT4 CSV no trobat.")
        return 1

    print("[T8.34] D1 Policy Audit...")
    run_audit(indicators_path, mt4_path, trade_diff_path, out_dir)
    print(f"Artifacts → {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
