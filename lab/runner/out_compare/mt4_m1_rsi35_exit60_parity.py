"""
lab/runner/out_compare/mt4_m1_rsi35_exit60_parity.py — T8.39 Paritat M1 candles + 17 trades.

Harness de paritat "de baix a dalt" per validar:
  1. Candles M1 LAB = MT4/SQ (OHLC per timestamp)
  2. RSI Wilder PRICE_CLOSE [1] < 35
  3. Reproducció exacta 17 trades (entry open[i], exit open[i+60])

Estratègia:
  - Entry: RSI(14, PRICE_CLOSE)[1] < 35 (On Bar Open)
  - Exit: After 60 bars (al open de bar i+60)
  - Duplicate trades disabled (max 1 posició)
  - Don't trade weekends (Fri 17:00 → Sun 17:00 UTC-05)

Ús:
  python3 lab/runner/out_compare/mt4_m1_rsi35_exit60_parity.py [--base-url URL] [--mt4-trades PATH]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUT_COMPARE_ROOT = Path(__file__).resolve().parent
MT4_ORACLE_DIR = OUT_COMPARE_ROOT / "mt4_oracle"
ARTIFACTS_BASE = OUT_COMPARE_ROOT / "artifacts" / "T8.39" / "EURUSD" / "1m" / "2026-02-01_2026-02-02"

SYMBOL = "EURUSD"
FROM_DATE = "2026-02-01"
TO_DATE = "2026-02-03"  # exclusiu, per cobrir exit del darrer trade
RSI_PERIOD = 14
RSI_THRESHOLD = 35
EXIT_BARS = 60
OHLC_TOLERANCE = 1e-5

# Weekend block: Fri 17:00 UTC-05 → Sun 17:00 UTC-05
# UTC-05: +5h per obtenir UTC → Fri 22:00 UTC, Sun 22:00 UTC
WEEKEND_FRIDAY_HOUR_UTC = 22
WEEKEND_SUNDAY_HOUR_UTC = 22
FRIDAY_WEEKDAY = 4
SUNDAY_WEEKDAY = 6

# MT4 SQ export format
SQ_DATE_FMT = "%Y.%m.%d %H:%M:%S"
UTC_MINUS_05_OFFSET = timedelta(hours=5)


def _ts_to_utc_minus_05(ts_utc: int) -> datetime:
    """Converteix epoch UTC a datetime UTC-05 (per comparació)."""
    dt_utc = datetime.fromtimestamp(ts_utc, tz=timezone.utc)
    return (dt_utc - UTC_MINUS_05_OFFSET).replace(tzinfo=timezone.utc)


def _utc_minus_05_to_ts(dt_utc05: datetime) -> int:
    """Converteix datetime UTC-05 a epoch UTC."""
    return int((dt_utc05 + UTC_MINUS_05_OFFSET).timestamp())


def _is_weekend_blocked(ts_utc: int) -> bool:
    """True si ts_utc cau dins Fri 22:00 UTC → Sun 22:00 UTC."""
    dt = datetime.fromtimestamp(ts_utc, tz=timezone.utc)
    wd = dt.weekday()
    h = dt.hour
    if wd == FRIDAY_WEEKDAY and h >= WEEKEND_FRIDAY_HOUR_UTC:
        return True
    if wd == 5:  # Saturday
        return True
    if wd == SUNDAY_WEEKDAY and h < WEEKEND_SUNDAY_HOUR_UTC:
        return True
    return False


# ---------------------------------------------------------------------------
# Step 2 — Export candles LAB (Dukascopy BI5)
# ---------------------------------------------------------------------------

def _fetch_lab_candles_bi5(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Obté candles M1 via Dukascopy BI5."""
    from application.data.dukascopy_bi5 import fetch_m1_range

    candles = fetch_m1_range(symbol, from_date, to_date, rate_limit_s=0.1)
    if not candles:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    df = df.rename(columns={"ts_utc": "ts", "vol": "volume"})
    df = df[["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)
    return df


def _fetch_lab_candles_api(base_url: str, symbol: str, from_ts: int, to_ts: int) -> Optional[pd.DataFrame]:
    """Obté candles M1 via API (historical_datalayer)."""
    import urllib.request
    import urllib.error

    url = f"{base_url.rstrip('/')}/data/ohlcv/{symbol}?tf=1m&from_ts={from_ts}&to_ts={to_ts}&limit=10000"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None

    rows = data.get("candles", [])
    if not rows:
        return None

    # Format: [ts, o, h, l, c, v]
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = df["ts"].astype(int)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df.sort_values("ts").reset_index(drop=True)


def fetch_lab_candles(symbol: str, from_date: str, to_date: str, base_url: Optional[str]) -> pd.DataFrame:
    """Obté candles LAB: prova API, fallback BI5."""
    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")
    from_ts = int(from_dt.replace(tzinfo=timezone.utc).timestamp())
    to_ts = int(to_dt.replace(tzinfo=timezone.utc).timestamp())

    if base_url:
        df = _fetch_lab_candles_api(base_url, symbol, from_ts, to_ts)
        if df is not None and len(df) > 0:
            return df

    return _fetch_lab_candles_bi5(symbol, from_date, to_date)


def _checksum_csv(df: pd.DataFrame) -> str:
    """Hash per idempotència."""
    h = hashlib.sha256()
    h.update(df.to_csv(index=False).encode("utf-8"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Step 3 — Candle parity
# ---------------------------------------------------------------------------

def load_mt4_candles(path: Path) -> Optional[pd.DataFrame]:
    """Carrega MT4 candles CSV: ts, open, high, low, close (UTC-05 o UTC)."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    required = ["ts", "open", "high", "low", "close"]
    if not all(c in df.columns for c in required):
        return None
    return df


def compare_candles(lab_df: pd.DataFrame, mt4_df: pd.DataFrame, tol: float = OHLC_TOLERANCE) -> dict:
    """Compara candles LAB vs MT4. Retorna report."""
    lab_by_ts = lab_df.set_index("ts")
    mt4_by_ts = mt4_df.set_index("ts")
    common = lab_by_ts.index.intersection(mt4_by_ts.index)
    mismatches = []
    for ts in common[:500]:  # limit
        lr = lab_by_ts.loc[ts]
        mr = mt4_by_ts.loc[ts]
        for col in ["open", "high", "low", "close"]:
            if abs(float(lr[col]) - float(mr[col])) > tol:
                mismatches.append({"ts": int(ts), "col": col, "lab": float(lr[col]), "mt4": float(mr[col])})
                if len(mismatches) >= 5:
                    break
        if len(mismatches) >= 5:
            break
    matched = len(common)
    total_mt4 = len(mt4_by_ts)
    pct = 100.0 * matched / total_mt4 if total_mt4 else 0.0
    return {
        "matched_rows": matched,
        "total_mt4": total_mt4,
        "pct_matched": round(pct, 2),
        "mismatches": mismatches,
        "pass": len(mismatches) == 0 and matched == total_mt4,
    }


# ---------------------------------------------------------------------------
# Step 4 — RSI parity
# ---------------------------------------------------------------------------

def compute_rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    """RSI Wilder (MT4 iRSI PRICE_CLOSE)."""
    from application.data.indicators_mt4_like import rsi_wilder
    return rsi_wilder(close, period)


# ---------------------------------------------------------------------------
# Step 5 — Simulació trades LAB
# ---------------------------------------------------------------------------

def simulate_trades(df: pd.DataFrame) -> list[dict]:
    """
    Simula trades: rsi[i-1] < 35 → entry at open[i], exit at open[i+60].
    Duplicate disabled, weekend blocked.
    """
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


# ---------------------------------------------------------------------------
# Step 6 — Trade parity
# ---------------------------------------------------------------------------

def load_mt4_trades(path: Path) -> list[dict]:
    """Carrega MT4 trades (SQ export format). Retorna [{entry_ts, exit_ts, entry_price, exit_price}]."""
    if not path.exists():
        return []

    trades = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ot = row.get("Open time", "").strip().strip('"')
            ct = row.get("Close time", "").strip().strip('"')
            if not ot or not ct:
                continue
            try:
                dt_open = datetime.strptime(ot, SQ_DATE_FMT)
                dt_close = datetime.strptime(ct, SQ_DATE_FMT)
            except ValueError:
                continue
            entry_ts = int((dt_open + UTC_MINUS_05_OFFSET).timestamp())
            exit_ts = int((dt_close + UTC_MINUS_05_OFFSET).timestamp())
            op = float(row.get("Open price", 0).replace(",", ".").strip('"'))
            cp = float(row.get("Close price", 0).replace(",", ".").strip('"'))
            trades.append({
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_price": op,
                "exit_price": cp,
            })
    return trades


def compare_trades(lab_trades: list[dict], mt4_trades: list[dict], ts_tol_s: int = 0) -> dict:
    """Compara trades LAB vs MT4. Retorna report."""
    matched = 0
    mismatches = []
    for i, mt in enumerate(mt4_trades):
        found = False
        for lt in lab_trades:
            if abs(lt["entry_ts"] - mt["entry_ts"]) <= ts_tol_s and abs(lt["exit_ts"] - mt["exit_ts"]) <= ts_tol_s:
                matched += 1
                found = True
                break
        if not found and len(mismatches) < 5:
            mismatches.append({
                "mt4_idx": i + 1,
                "entry_ts": mt["entry_ts"],
                "exit_ts": mt["exit_ts"],
                "entry_price": mt["entry_price"],
            })
    return {
        "lab_count": len(lab_trades),
        "mt4_count": len(mt4_trades),
        "matched": matched,
        "pass": matched == len(mt4_trades) and len(lab_trades) == len(mt4_trades),
        "mismatches": mismatches,
    }


def _classify_cause(candle_parity: dict, trade_parity: dict, rsi_parity: Optional[dict]) -> str:
    """Classifica causa principal si falla."""
    cp = candle_parity or {}
    if cp.get("pass") is False:
        return "CANDLES_MISMATCH"
    if not trade_parity.get("pass", True):
        if rsi_parity is not None and not rsi_parity.get("pass", True):
            return "RSI_MISMATCH"
        return "EXECUTION_MISMATCH"
    return "PASS"


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def _main() -> int:
    parser = argparse.ArgumentParser(description="T8.39 — Paritat M1 candles + 17 trades")
    parser.add_argument("--base-url", default="http://localhost:8081", help="Base URL API (per candles)")
    parser.add_argument("--mt4-trades", type=Path, help="Path MT4 trades CSV (fallback: mt4_oracle)")
    parser.add_argument("--mt4-candles", type=Path, help="Path MT4 candles CSV (opcional)")
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_BASE, help="Directori artifacts")
    parser.add_argument("--no-api", action="store_true", help="No provar API, només BI5")
    args = parser.parse_args()

    artifacts_dir = args.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    base_url = None if args.no_api else args.base_url
    mt4_trades_path = args.mt4_trades
    if mt4_trades_path is None:
        mt4_trades_path = MT4_ORACLE_DIR / "trades_EURUSD_M1_UTCMinus05_20260201_20260202.csv"
        if not mt4_trades_path.exists():
            fallback = OUT_COMPARE_ROOT.parent.parent / "ostium" / "out_ind" / "rsi" / "output.rsi1m.csv"
            if fallback.exists():
                mt4_trades_path = fallback

    mt4_candles_path = args.mt4_candles
    if mt4_candles_path is None:
        mt4_candles_path = MT4_ORACLE_DIR / "candles_EURUSD_M1_UTCMinus05_20260201_20260202.csv"

    report: dict[str, Any] = {
        "task": "T8.39",
        "symbol": SYMBOL,
        "from": FROM_DATE,
        "to": "2026-02-02",
        "cause": "UNKNOWN",
        "needs_mt4_export": False,
    }

    # Step 2 — Export candles LAB
    print("STEP 2/6 — Export candles LAB...")
    lab_df = fetch_lab_candles(SYMBOL, FROM_DATE, TO_DATE, base_url)
    if len(lab_df) == 0:
        print("ERROR: 0 candles LAB. Verifica API o BI5.")
        report["cause"] = "DATA_MISSING"
        report["lab_candles_count"] = 0
        with open(artifacts_dir / "t839_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return 1

    lab_df.to_csv(artifacts_dir / "lab_candles_m1_utcminus05.csv", index=False)
    report["lab_candles_count"] = len(lab_df)
    report["lab_candles_checksum"] = _checksum_csv(lab_df)
    print(f"  lab_candles: {len(lab_df)} rows, checksum={report['lab_candles_checksum']}")

    # Step 3 — Candle parity (si tenim MT4 candles)
    print("STEP 3/6 — Candle parity...")
    mt4_candles = load_mt4_candles(mt4_candles_path)
    if mt4_candles is not None:
        candle_report = compare_candles(lab_df, mt4_candles)
        report["candle_parity"] = candle_report
        print(f"  CANDLE_PARITY: matched={candle_report['matched_rows']}/{candle_report['total_mt4']} "
              f"({candle_report['pct_matched']}%), pass={candle_report['pass']}")
        if candle_report["mismatches"]:
            pd.DataFrame(candle_report["mismatches"]).to_csv(
                artifacts_dir / "candle_mismatches.csv", index=False
            )
    else:
        report["candle_parity"] = {"status": "NEEDS_MT4_EXPORT", "pass": None}
        report["needs_mt4_export"] = True
        print("  CANDLE_PARITY: NEEDS_MT4_EXPORT (no mt4_candles.csv)")

    # Step 4 — RSI
    print("STEP 4/6 — RSI Wilder...")
    rsi = compute_rsi_wilder(lab_df["close"], RSI_PERIOD)
    lab_rsi_df = lab_df[["ts"]].copy()
    lab_rsi_df["close"] = lab_df["close"]
    lab_rsi_df["rsi"] = rsi
    lab_rsi_df.to_csv(artifacts_dir / "lab_rsi_m1.csv", index=False)

    # Step 5 — Simulació trades
    print("STEP 5/6 — Simulació trades LAB...")
    lab_trades = simulate_trades(lab_df)
    report["lab_trades_count"] = len(lab_trades)
    print(f"  LAB_TRADES: count={len(lab_trades)}")

    lab_trades_df = pd.DataFrame(lab_trades)
    if len(lab_trades_df) > 0:
        lab_trades_df.to_csv(artifacts_dir / "lab_trades.csv", index=False)

    # Step 6 — Trade parity
    print("STEP 6/6 — Trade parity...")
    mt4_trades = load_mt4_trades(mt4_trades_path)
    if mt4_trades:
        trade_report = compare_trades(lab_trades, mt4_trades, ts_tol_s=0)
        report["trade_parity"] = trade_report
        print(f"  TRADE_PARITY: lab={trade_report['lab_count']} mt4={trade_report['mt4_count']} "
              f"matched={trade_report['matched']}, pass={trade_report['pass']}")
        if trade_report["mismatches"]:
            pd.DataFrame(trade_report["mismatches"]).to_csv(
                artifacts_dir / "trade_mismatches.csv", index=False
            )
        report["cause"] = _classify_cause(
            report.get("candle_parity", {}),
            trade_report,
            None,
        )
    else:
        report["trade_parity"] = {"status": "NEEDS_MT4_EXPORT", "lab_count": len(lab_trades)}
        report["needs_mt4_export"] = True
        report["cause"] = "NEEDS_MT4_EXPORT"
        print("  TRADE_PARITY: NEEDS_MT4_EXPORT (no mt4_trades.csv)")

    with open(artifacts_dir / "t839_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport: {artifacts_dir / 't839_report.json'}")
    print(f"Cause: {report['cause']}")
    return 0 if report["cause"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(_main())
