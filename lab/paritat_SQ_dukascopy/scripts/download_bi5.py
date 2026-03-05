"""
lab/paritat_SQ_dukascopy/scripts/download_bi5.py

Descarrega dades EURUSD M1 bi5 de Dukascopy per any sencer i desa a data/.

Ús:
    python3 lab/paritat_SQ_dukascopy/scripts/download_bi5.py --year 2024
    python3 lab/paritat_SQ_dukascopy/scripts/download_bi5.py --year 2025
    python3 lab/paritat_SQ_dukascopy/scripts/download_bi5.py --year 2024 --year 2025

Format sortida: data/EURUSD_M1_{YEAR}.csv
  ts,open,high,low,close
  (ts = epoch UTC start-of-minute, OHLC float 5 decimals)
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from application.data.dukascopy_bi5 import fetch_m1_range  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SYMBOL = "EURUSD"
RATE_LIMIT_S = 0.1


def download_year(year: int) -> Path:
    from_date = f"{year}-01-01"
    to_date = f"{year + 1}-01-01"
    out_csv = DATA_DIR / f"{SYMBOL}_M1_{year}.csv"

    if out_csv.exists():
        print(f"[SKIP] {out_csv.name} ja existeix ({out_csv.stat().st_size // 1024} KB)")
        return out_csv

    print(f"[DOWNLOAD] {SYMBOL} M1 {from_date} → {to_date} ...")
    candles = fetch_m1_range(SYMBOL, from_date, to_date, rate_limit_s=RATE_LIMIT_S)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close"])
        for c in candles:
            w.writerow([c["ts_utc"], c["open"], c["high"], c["low"], c["close"]])

    first_dt = datetime.fromtimestamp(candles[0]["ts_utc"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if candles else "—"
    last_dt = datetime.fromtimestamp(candles[-1]["ts_utc"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if candles else "—"
    print(f"[OK] {out_csv.name}: {len(candles)} candles  ({first_dt} → {last_dt} UTC)")
    return out_csv


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Descarrega EURUSD M1 bi5 per any(s) sencer(s)")
    parser.add_argument("--year", type=int, action="append", required=True,
                        help="Any a descarregar (repetible: --year 2024 --year 2025)")
    args = parser.parse_args()

    for year in sorted(set(args.year)):
        download_year(year)

    return 0


if __name__ == "__main__":
    sys.exit(main())
