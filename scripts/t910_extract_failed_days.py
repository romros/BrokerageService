#!/usr/bin/env python3
"""
BS.T9.10.1 — Extreure llista exacta de dies fallats d'un job RAW (inferida per rang vs FS).
No-delete; artifacts a lab/datalayer/artifacts/BS.T9.10/.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS_DEFAULT = ROOT / "lab" / "datalayer" / "artifacts" / "BS.T9.10"
RAW_BI5_NAME = "BID_candles_min_1.bi5"
REASON_UNKNOWN = "unknown"
REASON_NO_DATA = "no_data"
REASON_TRANSIENT = "transient"
REASON_PARTIAL_CORRUPT = "partial_or_corrupt"
SOURCE_INFERRED = "inferred_from_missing_raw"
SOURCE_JOB_LOG = "job_log"


def _days_in_range(from_d: date, to_d: date) -> list[date]:
    """Rang [from_d, to_d) exclusiu."""
    out = []
    cur = from_d
    while cur < to_d:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _raw_bi5_path(raw_root: Path, symbol: str, d: date) -> Path:
    return raw_root / symbol / f"year={d.year}" / f"month={d.month:02d}" / f"day={d.day:02d}" / RAW_BI5_NAME


def _exists_valid_bi5(raw_root: Path, symbol: str, d: date) -> bool:
    p = _raw_bi5_path(raw_root, symbol, d)
    return p.exists() and p.stat().st_size > 0


def _classify_day(raw_root: Path, symbol: str, d: date) -> tuple[str, str]:
    """reason_code, reason_detail. Sense logs només podem inferir missing vs partial."""
    p = _raw_bi5_path(raw_root, symbol, d)
    dir_path = p.parent
    if p.exists():
        if p.stat().st_size == 0:
            return REASON_PARTIAL_CORRUPT, "bi5 size 0"
        return REASON_UNKNOWN, "exists_ok"
    tmp_path = dir_path / f"{RAW_BI5_NAME}.tmp"
    if tmp_path.exists():
        return REASON_PARTIAL_CORRUPT, "tmp penjat"
    if dir_path.exists():
        return REASON_PARTIAL_CORRUPT, "dir sense bi5"
    return REASON_UNKNOWN, SOURCE_INFERRED


def load_job_range(job_id: str, datafiles_root: Path) -> tuple[str, str, list[str]]:
    """from_date, to_date, symbols des de job persistit."""
    job_path = datafiles_root / "jobs" / "raw_sync" / f"{job_id}.json"
    if not job_path.exists():
        raise FileNotFoundError(f"Job file no trobat: {job_path}")
    data = json.loads(job_path.read_text())
    return data["from_date"], data["to_date"], data.get("symbols", ["EURUSD"])


def extract_failed_days(
    job_id: str,
    final_report_path: Path,
    artifacts_dir: Path,
    job_log_path: Path | None,
) -> int:
    with open(final_report_path) as f:
        report = json.load(f)
    raw_root = Path(report.get("raw_root") or "")
    if not raw_root or not raw_root.exists():
        df = report.get("datafiles_root") or ""
        raw_root = Path(df) / "dukascopy_raw" / "m1_bi5_bid"
    datafiles_root = Path(report.get("datafiles_root") or str(raw_root.parent.parent))
    from_date_s, to_date_s, symbols = load_job_range(job_id, datafiles_root)
    from_d = date.fromisoformat(from_date_s)
    to_d = date.fromisoformat(to_date_s)
    if not symbols:
        symbols = ["EURUSD"]

    all_days = _days_in_range(from_d, to_d)
    failed_rows: list[dict] = []
    for d in all_days:
        missing = False
        reason_code = REASON_UNKNOWN
        reason_detail = SOURCE_INFERRED
        for sym in symbols:
            if not _exists_valid_bi5(raw_root, sym, d):
                missing = True
                reason_code, reason_detail = _classify_day(raw_root, sym, d)
                break
        if missing:
            failed_rows.append({
                "date": d.isoformat(),
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "source_ref": SOURCE_INFERRED,
            })

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    failed_days_path = artifacts_dir / "failed_days.csv"
    with open(failed_days_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "reason_code", "reason_detail", "source_ref"])
        w.writeheader()
        w.writerows(failed_rows)

    by_reason: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for r in failed_rows:
        by_reason[r["reason_code"]] = by_reason.get(r["reason_code"], 0) + 1
        ym = r["date"][:7]
        by_month[ym] = by_month.get(ym, 0) + 1
    dates_only = [r["date"] for r in failed_rows]
    summary = {
        "job_id": job_id,
        "from_date": from_date_s,
        "to_date": to_date_s,
        "total_failed": len(failed_rows),
        "by_reason_code": by_reason,
        "by_month": dict(sorted(by_month.items())),
        "min_date": min(dates_only) if dates_only else None,
        "max_date": max(dates_only) if dates_only else None,
    }
    summary_path = artifacts_dir / "failed_days_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    gap_date = "2026-02-27"
    in_range = from_d <= date.fromisoformat(gap_date) < to_d
    in_failed = gap_date in dates_only
    gap_json = {
        "gap_date": gap_date,
        "job_id": job_id,
        "job_from": from_date_s,
        "job_to": to_date_s,
        "in_job_range": in_range,
        "in_failed_days": in_failed,
        "conclusion": "gap_explained_by_this_job" if (in_range and in_failed) else (
            "gap_outside_job_range" if not in_range else "gap_date_not_in_failed_list"
        ),
        "hour_level_signals": None,
    }
    gap_path = artifacts_dir / "gap_crosscheck_2026-02-27.json"
    with open(gap_path, "w") as f:
        json.dump(gap_json, f, indent=2)

    print(f"failed_days: {len(failed_rows)} → {failed_days_path}")
    print(f"summary: {summary_path}")
    print(f"gap_crosscheck: {gap_path} (2026-02-27 in_range={in_range} in_failed={in_failed})")
    return len(failed_rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="T9.10.1 Extract failed days from job (infer from range vs FS)")
    ap.add_argument("--job-id", default="9c9f42f95fa3", help="Job ID")
    ap.add_argument("--final-report", type=Path, default=ARTIFACTS_DEFAULT / "final_report.json")
    ap.add_argument("--job-log", type=Path, default=None)
    ap.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DEFAULT)
    args = ap.parse_args()
    if not args.final_report.exists():
        print(f"ERROR: final_report no trobat: {args.final_report}", file=sys.stderr)
        return 1
    n = extract_failed_days(args.job_id, args.final_report, args.artifacts_dir, args.job_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
