#!/usr/bin/env python3
"""
T9.15 — Gate paritat SQ sobre Parquet v2 ticks.

1. Fetch candles via API (source=dukascopy = Parquet ticks)
2. Simula trades: RSI(14)[1]<35, exit 60 bars
3. Compara amb oracle SQ (expected_trades.csv)
4. Escriu artifacts: bs_trades.csv, sq_trades.csv, trade_diff_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

# Rang gold: 2026-02-01 → 2026-02-03
FROM_DATE = "2026-02-01"
TO_DATE = "2026-02-03"
SYMBOL = "EURUSD"
RSI_PERIOD = 14
RSI_THRESHOLD = 35
EXIT_BARS = 60
FRIDAY_WEEKDAY = 4
SUNDAY_WEEKDAY = 6
WEEKEND_FRIDAY_HOUR_UTC = 22
WEEKEND_SUNDAY_HOUR_UTC = 22


def _is_weekend_blocked(ts_utc: int) -> bool:
    dt = datetime.fromtimestamp(ts_utc, tz=timezone.utc)
    wd = dt.weekday()
    h = dt.hour
    if wd == FRIDAY_WEEKDAY and h >= WEEKEND_FRIDAY_HOUR_UTC:
        return True
    if wd == 5:
        return True
    if wd == SUNDAY_WEEKDAY and h < WEEKEND_SUNDAY_HOUR_UTC:
        return True
    return False


def fetch_candles_api(base_url: str, symbol: str, from_ts: int, to_ts: int) -> pd.DataFrame:
    """Fetch M1 via API (source=dukascopy = Parquet ticks)."""
    import urllib.request
    import urllib.error

    url = f"{base_url.rstrip('/')}/data/ohlcv/{symbol}?tf=1m&from_ts={from_ts}&to_ts={to_ts}&limit=5000&source=dukascopy"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    rows = data.get("candles", [])
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = df["ts"].astype(int)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df.sort_values("ts").reset_index(drop=True)


def compute_rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    from application.data.indicators_mt4_like import rsi_wilder
    return rsi_wilder(close, period)


def simulate_trades(df: pd.DataFrame) -> list[dict]:
    """RSI[1]<35 → entry open[i], exit open[i+60]."""
    rsi = compute_rsi_wilder(df["close"], RSI_PERIOD)
    n = len(df)
    trades = []
    in_position = False
    exit_at_bar = -1
    pending_entry_ts = 0
    pending_entry_price = 0.0

    for i in range(1, n):
        ts = int(df.iloc[i]["ts"])
        if in_position:
            if i >= exit_at_bar:
                exit_price = float(df.iloc[i]["open"])
                trades.append({
                    "entry_ts": pending_entry_ts,
                    "exit_ts": ts,
                    "entry_price": pending_entry_price,
                    "exit_price": exit_price,
                })
                in_position = False
            continue
        if _is_weekend_blocked(ts):
            continue
        rsi_prev = rsi.iloc[i - 1]
        if pd.isna(rsi_prev) or rsi_prev >= RSI_THRESHOLD:
            continue
        if i + EXIT_BARS >= n:
            continue
        pending_entry_ts = int(df.iloc[i]["ts"])
        pending_entry_price = float(df.iloc[i]["open"])
        in_position = True
        exit_at_bar = i + EXIT_BARS
    return trades


def load_sq_trades(path: Path) -> list[dict]:
    """Carrega expected_trades.csv: entry_ts,exit_ts,entry_price,exit_price."""
    trades = []
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                trades.append({
                    "entry_ts": int(row["entry_ts"]),
                    "exit_ts": int(row["exit_ts"]),
                    "entry_price": float(row["entry_price"]),
                    "exit_price": float(row["exit_price"]),
                })
            except (KeyError, ValueError):
                continue
    return trades


def compare_trades(bs: list[dict], sq: list[dict], ts_tol_s: int = 0) -> dict:
    matched = 0
    mismatches = []
    for i, st in enumerate(sq):
        found = False
        for bt in bs:
            if abs(bt["entry_ts"] - st["entry_ts"]) <= ts_tol_s and abs(bt["exit_ts"] - st["exit_ts"]) <= ts_tol_s:
                matched += 1
                found = True
                break
        if not found and len(mismatches) < 10:
            mismatches.append({
                "sq_idx": i + 1,
                "entry_ts": st["entry_ts"],
                "exit_ts": st["exit_ts"],
                "entry_price": st["entry_price"],
            })
    match_rate = 100.0 * matched / len(sq) if sq else 0.0
    return {
        "bs_count": len(bs),
        "sq_count": len(sq),
        "matched": matched,
        "match_rate": round(match_rate, 2),
        "pass": match_rate >= 95.0,
        "mismatches": mismatches,
        "first_mismatch_ts": mismatches[0]["entry_ts"] if mismatches else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="T9.15 Gate paritat SQ")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--sq-trades", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("lab/out/BS.T9.15"))
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from_dt = datetime.strptime(FROM_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(TO_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    print("STEP 1 — Fetch candles (source=dukascopy = ticks)...")
    df = fetch_candles_api(args.base_url, SYMBOL, from_ts, to_ts)
    if len(df) == 0:
        print("ERROR: 0 candles. Verifica API i DUKASCOPY_PARQUET_ACTIVE=ticks.")
        return 1
    print(f"  candles: {len(df)}")

    print("STEP 2 — Simulate BS trades...")
    bs_trades = simulate_trades(df)
    pd.DataFrame(bs_trades).to_csv(out / "bs_trades.csv", index=False)
    print(f"  bs_trades: {len(bs_trades)}")

    print("STEP 3 — Load SQ oracle...")
    sq_trades = load_sq_trades(args.sq_trades)
    pd.DataFrame(sq_trades).to_csv(out / "sq_trades.csv", index=False)
    print(f"  sq_trades: {len(sq_trades)}")

    print("STEP 4 — Compare...")
    report = compare_trades(bs_trades, sq_trades)
    report["range"] = f"{FROM_DATE} → {TO_DATE}"
    report["symbol"] = SYMBOL
    report["strategy"] = "RSI35_exit60_M1"

    with open(out / "trade_diff_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if report["mismatches"]:
        pd.DataFrame(report["mismatches"]).to_csv(out / "trade_diff_report.csv", index=False)
        print(f"  first_mismatch: ts={report['first_mismatch_ts']}")
        # first_mismatch_window: candles al voltant del primer mismatch (±2h + exit)
        fm_ts = report["first_mismatch_ts"]
        if fm_ts and len(df) > 0:
            margin_s = 120 * 60  # ±2h
            mask = (df["ts"] >= fm_ts - margin_s) & (df["ts"] <= fm_ts + (EXIT_BARS + 60) * 60)
            df[mask].to_csv(out / "first_mismatch_window.csv", index=False)

    print(f"\n  matched: {report['matched']}/{report['sq_count']} ({report['match_rate']}%)")
    print(f"  PASS: {report['pass']}")

    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
