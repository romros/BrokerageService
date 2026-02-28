"""
application/tools/export_indicators_csv.py — T8.21

Exporta indicadors LAB (EMA200, RSI14, ATR14) barra-a-barra per un rang D1.

Ús:
    python3 -m application.tools.export_indicators_csv \\
        --symbol EURUSD \\
        --from 2012-01-01 \\
        --to 2014-01-01 \\
        --base-url http://localhost:8081 \\
        --out lab/runner/out_compare/indicators_lab_2012_2013.csv

Output CSV:
    ts, date_utc, open, high, low, close,
    ema200_lab, rsi14_lab, atr14_lab,
    signal (1 si Close[prev]>EMA[prev] AND RSI[prev]<35)

Notes:
    - Warmup de 300 barres D1 ABANS de --from per estabilitzar EMA200/RSI/ATR
    - day_offset_h=5 (05:00 UTC = MT4 Dukascopy D1 boundary)
    - Fórmules idèntiques a lab/runner/backtest/run_backtest.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Afegim el root al path si cal
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reutilitzem les funcions del runner LAB
from lab.runner.backtest.run_backtest import (
    fetch_candles_1m,
    aggregate_to_tf,
    candles_to_df,
    compute_atr,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAY_OFFSET_H = 5          # 05:00 UTC = MT4 D1 boundary
WARMUP_BARS = 300         # barres D1 addicionals per estabilitzar EMA200
TF_MINUTES = 1440         # D1
API_PAGE_LIMIT = 5000


# ---------------------------------------------------------------------------
# Càlcul indicadors (fórmules idèntiques al runner)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    """EMA Wilder equivalent a MT4 iMA MODE_EMA."""
    return series.ewm(span=period, adjust=False).mean()


def _rsi_wilder(series: pd.Series, period: int) -> pd.Series:
    """RSI Wilder equivalent a MT4 iRSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_indicators(
    base_url: str,
    symbol: str,
    from_date: str,
    to_date: str,
    out_path: Path,
    warmup_bars: int = WARMUP_BARS,
    day_offset_h: int = DAY_OFFSET_H,
) -> int:
    """
    Exporta indicadors barra-a-barra a CSV.
    Retorna 0=OK, 1=error.
    """
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    day_offset_s = day_offset_h * 3600

    # Warmup: ampliar el fetch
    warmup_days = (warmup_bars * TF_MINUTES) // (24 * 60) + 1
    warmup_from_dt = from_dt - timedelta(days=warmup_days)
    warmup_from_ts = int(warmup_from_dt.timestamp())

    print(f"FETCH candles 1m [{warmup_from_dt.date()} → {to_date}] (warmup_bars={warmup_bars}, warmup_days={warmup_days}) ...")
    try:
        candles_1m = fetch_candles_1m(base_url, symbol, warmup_from_ts, to_ts)
    except RuntimeError as exc:
        print(f"ERROR fetch: {exc}")
        return 1

    if not candles_1m:
        print("ERROR: cap candle carregada")
        return 1

    print(f"  candles_1m={len(candles_1m)}")

    # Agrega a D1 amb offset MT4
    candles_d1 = aggregate_to_tf(candles_1m, TF_MINUTES, day_offset_seconds=day_offset_s)
    print(f"  candles_d1={len(candles_d1)}")

    # DataFrame
    df = candles_to_df(candles_d1)

    # Indicadors
    ema200 = _ema(df["close"], 200)
    rsi14 = _rsi_wilder(df["close"], 14)
    atr14 = compute_atr(df, 14)

    # Senyals (Close[i-1] > EMA200[i-1] AND RSI14[i-1] < 35)
    signals = pd.Series(0, index=df.index, dtype=int)
    for i in range(1, len(df)):
        prev_close = df["close"].iloc[i - 1]
        prev_ema = ema200.iloc[i - 1]
        prev_rsi = rsi14.iloc[i - 1]
        if np.isnan(prev_ema) or np.isnan(prev_rsi):
            continue
        if prev_close > prev_ema and prev_rsi < 35.0:
            signals.iloc[i] = 1

    # Exporta — filtrant pel rang sol·licitat [from_ts, to_ts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ts", "date_utc",
            "open", "high", "low", "close",
            "ema200_lab", "rsi14_lab", "atr14_lab",
            "signal_lab",
        ])
        for i, (idx, row) in enumerate(df.iterrows()):
            ts = int(row["_ts"])
            if ts < from_ts or ts >= to_ts:
                continue
            date_utc = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            ema_val = ema200.iloc[i]
            rsi_val = rsi14.iloc[i]
            atr_val = atr14.iloc[i]
            sig_val = signals.iloc[i]

            writer.writerow([
                ts,
                date_utc,
                round(float(row["open"]), 6),
                round(float(row["high"]), 6),
                round(float(row["low"]), 6),
                round(float(row["close"]), 6),
                round(float(ema_val), 6) if not np.isnan(ema_val) else "",
                round(float(rsi_val), 6) if not np.isnan(rsi_val) else "",
                round(float(atr_val), 6) if not np.isnan(atr_val) else "",
                int(sig_val),
            ])
            rows_written += 1

    print(f"  rows_written={rows_written} → {out_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export LAB indicators to CSV (T8.21)")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--out", required=True, help="Path fitxer CSV de sortida")
    parser.add_argument("--warmup-bars", type=int, default=WARMUP_BARS)
    parser.add_argument("--day-offset-h", type=int, default=DAY_OFFSET_H)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(export_indicators(
        base_url=args.base_url,
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        out_path=Path(args.out),
        warmup_bars=args.warmup_bars,
        day_offset_h=args.day_offset_h,
    ))
