"""
Baixada directa BI5 (5 anys) + comparació amb export SQCLI mateix rang.

1. Descarrega M1 BID des de Dukascopy BI5 (from_date → to_date) i desa a out_dir/bi5_5y.csv.
2. Carrega export SQCLI (--sq-csv) i compara barra a barra (ts, OHLC).
3. Escriu summary a out_dir/summary.json.

Ús:
  python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --sq-csv /path/to/EURUSD_M1_dukas_M1_UTCMinus05.csv
  python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --compare-only --sq-csv /path/to/sq.csv  # sense tornar a baixar
"""

from __future__ import annotations

import csv
import json
import sys
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OHLC_TOLERANCE = 1e-5
PIPS_EURUSD = 1e-4
DEFAULT_FROM = "2019-01-01"
DEFAULT_TO = "2024-01-01"

# DST USA (igual que lab/paritat_SQ_dukascopy): SQ en UTC-5, DST-aware
DST_RANGES = {
    2024: (datetime(2024, 3, 10, 2, 0), datetime(2024, 11, 3, 2, 0)),
    2025: (datetime(2025, 3, 9, 2, 0), datetime(2025, 11, 2, 2, 0)),
}


def _dst_range(year: int) -> tuple[datetime, datetime]:
    if year in DST_RANGES:
        return DST_RANGES[year]
    import calendar
    sundays = [d for d in range(1, 32) if calendar.weekday(year, 3, d) == 6]
    dst_start = datetime(year, 3, sundays[1], 2, 0) if len(sundays) >= 2 else datetime(year, 3, 10, 2, 0)
    sundays_n = [d for d in range(1, 31) if calendar.weekday(year, 11, d) == 6]
    dst_end = datetime(year, 11, sundays_n[0], 2, 0) if sundays_n else datetime(year, 11, 3, 2, 0)
    return (dst_start, dst_end)


def sq_to_utc(date_str: str, time_str: str, year: int) -> int:
    """Converteix timestamp SQ (UTCMinus05, DST-aware) a epoch UTC. Idèntic a lab validate_parity."""
    s = f"{date_str.strip()} {time_str.strip()}"
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"No parse: {s}")
    dst_start, dst_end = _dst_range(year)
    offset = timedelta(hours=4) if dst_start <= dt < dst_end else timedelta(hours=5)
    return int((dt + offset).timestamp())


