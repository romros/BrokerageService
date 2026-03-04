"""
BS.T9.03 — Gate 5 anys M1 BID: comparar BS vs SQCLI (read-only, chunk mensual).

Comparació month-by-month de candles M1:
  - SQCLI: CSV export (format Date,Time,O,H,L,C o ts,open,high,low,close)
  - BS: GET /data/ohlcv/{symbol}?tf=1m&from_ts=&to_ts= (read-only)

Contracte: ts epoch UTC, OHLC tolerància 1e-5. Artifacts a lab/datalayer/artifacts/BS.T9.03/
"""

from __future__ import annotations

import csv
import json
import sys
from calendar import monthrange
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# Project root per imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OHLC_TOLERANCE = 1e-5
ARTIFACTS_SUBDIR = "lab/datalayer/artifacts/BS.T9.03"

# DST USA (igual que lab/paritat_SQ_dukascopy): SQ UTC-5 DST-aware
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
API_LIMIT = 5000
PIPS_EURUSD = 1e-4
REQUIRED_MONTHS_5Y = 60


def fetch_coverage(base_url: str, symbol: str, timeout: int = 30) -> dict:
    """
    GET /data/coverage/{symbol}?tf=1m. Retorna {summary, months}.
    months: {"YYYY-MM": {"status": "done"|..., "rows": N}, ...}
    """
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/data/coverage/{symbol}?tf=1m"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def find_contiguous_5y_range(months: dict) -> Optional[tuple[str, str]]:
    """
    Troba un bloc contigu de 60 mesos (5 anys) amb status "done" i rows > 0.
    Retorna (from_date, to_date) en format YYYY-MM-DD (to exclusiu).
    Tria el bloc més recent possible (últims 5 anys complets disponibles).
    """
    done_ok = []
    for key, val in (months or {}).items():
        if not isinstance(val, dict):
            continue
        if val.get("status") != "done":
            continue
        try:
            r = val.get("rows") or 0
            if int(r) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        try:
            y, m = int(key[:4]), int(key[5:7])
            if 1 <= m <= 12:
                done_ok.append((y, m))
        except (ValueError, IndexError):
            continue
    if not done_ok:
        return None
    done_ok.sort()
    # Trobar el bloc més recent de 60 mesos consecutius
    # (year*12+month) ha de ser consecutiu
    def to_linear(y: int, m: int) -> int:
        return y * 12 + m

    set_linear = {to_linear(y, m) for y, m in done_ok}
    # Cercar des del mes més alt cap enrere: hi ha 60 consecutius?
    for (y_end, m_end) in reversed(done_ok):
        start_linear = to_linear(y_end, m_end) - REQUIRED_MONTHS_5Y + 1
        if all(L in set_linear for L in range(start_linear, to_linear(y_end, m_end) + 1)):
            # Bloc vàlid: [start_linear .. end]; convertir start_linear → (y, m)
            y_start = start_linear // 12
            m_start = start_linear % 12
            if m_start == 0:
                m_start = 12
                y_start -= 1
            from_date = f"{y_start:04d}-{m_start:02d}-01"
            # to_date = primer dia del mes següent al darrer mes del bloc (exclusiu)
            if m_end == 12:
                to_date = f"{y_end + 1:04d}-01-01"
            else:
                to_date = f"{y_end:04d}-{m_end + 1:02d}-01"
            return (from_date, to_date)
    return None


