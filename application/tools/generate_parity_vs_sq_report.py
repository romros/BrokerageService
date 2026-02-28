"""
T8.26 — Genera parity_EURUSD_M1_vs_SQ.json des de l'estat actual del Parquet.

Llegeix parquets EURUSD M1, compara amb baseline SQ (8.5M rows), escriu report
al format esperat per lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json.

Ús:
    python3 -m application.tools.generate_parity_vs_sq_report \
        --symbol EURUSD --datafiles-root /datafiles \
        --out lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SQ_BASELINE_ROWS = 8_499_508
SQ_COVERAGE_FROM = "2003-05-05"
SQ_COVERAGE_TO = "2026-02-28"
SQ_MONTHS_TOTAL = 274


def generate_report(
    symbol: str,
    datafiles_root: str,
    sq_rows: int = SQ_BASELINE_ROWS,
) -> dict:
    from application.tools.missing_months_report import (
        _all_months_in_range,
        _months_with_data,
        _rows_per_month,
    )

    from_d = date(2003, 5, 1)
    to_d = date(2026, 2, 28)

    months_with_data = _months_with_data(datafiles_root, symbol)
    rows_by_month = _rows_per_month(datafiles_root, symbol)
    all_months = _all_months_in_range(from_d, to_d)

    our_rows = sum(rows_by_month.values())
    missing = [(y, m) for y, m in all_months if (y, m) not in months_with_data]
    missing_strs = [f"{y:04d}-{m:02d}" for y, m in missing]

    months_done = len(months_with_data)
    coverage_from = None
    coverage_to = None
    if months_with_data:
        sorted_done = sorted(months_with_data)
        coverage_from = f"{sorted_done[0][0]:04d}-{sorted_done[0][1]:02d}"
        coverage_to = f"{sorted_done[-1][0]:04d}-{sorted_done[-1][1]:02d}"

    gap_pre_2007 = sum(1 for y, m in missing if y < 2007)
    gap_2007_2011 = sum(
        1 for y, m in missing if (y == 2007 and m >= 6) or (2008 <= y <= 2011)
    )
    gap_post_2012 = sum(1 for y, m in missing if y > 2011)

    delta_rows = our_rows - sq_rows
    delta_pct = round(delta_rows / sq_rows * 100, 2) if sq_rows else 0

    if coverage_from and coverage_to:
        expl = f"Our Parquet: {our_rows:,} rows, {coverage_from}→{coverage_to}. Delta -{abs(delta_pct)}% vs SQ."
    else:
        expl = f"Our Parquet: {our_rows:,} rows. Delta -{abs(delta_pct)}% vs SQ."

    if gap_2007_2011 > 0 and delta_pct < -5:
        expl += f" {gap_2007_2011} mesos buits 2007-06→2011-12 (reparables via BI5, T8.26)."

    gate = "PASS" if delta_pct >= -3 and coverage_from and "2003" in coverage_from else "PARTIAL"
    criteria = "PASS: delta≥-3% i coverage_from≤2003-05" if gate == "PASS" else (
        "PARTIAL: delta residual o coverage incomplet. Post-T8.26: executar repair_missing_months_bi5 --fix."
    )

    return {
        "report_type": "parity_vs_SQ",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sq_baseline": {
            "dataset": "EURUSD_M1_dukas_M1_UTCMinus05",
            "total_records": sq_rows,
            "coverage_from": SQ_COVERAGE_FROM,
            "coverage_to": SQ_COVERAGE_TO,
            "months_total": SQ_MONTHS_TOTAL,
        },
        "our_data": {
            "total_rows": our_rows,
            "coverage_from": coverage_from or "",
            "coverage_to": coverage_to or "",
            "months_done": months_done,
            "months_missing_total": len(missing),
            "months_missing_pre_2007": gap_pre_2007,
            "months_missing_2007_2011_duka_empty": gap_2007_2011,
            "months_missing_post_2012": gap_post_2012,
        },
        "delta": {
            "rows_delta": delta_rows,
            "rows_delta_pct": delta_pct,
            "coverage_gap_months": len(missing),
            "explanation": expl,
        },
        "gate_status": gate,
        "gate_pass_criteria": criteria,
        "months_missing_list": missing_strs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.26 — Parity vs SQ report")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--datafiles-root", default="/datafiles")
    parser.add_argument("--out", default="lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json")
    parser.add_argument("--sq-rows", type=int, default=SQ_BASELINE_ROWS)
    args = parser.parse_args()

    report = generate_report(args.symbol, args.datafiles_root, args.sq_rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  parity vs SQ: {report['our_data']['total_rows']:,} rows, delta {report['delta']['rows_delta_pct']}%, gate={report['gate_status']}")
    print(f"  Artifact: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