def _month_ts_range(year: int, month: int) -> tuple[int, int]:
    """(from_ts, to_ts) UTC per un mes (inclusiu, exclusiu)."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp()) + 1


def download_bi5_5y(
    symbol: str,
    from_date: str,
    to_date: str,
    out_csv: Path,
    rate_limit_s: float = 0.1,
) -> int:
    """Descarrega BI5 per [from_date, to_date) i desa CSV. Retorna nombre de candles."""
    from application.data.dukascopy_bi5 import fetch_m1_range

    candles = fetch_m1_range(symbol, from_date, to_date, rate_limit_s=rate_limit_s)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close"])
        for c in candles:
            w.writerow([c["ts_utc"], c["open"], c["high"], c["low"], c["close"]])
    return len(candles)


def load_bi5_csv(path: Path) -> list[dict]:
    """Carrega CSV generat per download_bi5_5y: ts, open, high, low, close."""
    out = []
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append({
                "ts": int(row["ts"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
    return out


def load_sq_csv(path: Path) -> Optional[list[dict]]:
    """Carrega CSV SQCLI. DST-aware (UTC-5 EDT/EST) com lab/paritat_SQ_dukascopy. ts = epoch UTC."""
    if not path.exists():
        return None
    try:
        import pandas as pd
    except ImportError:
        return _load_sq_csv_stdlib(path)
    df = pd.read_csv(path)
    if "ts" in df.columns and all(c in df.columns for c in ["open", "high", "low", "close"]):
        df["ts"] = df["ts"].astype(int)
        return df[["ts", "open", "high", "low", "close"]].to_dict("records")
    for date_col in ["dt_utcminus05", "Open time", "date_utcminus05", "date"]:
        if date_col not in df.columns or not all(c in df.columns for c in ["open", "high", "low", "close"]):
            continue
        # Una sola columna dt: separar date + time, DST-aware
        def _ts_from_dt(s: str) -> int:
            s = str(s).strip().strip('"')
            parts = s.split(maxsplit=1)
            date_s = parts[0]
            time_s = parts[1] if len(parts) > 1 else "00:00"
            year = int(date_s[:4])
            return sq_to_utc(date_s, time_s, year)
        df["ts"] = df[date_col].apply(_ts_from_dt)
        return df[["ts", "open", "high", "low", "close"]].to_dict("records")
    df_raw = pd.read_csv(path, header=None, dtype={0: str, 1: str})
    if len(df_raw.columns) >= 6:
        first_val = str(df_raw.iloc[0, 0]).strip()
        if len(first_val) >= 10 and first_val[4] == "." and first_val[7] == ".":
            names = ["date", "time", "open", "high", "low", "close", "volume"][: len(df_raw.columns)]
            df_raw.columns = names[: len(df_raw.columns)]

            def _ts_sq_row(r) -> int:
                date_s, time_s = str(r["date"]).strip(), str(r["time"]).strip()
                year = int(date_s[:4])
                return sq_to_utc(date_s, time_s, year)

            df_raw["ts"] = df_raw.apply(_ts_sq_row, axis=1)
            return df_raw[["ts", "open", "high", "low", "close"]].to_dict("records")
    return None


def _load_sq_csv_stdlib(path: Path) -> Optional[list[dict]]:
    """Format C: date,time,o,h,l,c. DST-aware com lab."""
    out = []
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    if not first.strip():
        return None
    parts = first.split(",")
    if len(parts) >= 6 and parts[0].strip().replace(".", "").replace("-", "").isdigit() and ":" in (parts[1].strip() if len(parts) > 1 else ""):
        with open(path, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 6:
                    try:
                        date_s, time_s = str(row[0]).strip(), str(row[1]).strip()
                        year = int(date_s[:4])
                        ts = sq_to_utc(date_s, time_s, year)
                        out.append({"ts": ts, "open": float(row[2]), "high": float(row[3]), "low": float(row[4]), "close": float(row[5])})
                    except (ValueError, IndexError):
                        continue
        return out if out else None
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "ts" not in reader.fieldnames:
            return None
        return [
            {"ts": int(r["ts"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])}
            for r in reader
        ]


def compare_month(
    bi5_rows: list[dict],
    sq_rows: list[dict],
    tol: float = OHLC_TOLERANCE,
    max_sample: int = 50,
) -> dict[str, Any]:
    """Compara dos conjunts per ts. Retorna matched, missing_in_bi5, extra_in_bi5, mismatches."""
    bi5_by = {r["ts"]: r for r in bi5_rows}
    sq_by = {r["ts"]: r for r in sq_rows}
    common = set(bi5_by) & set(sq_by)
    missing_in_bi5 = len(set(sq_by) - set(bi5_by))
    extra_in_bi5 = len(set(bi5_by) - set(sq_by))
    mismatches = []
    mismatch_count = 0
    max_pips = 0.0
    for ts in common:
        a, b = bi5_by[ts], sq_by[ts]
        for col in ("open", "high", "low", "close"):
            da = abs(float(a[col]) - float(b[col]))
            if da > tol:
                mismatch_count += 1
                pips = da / PIPS_EURUSD
                if pips > max_pips:
                    max_pips = pips
                if len(mismatches) < max_sample:
                    mismatches.append({"ts": ts, "col": col, "bi5": a[col], "sq": b[col], "delta_pips": round(pips, 4)})
    return {
        "bi5_rows": len(bi5_rows),
        "sq_rows": len(sq_rows),
        "matched_rows": len(common),
        "missing_in_bi5": missing_in_bi5,
        "extra_in_bi5": extra_in_bi5,
        "mismatches_on_common_ts": mismatch_count,
        "mismatches_sample": mismatches[:20],
        "max_abs_delta_pips": round(max_pips, 4),
        "pass_preu": mismatch_count == 0,
    }


def run(
    sq_csv: Path,
    out_dir: Path,
    symbol: str = "EURUSD",
    from_date: str = DEFAULT_FROM,
    to_date: str = DEFAULT_TO,
    download: bool = True,
    rate_limit_s: float = 0.1,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bi5_csv = out_dir / "bi5_5y.csv"

    if download or not bi5_csv.exists():
        print(f"[BI5] Descarregant {symbol} {from_date} → {to_date}...")
        n = download_bi5_5y(symbol, from_date, to_date, bi5_csv, rate_limit_s=rate_limit_s)
        print(f"[BI5] Desats {n} candles a {bi5_csv}")
    else:
        print(f"[BI5] Reutilitzant {bi5_csv}")

    bi5_all = load_bi5_csv(bi5_csv)
    sq_all = load_sq_csv(sq_csv)
    if not sq_all:
        return {"status": "FAIL", "error": f"SQCLI CSV no carregat o buit: {sq_csv}"}

    from_y, from_m = int(from_date[:4]), int(from_date[5:7])
    to_y, to_m = int(to_date[:4]), int(to_date[5:7])
    months = []
    y, m = from_y, from_m
    while (y, m) < (to_y, to_m):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    total_mismatches = 0
    total_missing = 0
    total_extra = 0
    any_fail = False
    month_reports = []

    for y, m in months:
        from_ts, to_ts = _month_ts_range(y, m)
        month_key = f"{y}-{m:02d}"
        bi5_month = [r for r in bi5_all if from_ts <= r["ts"] < to_ts]
        sq_month = [r for r in sq_all if from_ts <= r["ts"] < to_ts]
        report = compare_month(bi5_month, sq_month)
        report["month"] = month_key
        month_reports.append(report)
        total_mismatches += report["mismatches_on_common_ts"]
        total_missing += report["missing_in_bi5"]
        total_extra += report["extra_in_bi5"]
        if not report["pass_preu"]:
            any_fail = True
        print(f"  {month_key}: bi5={report['bi5_rows']} sq={report['sq_rows']} match={report['matched_rows']} "
              f"miss_bi5={report['missing_in_bi5']} extra_bi5={report['extra_in_bi5']} mismatches={report['mismatches_on_common_ts']}")

    summary = {
        "status": "PASS" if not any_fail and total_mismatches == 0 else "FAIL",
        "from_date": from_date,
        "to_date": to_date,
        "symbol": symbol,
        "bi5_csv": str(bi5_csv),
        "sq_csv": str(sq_csv),
        "months_processed": len(months),
        "total_mismatches_on_common_ts": total_mismatches,
        "total_missing_in_bi5": total_missing,
        "total_extra_in_bi5": total_extra,
        "months": month_reports,
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[Resultat] {summary['status']} — mismatches={total_mismatches} missing_in_bi5={total_missing} extra_in_bi5={total_extra}")
    return summary


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="BI5 5y directe + comparació SQCLI")
    parser.add_argument("--sq-csv", type=Path, required=True, help="Path export SQCLI (EURUSD M1 UTCMinus05)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Directori sortida (default: lab/bi5_vs_sqcli/artifacts)")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_date", default=DEFAULT_FROM, help="Data inici YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default=DEFAULT_TO, help="Data fi YYYY-MM-DD (exclusiu)")
    parser.add_argument("--compare-only", action="store_true", help="No baixar BI5, usar bi5_5y.csv existent a out-dir")
    parser.add_argument("--rate-limit", type=float, default=0.1, help="Segons entre requests BI5")
    args = parser.parse_args()
    out_dir = args.out_dir or (PROJECT_ROOT / "lab" / "bi5_vs_sqcli" / "artifacts")
    summary = run(
        sq_csv=args.sq_csv,
        out_dir=out_dir,
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        download=not args.compare_only,
        rate_limit_s=args.rate_limit,
    )
    return 0 if summary.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