def _month_range(year: int, month: int) -> tuple[int, int]:
    """Retorna (from_ts, to_ts) UTC per un mes (inclusiu, exclusiu)."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    from_ts = int(start.timestamp())
    to_ts = int(end.timestamp()) + 1
    return from_ts, to_ts


def load_sq_csv(path: Path) -> Optional[list[dict]]:
    """
    Carrega CSV SQ (M1). Auto-detecta format.
    Retorna llista de {"ts": int, "open": float, "high": float, "low": float, "close": float}.
    ts = epoch UTC start-of-minute.
    """
    if not path.exists():
        return None
    try:
        import pandas as pd
    except ImportError:
        return _load_sq_csv_stdlib(path)
    df = pd.read_csv(path)
    # Format A: ts directe
    if "ts" in df.columns and all(c in df.columns for c in ["open", "high", "low", "close"]):
        df["ts"] = df["ts"].astype(int)
        return df[["ts", "open", "high", "low", "close"]].to_dict("records")
    # Format B: dt_utcminus05 / Open time
    date_col = None
    for col in ["dt_utcminus05", "Open time", "date_utcminus05", "date"]:
        if col in df.columns:
            date_col = col
            break
    if date_col and all(c in df.columns for c in ["open", "high", "low", "close"]):

        def _ts_from_dt(s: str) -> int:
            s = str(s).strip().strip('"')
            parts = s.split(maxsplit=1)
            date_s, time_s = parts[0], parts[1] if len(parts) > 1 else "00:00"
            year = int(date_s[:4])
            return sq_to_utc(date_s, time_s, year)

        df["ts"] = df[date_col].apply(_ts_from_dt)
        return df[["ts", "open", "high", "low", "close"]].to_dict("records")
    # Format C: SQ export sense header (Date,Time,O,H,L,C). DST-aware com lab.
    try:
        df_raw = pd.read_csv(path, header=None)
        if len(df_raw.columns) >= 6:
            first_val = str(df_raw.iloc[0, 0])
            if len(first_val) >= 10 and first_val[4] == "." and first_val[7] == ".":
                names = ["date", "time", "open", "high", "low", "close", "volume"][: len(df_raw.columns)]
                df_raw.columns = names[: len(df_raw.columns)]

                def _ts_sq_row(r) -> int:
                    date_s, time_s = str(r["date"]).strip(), str(r["time"]).strip()
                    year = int(date_s[:4])
                    return sq_to_utc(date_s, time_s, year)

                df_raw["ts"] = df_raw.apply(_ts_sq_row, axis=1)
                return df_raw[["ts", "open", "high", "low", "close"]].to_dict("records")
    except (ValueError, KeyError):
        pass
    return None


def _load_sq_csv_stdlib(path: Path) -> Optional[list[dict]]:
    """Fallback sense pandas: ts,open,... o Format C date,time,o,h,l,c (DST-aware)."""
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        first = next(reader, None)
        if not first:
            return None
        if first[0].strip().lower() == "ts" and len(first) >= 5:
            for r in reader:
                if len(r) >= 5:
                    try:
                        rows.append({"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])})
                    except (ValueError, IndexError):
                        continue
            return rows if rows else None
        if len(first) >= 6 and "." in str(first[0]) and ":" in str(first[1]):
            for r in [first] + list(reader):
                if len(r) < 6:
                    continue
                try:
                    date_s, time_s = str(r[0]).strip(), str(r[1]).strip()
                    year = int(date_s[:4])
                    ts = sq_to_utc(date_s, time_s, year)
                    rows.append({"ts": ts, "open": float(r[2]), "high": float(r[3]), "low": float(r[4]), "close": float(r[5])})
                except (ValueError, IndexError):
                    continue
            return rows if rows else None
    return None


def fetch_bs_candles_month(
    base_url: str,
    symbol: str,
    from_ts: int,
    to_ts: int,
    timeout: int = 120,
) -> list[dict]:
    """
    Obté candles BS per un rang [from_ts, to_ts) via API.
    Pagina amb next_ts si cal. Retorna llista de {"ts", "open", "high", "low", "close"}.
    """
    import urllib.error
    import urllib.request

    base_url = base_url.rstrip("/")
    all_candles: list[dict] = []
    next_ts: Optional[int] = None
    while True:
        url = f"{base_url}/data/ohlcv/{symbol}?tf=1m&from_ts={from_ts}&to_ts={to_ts}&limit={API_LIMIT}"
        if next_ts is not None:
            url += f"&next_ts={next_ts}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            raise RuntimeError(f"BS API error: {e}") from e
        candles = data.get("candles", [])
        for row in candles:
            if len(row) >= 5:
                all_candles.append({
                    "ts": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                })
        next_ts = data.get("next_ts")
        if not next_ts or not candles:
            break
    return all_candles


def compare_month(
    sq_rows: list[dict],
    bs_rows: list[dict],
    tol: float = OHLC_TOLERANCE,
    max_mismatches_sample: int = 100,
) -> dict[str, Any]:
    """
    Compara candles SQ vs BS per un mes. join per ts.
    Retorna month_summary amb matched_rows, missing_in_bs, extra_in_bs, mismatches_on_common_ts, max_abs_delta_pips.
    """
    sq_by_ts = {r["ts"]: r for r in sq_rows}
    bs_by_ts = {r["ts"]: r for r in bs_rows}
    common_ts = set(sq_by_ts) & set(bs_by_ts)
    missing_in_bs = sorted(set(sq_by_ts) - set(bs_by_ts))
    extra_in_bs = sorted(set(bs_by_ts) - set(sq_by_ts))

    mismatches = []
    max_abs_delta_pips = 0.0
    for ts in common_ts:
        sq_r = sq_by_ts[ts]
        bs_r = bs_by_ts[ts]
        for col in ("open", "high", "low", "close"):
            a, b = float(sq_r[col]), float(bs_r[col])
            delta = abs(a - b)
            if delta > tol:
                pips = delta / PIPS_EURUSD
                if pips > max_abs_delta_pips:
                    max_abs_delta_pips = pips
                if len(mismatches) < max_mismatches_sample:
                    mismatches.append({
                        "ts": ts,
                        "col": col,
                        "sq": a,
                        "bs": b,
                        "delta_pips": round(pips, 4),
                    })

    return {
        "sq_rows": len(sq_rows),
        "bs_rows": len(bs_rows),
        "matched_rows": len(common_ts),
        "missing_in_bs": len(missing_in_bs),
        "extra_in_bs": len(extra_in_bs),
        "mismatches_on_common_ts": len(mismatches),
        "max_abs_delta_pips": round(max_abs_delta_pips, 4),
        "mismatches_sample": mismatches[:20],
        "pass_preu": len(mismatches) == 0,
    }


def run_gate(
    sq_csv: Path,
    base_url: str,
    symbol: str = "EURUSD",
    from_date: str = "2020-01-01",
    to_date: str = "2025-01-01",
    out_dir: Optional[Path] = None,
    dry_run: bool = False,
    months_limit: Optional[int] = None,
    auto_range: bool = True,
) -> dict[str, Any]:
    """
    Punt únic del gate. Compara BS vs SQCLI per cada mes en [from_date, to_date).
    Read-only: només GET a BS i lectura de CSV.

    Si auto_range=True (per defecte): primer pas és obtenir la cobertura BS (GET /data/coverage)
    i triar un bloc de 5 anys (60 mesos) amb tots els mesos "done" i rows>0; s'usa aquest rang
    en lloc de from_date/to_date. Si no hi ha cap bloc vàlid, es retorna error.
    """
    if out_dir is None:
        out_dir = PROJECT_ROOT / ARTIFACTS_SUBDIR
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Primer pas: rang 5y amb cobertura BS completa (si auto_range)
    if auto_range:
        try:
            cov = fetch_coverage(base_url, symbol)
            months = cov.get("months") or {}
            discovered = find_contiguous_5y_range(months)
            if not discovered:
                summary = cov.get("summary") or {}
                return {
                    "gate": "BS.T9.03",
                    "status": "FAIL",
                    "error": (
                        "No s'ha trobat cap bloc de 60 mesos consecutius 'done' (rows>0) a la cobertura BS. "
                        f"summary={summary}. Executa sync EURUSD M1 o indica --from/--to manualment (sense --auto-range)."
                    ),
                    "months_processed": 0,
                }
            from_date, to_date = discovered
            print(f"STEP 0: Rang 5y descobert (cobertura BS): {from_date} → {to_date} (60 mesos)")
        except Exception as e:
            return {
                "gate": "BS.T9.03",
                "status": "FAIL",
                "error": f"No s'ha pogut obtenir la cobertura BS: {e}. Assegura't que el servei està en marxa (base_url) o indica --from/--to manualment (sense --auto-range).",
                "months_processed": 0,
            }

    if not sq_csv.exists():
        return {
            "gate": "BS.T9.03",
            "status": "FAIL",
            "error": f"SQ CSV no trobat: {sq_csv}",
            "months_processed": 0,
        }

    all_sq = load_sq_csv(sq_csv)
    if not all_sq:
        return {
            "gate": "BS.T9.03",
            "status": "FAIL",
            "error": f"No s'han pogut parsejar candles des de {sq_csv}",
            "months_processed": 0,
        }

    # Rang de mesos
    from_d = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_d = datetime.strptime(to_date, "%Y-%m-%d").date()
    months: list[tuple[int, int]] = []
    y, m = from_d.year, from_d.month
    while (y, m) <= (to_d.year, to_d.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    if months_limit is not None:
        months = months[: months_limit]

    if dry_run:
        return {
            "gate": "BS.T9.03",
            "status": "DRY_RUN",
            "sq_csv": str(sq_csv),
            "base_url": base_url,
            "symbol": symbol,
            "from_date": from_date,
            "to_date": to_date,
            "months": [f"{y}-{m:02d}" for y, m in months],
            "months_count": len(months),
        }

    sq_by_ts = {r["ts"]: r for r in all_sq}
    month_summaries: list[dict] = []
    total_mismatches = 0
    total_missing = 0
    total_extra = 0
    any_fail = False

    for i, (year, month) in enumerate(months):
        from_ts, to_ts = _month_range(year, month)
        month_key = f"{year}-{month:02d}"
        # Filtra SQ per aquest mes
        sq_month = [r for r in all_sq if from_ts <= r["ts"] < to_ts]
        print(f"MONTH {month_key}: sq_rows={len(sq_month)}", end="", flush=True)
        try:
            bs_month = fetch_bs_candles_month(base_url, symbol, from_ts, to_ts)
        except Exception as e:
            print(f" bs_error={e}")
            month_summaries.append({
                "month": month_key,
                "sq_rows": len(sq_month),
                "bs_rows": 0,
                "error": str(e),
                "pass_preu": False,
            })
            any_fail = True
            month_dir = out_dir / f"month={month_key}"
            month_dir.mkdir(parents=True, exist_ok=True)
            with open(month_dir / "month_summary.json", "w", encoding="utf-8") as f:
                json.dump(month_summaries[-1], f, indent=2)
            continue
        print(f" bs_rows={len(bs_month)}", end="", flush=True)
        report = compare_month(sq_month, bs_month)
        report["month"] = month_key
        total_mismatches += report["mismatches_on_common_ts"]
        total_missing += report["missing_in_bs"]
        total_extra += report["extra_in_bs"]
        if not report["pass_preu"]:
            any_fail = True
        print(f" join={report['matched_rows']} mismatches={report['mismatches_on_common_ts']} missing_bs={report['missing_in_bs']} extra_bs={report['extra_in_bs']}")
        month_summaries.append(report)
        month_dir = out_dir / f"month={month_key}"
        month_dir.mkdir(parents=True, exist_ok=True)
        with open(month_dir / "month_summary.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        if report.get("mismatches_sample"):
            with open(month_dir / "mismatches_top.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ts", "col", "sq", "bs", "delta_pips"])
                w.writeheader()
                w.writerows(report["mismatches_sample"])

    gate_pass = not any_fail and total_mismatches == 0
    gate_summary = {
        "gate": "BS.T9.03",
        "status": "PASS" if gate_pass else "FAIL",
        "symbol": symbol,
        "from_date": from_date,
        "to_date": to_date,
        "months_processed": len(months),
        "total_mismatches_on_common_ts": total_mismatches,
        "total_missing_in_bs": total_missing,
        "total_extra_in_bs": total_extra,
        "months": month_summaries,
    }
    with open(out_dir / "gate_summary.json", "w", encoding="utf-8") as f:
        json.dump(gate_summary, f, indent=2)

    # gate_summary.csv (fila per mes)
    csv_path = out_dir / "gate_summary.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["month", "sq_rows", "bs_rows", "matched_rows", "missing_in_bs", "extra_in_bs", "mismatches_on_common_ts", "max_abs_delta_pips", "pass_preu"],
        )
        w.writeheader()
        for m in month_summaries:
            w.writerow({
                "month": m.get("month", ""),
                "sq_rows": m.get("sq_rows", 0),
                "bs_rows": m.get("bs_rows", 0),
                "matched_rows": m.get("matched_rows", 0),
                "missing_in_bs": m.get("missing_in_bs", 0),
                "extra_in_bs": m.get("extra_in_bs", 0),
                "mismatches_on_common_ts": m.get("mismatches_on_common_ts", 0),
                "max_abs_delta_pips": m.get("max_abs_delta_pips", 0),
                "pass_preu": m.get("pass_preu", False),
            })
    print(f"WRITE: gate_summary.json gate_summary.csv -> {out_dir}")
    return gate_summary


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="BS.T9.03 Gate 5y M1 BID: BS vs SQCLI parity (read-only)")
    parser.add_argument("--sq-csv", type=Path, required=True, help="Path al CSV export SQ (M1)")
    parser.add_argument("--base-url", default="http://localhost:8081", help="Base URL BS (gateway)")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_date", default="2020-01-01", help="Data inici (YYYY-MM-DD); ignorat si --auto-range)")
    parser.add_argument("--to", dest="to_date", default="2025-01-01", help="Data fi (YYYY-MM-DD); ignorat si --auto-range)")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Només llista mesos i paths")
    parser.add_argument("--months", type=int, default=None, help="Limit nombre de mesos (ex: 1 per smoke)")
    parser.add_argument("--no-auto-range", action="store_true", help="Usar --from/--to; no descobert des de cobertura BS (per defecte: auto-range des de BS)")
    args = parser.parse_args()
    auto_range = not args.no_auto_range
    result = run_gate(
        sq_csv=args.sq_csv,
        base_url=args.base_url,
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        out_dir=args.out_dir,
        dry_run=args.dry_run,
        months_limit=args.months,
        auto_range=auto_range,
    )
    status = result.get("status", "FAIL")
    if status == "FAIL" and result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1
    if status == "PASS":
        return 0
    if status == "DRY_RUN":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
