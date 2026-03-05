"""
BS.T9.15 — Gate SQ↔BS M1 parity (candles 1:1 a nivell d'API).

Compara candles M1 SQ (CSV export) vs BS (GET /data/ohlcv) per certificar paritat 1:1.
SQ es parseja DST-aware (UTC-5 EDT/EST) igual que lab/paritat_SQ_dukascopy/validate_parity.py.

PASS: missing_in_bs=0, mismatches=0, extra_in_bs=0 (policy exact).
"""

from __future__ import annotations

import csv
import json
import sys
from calendar import monthrange
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OHLC_TOLERANCE = 1e-5
API_LIMIT = 5000

# DST USA (igual que lab/paritat_SQ_dukascopy): segon diumenge març, primer diumenge novembre
# SQ exporta en UTC-5; dins DST (EDT) offset +4h, fora (EST) +5h
DST_RANGES = {
    2024: (datetime(2024, 3, 10, 2, 0), datetime(2024, 11, 3, 2, 0)),
    2025: (datetime(2025, 3, 9, 2, 0), datetime(2025, 11, 2, 2, 0)),
}


def _dst_range(year: int) -> tuple[datetime, datetime]:
    """(inici_dst, fi_dst) per any. In-place sense tz."""
    if year in DST_RANGES:
        return DST_RANGES[year]
    import calendar
    # Segon diumenge de març
    mar = datetime(year, 3, 1)
    sundays = [d for d in range(1, 32) if calendar.weekday(year, 3, d) == 6]
    dst_start = datetime(year, 3, sundays[1], 2, 0) if len(sundays) >= 2 else datetime(year, 3, 10, 2, 0)
    # Primer diumenge de novembre
    nov = datetime(year, 11, 1)
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
PIPS_EURUSD = 1e-4
TOP_N = 100
FIRST_MISMATCH_WINDOW_MINUTES = 10


def _month_range(year: int, month: int) -> tuple[int, int]:
    """Retorna (from_ts, to_ts) UTC per un mes (inclusiu inici, exclusiu fi)."""
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    from_ts = int(start.timestamp())
    to_ts = int(end.timestamp()) + 1
    return from_ts, to_ts


