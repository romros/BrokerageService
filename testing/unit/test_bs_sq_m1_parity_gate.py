"""
BS.T9.03 — Tests unitaris per bs_sq_m1_parity_gate (0-network).

Cobertura:
  1. load_sq_csv format A (ts, open, high, low, close) → rows normalitzats
  2. load_sq_csv múltiples files (Format A) → ts consecutius
  3. compare_month: join per ts, missing_in_bs, extra_in_bs, mismatches
  4. run_gate dry_run → status DRY_RUN, months_count
  5. run_gate sq_csv missing → status FAIL, error
"""

import csv
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.datalayer.bs_sq_m1_parity_gate import (
    load_sq_csv,
    compare_month,
    run_gate,
    _month_range,
    find_contiguous_5y_range,
    OHLC_TOLERANCE,
)


def test_month_range():
    """_month_range retorna from_ts, to_ts UTC per un mes."""
    from_ts, to_ts = _month_range(2024, 2)
    assert from_ts == int(datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    # 29 dies febrer 2024; to_ts = inici del dia següent (exclusiu)
    assert to_ts > from_ts
    assert (to_ts - from_ts) >= 29 * 86400


def test_load_sq_csv_format_a(tmp_path):
    """Format A: ts, open, high, low, close → retorna rows."""
    p = tmp_path / "a.csv"
    p.write_text("ts,open,high,low,close\n1704067200,1.08,1.081,1.079,1.0805\n")
    rows = load_sq_csv(p)
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["ts"] == 1704067200
    assert abs(rows[0]["open"] - 1.08) < 1e-9
    assert abs(rows[0]["close"] - 1.0805) < 1e-9


def test_load_sq_csv_multiple_rows(tmp_path):
    """load_sq_csv amb diverses files (Format A) retorna llista amb ts consecutius."""
    p = tmp_path / "multi.csv"
    p.write_text("ts,open,high,low,close\n1704067200,1.08,1.081,1.079,1.08\n1704067260,1.08,1.0815,1.0795,1.081\n")
    rows = load_sq_csv(p)
    assert rows is not None
    assert len(rows) == 2
    assert rows[1]["ts"] - rows[0]["ts"] == 60


def test_load_sq_csv_missing_returns_none():
    """Fitxer inexistent → None."""
    assert load_sq_csv(Path("/tmp/noexist_t903_gate.csv")) is None


def test_compare_month_exact_match():
    """Mateixes rows → pass_preu True, 0 mismatches."""
    rows = [
        {"ts": 100, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
        {"ts": 160, "open": 1.15, "high": 1.25, "low": 1.05, "close": 1.2},
    ]
    report = compare_month(rows, rows, tol=OHLC_TOLERANCE)
    assert report["matched_rows"] == 2
    assert report["missing_in_bs"] == 0
    assert report["extra_in_bs"] == 0
    assert report["mismatches_on_common_ts"] == 0
    assert report["pass_preu"] is True


def test_compare_month_mismatch_delta():
    """Delta OHLC > tol → mismatches, pass_preu False."""
    sq = [{"ts": 100, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15}]
    bs = [{"ts": 100, "open": 1.1 + 1e-4, "high": 1.2, "low": 1.0, "close": 1.15}]
    report = compare_month(sq, bs, tol=1e-5)
    assert report["matched_rows"] == 1
    assert report["mismatches_on_common_ts"] == 1
    assert report["pass_preu"] is False
    assert len(report["mismatches_sample"]) == 1
    assert report["mismatches_sample"][0]["col"] == "open"


def test_compare_month_missing_extra():
    """SQ té ts que BS no té (missing_in_bs); BS té ts que SQ no té (extra_in_bs)."""
    sq = [{"ts": 100, "open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1}]
    bs = [{"ts": 160, "open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1}]
    report = compare_month(sq, bs, tol=1e-5)
    assert report["matched_rows"] == 0
    assert report["missing_in_bs"] == 1
    assert report["extra_in_bs"] == 1
    assert report["pass_preu"] is True  # no mismatch on common ts (n'hi ha zero)


def test_find_contiguous_5y_range_ok():
    """60 mesos consecutius 'done' amb rows>0 → retorna (from_date, to_date)."""
    months = {}
    # 2019-01 .. 2023-12 = 60 mesos
    for y in range(2019, 2024):
        for m in range(1, 13):
            months[f"{y}-{m:02d}"] = {"status": "done", "rows": 40000}
    out = find_contiguous_5y_range(months)
    assert out is not None
    from_d, to_d = out
    assert from_d == "2019-01-01"
    assert to_d == "2024-01-01"


def test_find_contiguous_5y_range_insufficient():
    """Menys de 60 mesos o amb forat → None."""
    assert find_contiguous_5y_range({}) is None
    months = {f"2020-{m:02d}": {"status": "done", "rows": 1} for m in range(1, 13)}
    assert find_contiguous_5y_range(months) is None  # només 12 mesos
    # 60 mesos però sense "done" o rows=0
    months["2021-01"] = {"status": "empty", "rows": 0}
    for y in (2021, 2022, 2023):
        for m in range(1, 13):
            months[f"{y}-{m:02d}"] = {"status": "done", "rows": 40000}
    for y in (2019, 2020):
        for m in range(1, 13):
            months[f"{y}-{m:02d}"] = {"status": "done", "rows": 40000}
    # Falta 2019-06
    del months["2019-06"]
    out = find_contiguous_5y_range(months)
    assert out is None


def test_run_gate_dry_run(tmp_path):
    """run_gate --dry-run retorna status DRY_RUN i months (sense cobertura BS)."""
    csv_path = tmp_path / "sq.csv"
    csv_path.write_text("ts,open,high,low,close\n1704067200,1.08,1.081,1.079,1.08\n")
    result = run_gate(
        sq_csv=csv_path,
        base_url="http://localhost:8081",
        from_date="2024-01-01",
        to_date="2024-03-01",
        out_dir=tmp_path / "out",
        dry_run=True,
        auto_range=False,
    )
    assert result["status"] == "DRY_RUN"
    assert result["months_count"] == 3  # gen, feb, mar
    assert "2024-01" in result["months"]


def test_run_gate_sq_csv_missing():
    """run_gate amb sq_csv inexistent → status FAIL, error."""
    result = run_gate(
        sq_csv=Path("/tmp/noexist_t903.csv"),
        base_url="http://localhost:8081",
        from_date="2024-01-01",
        to_date="2024-02-01",
        dry_run=False,
        auto_range=False,
    )
    assert result["status"] == "FAIL"
    assert "no trobat" in result.get("error", "").lower() or "no existe" in result.get("error", "").lower()


def main() -> int:
    import tempfile
    tests = [
        test_month_range,
        test_find_contiguous_5y_range_ok,
        test_find_contiguous_5y_range_insufficient,
        test_load_sq_csv_format_a,
        test_load_sq_csv_multiple_rows,
        test_load_sq_csv_missing_returns_none,
        test_compare_month_exact_match,
        test_compare_month_mismatch_delta,
        test_compare_month_missing_extra,
        test_run_gate_dry_run,
        test_run_gate_sq_csv_missing,
    ]
    for t in tests:
        if t.__name__ in ("test_load_sq_csv_format_a", "test_load_sq_csv_multiple_rows", "test_run_gate_dry_run"):
            with tempfile.TemporaryDirectory() as tmp:
                t(Path(tmp))
        else:
            t()
        print(f"OK {t.__name__}")
    print("OK test_bs_sq_m1_parity_gate (all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