def load_sq_csv(path: Path) -> Optional[list[dict]]:
    """
    Carrega CSV SQ M1. Auto-detecta format.
    Retorna [{"ts": int, "open": float, "high": float, "low": float, "close": float}].
    ts = epoch UTC. SQ en UTC-05 es converteix a UTC.
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

    # Format B: Date,Time,Open,High,Low,Close (amb capçalera). DST-aware com lab validate_parity.
    for date_col in ["Date", "date", "Open time"]:
        if date_col not in df.columns:
            continue
        time_col = "Time" if "Time" in df.columns else "time"
        if time_col not in df.columns:
            continue
        o_col = next((c for c in ["Open", "open"] if c in df.columns), None)
        if not o_col or not all(c in df.columns for c in ["High", "Low", "Close"]) and not all(c in df.columns for c in ["high", "low", "close"]):
            continue
        h_col = "High" if "High" in df.columns else "high"
        l_col = "Low" if "Low" in df.columns else "low"
        c_col = "Close" if "Close" in df.columns else "close"

        def _ts_from_row(r) -> int:
            date_s, time_s = str(r[date_col]).strip().strip('"'), str(r[time_col]).strip().strip('"')
            year = int(date_s[:4])
            return sq_to_utc(date_s, time_s, year)

        df["ts"] = df.apply(_ts_from_row, axis=1)
        df["open"] = df[o_col].astype(float)
        df["high"] = df[h_col].astype(float)
        df["low"] = df[l_col].astype(float)
        df["close"] = df[c_col].astype(float)
        return df[["ts", "open", "high", "low", "close"]].to_dict("records")

    # Format C: sense header (Date,Time,O,H,L,C). DST-aware com lab validate_parity.
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
                for col in ["open", "high", "low", "close"]:
                    df_raw[col] = df_raw[col].astype(float)
                return df_raw[["ts", "open", "high", "low", "close"]].to_dict("records")
    except (ValueError, KeyError):
        pass
    return None


def _load_sq_csv_stdlib(path: Path) -> Optional[list[dict]]:
    """Fallback sense pandas: format ts,open,high,low,close o Date,Time,O,H,L,C. DST-aware com lab."""
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        first = next(reader, None)
        if not first:
            return None
        # Format A: header ts,open,high,low,close
        if first[0].strip().lower() == "ts" and len(first) >= 5:
            for r in reader:
                if len(r) >= 5:
                    try:
                        rows.append({
                            "ts": int(r[0]),
                            "open": float(r[1]),
                            "high": float(r[2]),
                            "low": float(r[3]),
                            "close": float(r[4]),
                        })
                    except (ValueError, IndexError):
                        continue
            return rows if rows else None
        # Format C: sense header, Date,Time,O,H,L,C. DST-aware: any per fila
        if len(first) >= 6 and "." in str(first[0]) and ":" in str(first[1]):
            rows = []
            for r in [first] + list(reader):
                if len(r) < 6:
                    continue
                try:
                    date_s, time_s = str(r[0]).strip(), str(r[1]).strip()
                    year = int(date_s[:4])
                    ts = sq_to_utc(date_s, time_s, year)
                    rows.append({
                        "ts": ts,
                        "open": float(r[2]),
                        "high": float(r[3]),
                        "low": float(r[4]),
                        "close": float(r[5]),
                    })
                except (ValueError, IndexError):
                    continue
            return rows if rows else None
    return None


def fetch_bs_candles_month(
    base_url: str,
    symbol: str,
    from_ts: int,
    to_ts: int,
    source: str = "dukascopy",
    timeout: int = 120,
) -> list[dict]:
    """Obté candles BS per [from_ts, to_ts) via API. Pagina amb next_ts."""
    import urllib.error
    import urllib.request

    base_url = base_url.rstrip("/")
    all_candles: list[dict] = []
    next_ts: Optional[int] = None
    while True:
        url = f"{base_url}/data/ohlcv/{symbol}?tf=1m&from_ts={from_ts}&to_ts={to_ts}&limit={API_LIMIT}&source={source}"
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
    max_sample: int = TOP_N,
) -> dict[str, Any]:
    """
    Compara SQ vs BS per mes. Join per ts.
    Retorna month_summary amb missing_in_bs, extra_in_bs, mismatches, first_mismatch_ts.
    """
    sq_by_ts = {r["ts"]: r for r in sq_rows}
    bs_by_ts = {r["ts"]: r for r in bs_rows}
    common_ts = set(sq_by_ts) & set(bs_by_ts)
    missing_in_bs = sorted(set(sq_by_ts) - set(bs_by_ts))
    extra_in_bs = sorted(set(bs_by_ts) - set(sq_by_ts))

    mismatches = []
    mismatches_count = 0
    first_mismatch_ts: Optional[int] = None
    max_abs_delta_pips = 0.0
    for ts in sorted(common_ts):
        sq_r = sq_by_ts[ts]
        bs_r = bs_by_ts[ts]
        for col in ("open", "high", "low", "close"):
            a, b = float(sq_r[col]), float(bs_r[col])
            delta = abs(a - b)
            if delta > tol:
                mismatches_count += 1
                pips = delta / PIPS_EURUSD
                if pips > max_abs_delta_pips:
                    max_abs_delta_pips = pips
                if first_mismatch_ts is None:
                    first_mismatch_ts = ts
                if len(mismatches) < max_sample:
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
        "mismatches_on_common_ts": mismatches_count,
        "max_abs_delta_pips": round(max_abs_delta_pips, 4),
        "first_mismatch_ts": first_mismatch_ts,
        "mismatches_sample": mismatches[:max_sample],
        "missing_in_bs_list": missing_in_bs[:max_sample],
        "missing_in_bs_full": missing_in_bs,  # T9.16: llista completa per audit
        "extra_in_bs_list": extra_in_bs[:max_sample],
        "extra_in_bs_full": extra_in_bs,  # per audit: ts + market_open
        "pass_preu": len(mismatches) == 0,
        "pass_missing": len(missing_in_bs) == 0,
        "pass_extra": len(extra_in_bs) == 0,
    }


POLICY_INTERSECTION = "intersection"
POLICY_EXACT = "exact"


def _mtime_iso(path: Path) -> Optional[str]:
    """Retorna mtime del path en ISO format."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def run_gate(
    sq_input: Path,
    base_url: str,
    symbol: str = "EURUSD",
    from_date: str = "2003-01-01",
    to_date: str = "2026-03-04",
    source: str = "dukascopy",
    out_dir: Optional[Path] = None,
    resume: bool = False,
    months_limit: Optional[int] = None,
    tol: float = OHLC_TOLERANCE,
    policy: str = POLICY_EXACT,
    export_method: str = "unknown",
) -> dict[str, Any]:
    """
    Gate SQ↔BS M1 parity. Chunk per mes. Resume si --resume.
    policy=intersection: PASS si missing_in_bs=0, mismatches=0 (extra_in_bs informatiu).
    policy=exact: PASS si missing_in_bs=0, mismatches=0, extra_in_bs=0.
    """
    out_dir = Path(out_dir) if out_dir else PROJECT_ROOT / "lab/out/artifacts/BS.T9.15" / symbol / "1m" / f"{from_date.replace('-', '')}_{to_date.replace('-', '')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    months_dir = out_dir / "months"
    months_dir.mkdir(parents=True, exist_ok=True)

    if policy == POLICY_INTERSECTION:
        print("Policy: intersection (extra_in_bs ignored for PASS)")
    else:
        print("Policy: exact (extra_in_bs must be 0)")

    if not sq_input.exists():
        return {
            "gate": "BS.T9.15",
            "status": "FAIL",
            "error": f"SQ input no trobat: {sq_input}",
            "months_processed": 0,
        }

    # Carregar SQ (directori o fitxer)
    all_sq: list[dict] = []
    if sq_input.is_dir():
        for p in sorted(sq_input.glob("*.csv")):
            rows = load_sq_csv(p)
            if rows:
                all_sq.extend(rows)
    else:
        rows = load_sq_csv(sq_input)
        if not rows:
            return {
                "gate": "BS.T9.15",
                "status": "FAIL",
                "error": f"No s'han pogut parsejar candles des de {sq_input}",
                "months_processed": 0,
            }
        all_sq = rows

    if not all_sq:
        return {
            "gate": "BS.T9.15",
            "status": "FAIL",
            "error": f"0 candles SQ a {sq_input}",
            "months_processed": 0,
        }

    # Deduplicar per ts (monotònic)
    seen = set()
    dedup = []
    for r in sorted(all_sq, key=lambda x: x["ts"]):
        if r["ts"] in seen:
            continue
        seen.add(r["ts"])
        dedup.append(r)
    all_sq = dedup

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

    month_summaries: list[dict] = []
    total_missing = 0
    total_extra = 0
    total_mismatches = 0
    first_fail_month: Optional[str] = None
    first_fail_ts: Optional[int] = None
    first_fail_cause: Optional[str] = None
    first_mismatch_window_rows: Optional[list[dict]] = None

    for year, month in months:
        from_ts, to_ts = _month_range(year, month)
        month_key = f"{year}-{month:02d}"
        sq_month = [r for r in all_sq if from_ts <= r["ts"] < to_ts]

        if resume:
            month_summary_path = months_dir / month_key / "month_summary.json"
            if month_summary_path.exists():
                try:
                    with open(month_summary_path, encoding="utf-8") as f:
                        existing = json.load(f)
                    skip_ok = existing.get("pass_preu") and existing.get("pass_missing")
                    if policy == POLICY_EXACT:
                        skip_ok = skip_ok and existing.get("pass_extra")
                    if skip_ok:
                        existing["month"] = month_key
                        existing["policy"] = policy
                        month_summaries.append(existing)
                        total_missing += existing.get("missing_in_bs", 0)
                        total_extra += existing.get("extra_in_bs", 0)
                        total_mismatches += existing.get("mismatches_on_common_ts", 0)
                        print(f"MONTH {month_key}: RESUMED (skip)")
                        continue
                except (json.JSONDecodeError, KeyError):
                    pass

        if len(sq_month) == 0:
            print(f"MONTH {month_key}: SKIP (0 SQ rows)")
            continue

        print(f"MONTH {month_key}: sq={len(sq_month)}", end="", flush=True)
        try:
            bs_month = fetch_bs_candles_month(base_url, symbol, from_ts, to_ts, source=source)
        except Exception as e:
            print(f" bs_error={e}")
            month_summaries.append({
                "month": month_key,
                "sq_rows": len(sq_month),
                "bs_rows": 0,
                "error": str(e),
                "pass_preu": False,
                "pass_missing": False,
                "pass_extra": False,
            })
            if first_fail_month is None:
                first_fail_month = month_key
                first_fail_cause = f"API_ERROR: {e}"
            continue

        print(f" bs={len(bs_month)}", end="", flush=True)
        report = compare_month(sq_month, bs_month, tol=tol)
        report["month"] = month_key
        total_missing += report["missing_in_bs"]
        total_extra += report["extra_in_bs"]
        total_mismatches += report["mismatches_on_common_ts"]

        if first_fail_month is None and (report["missing_in_bs"] > 0 or report["extra_in_bs"] > 0 or report["mismatches_on_common_ts"] > 0):
            first_fail_month = month_key
            first_fail_ts = report.get("first_mismatch_ts") or (report.get("missing_in_bs_list") or [None])[0] or (report.get("extra_in_bs_list") or [None])[0]
            if report["missing_in_bs"] > 0:
                first_fail_cause = "missing_in_bs"
            elif report["extra_in_bs"] > 0:
                first_fail_cause = "extra_in_bs"
            else:
                first_fail_cause = "mismatch"

            if first_fail_ts:
                margin_s = FIRST_MISMATCH_WINDOW_MINUTES * 60
                window_min = first_fail_ts - margin_s
                window_max = first_fail_ts + margin_s
                rows_sq = [{"ts": r["ts"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "source": "sq"} for r in sq_month if window_min <= r["ts"] <= window_max]
                rows_bs = [{"ts": r["ts"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "source": "bs"} for r in bs_month if window_min <= r["ts"] <= window_max]
                first_mismatch_window_rows = sorted(rows_sq + rows_bs, key=lambda x: (x["ts"], x["source"]))

        print(f" join={report['matched_rows']} miss={report['missing_in_bs']} extra={report['extra_in_bs']} mism={report['mismatches_on_common_ts']}")

        month_dir = months_dir / month_key
        month_dir.mkdir(parents=True, exist_ok=True)
        report["policy"] = policy
        report_for_json = {k: v for k, v in report.items() if k != "missing_in_bs_full"}
        with open(month_dir / "month_summary.json", "w", encoding="utf-8") as f:
            json.dump(report_for_json, f, indent=2)

        if report.get("missing_in_bs"):
            to_write = report.get("missing_in_bs_full") or report.get("missing_in_bs_list") or []
            if to_write:
                with open(month_dir / "missing_in_bs.csv", "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["ts"])
                    for t in to_write:
                        w.writerow([t])
        if report.get("extra_in_bs"):
            extra_full = report.get("extra_in_bs_full") or report.get("extra_in_bs_list") or []
            if extra_full:
                from application.market_hours.fx_24_5 import is_market_open
                with open(month_dir / "extra_in_bs.csv", "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["ts", "market_open"])
                    for t in extra_full:
                        w.writerow([t, is_market_open(symbol, t)])
        if report.get("mismatches_sample"):
            with open(month_dir / "mismatches_top.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ts", "col", "sq", "bs", "delta_pips"])
                w.writeheader()
                w.writerows(report["mismatches_sample"])

        month_summaries.append(report)

    pass_basic = total_missing == 0 and total_mismatches == 0
    if policy == POLICY_INTERSECTION:
        gate_pass = pass_basic
    else:
        gate_pass = pass_basic and total_extra == 0
    gate_summary = {
        "gate": "BS.T9.15",
        "policy": policy,
        "status": "PASS" if gate_pass else "FAIL",
        "symbol": symbol,
        "from_date": from_date,
        "to_date": to_date,
        "source": source,
        "total_missing_in_bs": total_missing,
        "total_extra_in_bs": total_extra,
        "total_mismatches": total_mismatches,
        "total_sq_rows": len(all_sq),
        "months_processed": len(month_summaries),
        "first_fail_month": first_fail_month,
        "first_fail_ts": first_fail_ts,
        "first_fail_cause": first_fail_cause,
        "months": month_summaries,
    }
    with open(out_dir / "gate_summary.json", "w", encoding="utf-8") as f:
        json.dump(gate_summary, f, indent=2)

    with open(out_dir / "gate_summary.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["month", "sq_rows", "bs_rows", "matched_rows", "missing_in_bs", "extra_in_bs", "mismatches_on_common_ts", "max_abs_delta_pips", "pass_preu", "pass_missing", "pass_extra", "policy"],
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
                "pass_missing": m.get("pass_missing", True),
                "pass_extra": m.get("pass_extra", True),
                "policy": m.get("policy", policy),
            })

    if first_mismatch_window_rows:
        with open(out_dir / "first_mismatch_window.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "source"])
            w.writeheader()
            w.writerows(first_mismatch_window_rows)

    # sq_export_manifest.json (T9.15.2)
    files_count = 0
    if sq_input.is_dir():
        files_count = len(list(sq_input.glob("*.csv")))
    else:
        files_count = 1 if sq_input.exists() else 0
    manifest = {
        "symbol": symbol,
        "from": from_date,
        "to": to_date,
        "sq_input_path": str(sq_input),
        "export_generated_at": _mtime_iso(sq_input) if sq_input.exists() else None,
        "export_method": export_method,
        "files_count": files_count,
        "total_sq_rows": len(all_sq),
        "notes": "Format: Date,Time,O,H,L,C (UTC-05) o ts,open,high,low,close",
    }
    with open(out_dir / "sq_export_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"WRITE: gate_summary.json gate_summary.csv sq_export_manifest.json -> {out_dir}")
    return gate_summary


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="BS.T9.15 Gate SQ↔BS M1 parity (candles 1:1)")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--sq-input", type=Path, required=True, help="Path al CSV SQ (o directori amb CSVs)")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--from", dest="from_date", default="2003-01-01", help="Data inici YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", default="2026-03-04", help="Data fi YYYY-MM-DD")
    parser.add_argument("--source", default="dukascopy")
    parser.add_argument("--tf", default="1m", help="Timeframe (només 1m)")
    parser.add_argument("--outdir", type=Path, default=None)
    parser.add_argument("--chunk", default="monthly", help="Chunk mensual (únic suportat)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--months", type=int, default=None, help="Limit mesos (ex: 1 per smoke)")
    parser.add_argument("--tol", type=float, default=OHLC_TOLERANCE, help="Tolerància OHLC")
    parser.add_argument("--policy", choices=[POLICY_INTERSECTION, POLICY_EXACT], default=POLICY_EXACT,
                        help="intersection: extra_in_bs ignored; exact: extra_in_bs must be 0")
    parser.add_argument("--export-method", default="unknown", help="Com s'ha generat l'export (sqcli/manual/...)")
    args = parser.parse_args()

    result = run_gate(
        sq_input=args.sq_input,
        base_url=args.base_url,
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        source=args.source,
        out_dir=args.outdir,
        resume=args.resume,
        months_limit=args.months,
        tol=args.tol,
        policy=args.policy,
        export_method=args.export_method,
    )
    status = result.get("status", "FAIL")
    if status == "FAIL" and result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1
    if status == "PASS":
        return 0
    if status == "FAIL":
        print(f"FAIL: first_fail_month={result.get('first_fail_month')} ts={result.get('first_fail_ts')} cause={result.get('first_fail_cause')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
