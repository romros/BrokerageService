"""
T8.12 — Tests unitaris per ParityChecker (0-network).

Cobertura:
  1. test_ok_month: mes ple → status="ok", completeness_ratio >= min_records_ratio
  2. test_bad_month_low_records: menys del 90% → status="bad"
  3. test_bad_month_high_flat: flat_ratio > 0.02 → status="bad"
  4. test_missing_month: parquet no existeix → status="missing", records=0
  5. test_full_report_aggregates: months_bad i months_missing agregats correctament
"""

import calendar
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from application.data.parity_checker import MonthParity, ParityChecker, ParityReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_month_parquet(tmp_path: Path, symbol: str, year: int, month: int, df: pd.DataFrame):
    """Escriu un DataFrame com a parquet a la ruta canònica (zero-padded month)."""
    p = (
        tmp_path
        / "historical_parquet"
        / symbol
        / "tf=1m"
        / f"year={year}"
        / f"month={month:02d}"
        / "data.parquet"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return p


def _make_candles_df(year: int, month: int, n: int, flat: int = 0) -> pd.DataFrame:
    """
    Genera un DataFrame amb n candles M1 per al mes donat.
    flat: quantes barres seran flat (O=H=L=C).
    """
    base_ts = int(datetime(year, month, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    rows = []
    for i in range(n):
        ts = base_ts + i * 60
        if i < flat:
            # Barra flat
            rows.append({"ts": ts, "open": 1.3000, "high": 1.3000, "low": 1.3000, "close": 1.3000, "volume": 0.0})
        else:
            rows.append({"ts": ts, "open": 1.3000, "high": 1.3010, "low": 1.2990, "close": 1.3005, "volume": 100.0})
    return pd.DataFrame(rows)


def _expected_minutes(year: int, month: int) -> int:
    """Minuts esperats per a un mes (dies laborables * 1440)."""
    _, days = calendar.monthrange(year, month)
    business = sum(1 for d in range(1, days + 1) if datetime(year, month, d).weekday() < 5)
    return business * 1440


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ok_month(tmp_path):
    """Mes ple (>= 90% completeness, flat < 2%) → status='ok'."""
    year, month = 2020, 6
    expected = _expected_minutes(year, month)
    n = int(expected * 0.95)  # 95% records
    df = _make_candles_df(year, month, n, flat=0)
    _write_month_parquet(tmp_path, "EURUSD", year, month, df)

    checker = ParityChecker(tmp_path, "EURUSD", "1m", min_records_ratio=0.90, max_flat_ratio=0.02)
    report = checker.run(f"{year}-{month:02d}-01", f"{year}-{month:02d}-28")

    assert len(report.per_month) == 1
    mp = report.per_month[0]
    assert mp.status == "ok"
    assert mp.records == n
    assert mp.completeness_ratio >= 0.90
    assert mp.flat_bars == 0
    assert mp.flat_bars_ratio == 0.0
    assert report.months_bad == []
    assert report.months_missing == []


def test_bad_month_low_records(tmp_path):
    """Mes amb menys del 90% records → status='bad'."""
    year, month = 2020, 6
    expected = _expected_minutes(year, month)
    n = int(expected * 0.80)  # 80% records → bad
    df = _make_candles_df(year, month, n, flat=0)
    _write_month_parquet(tmp_path, "EURUSD", year, month, df)

    checker = ParityChecker(tmp_path, "EURUSD", "1m", min_records_ratio=0.90, max_flat_ratio=0.02)
    report = checker.run(f"{year}-{month:02d}-01", f"{year}-{month:02d}-28")

    assert len(report.per_month) == 1
    mp = report.per_month[0]
    assert mp.status == "bad"
    assert mp.completeness_ratio < 0.90
    assert f"{year}-{month:02d}" in report.months_bad
    assert f"{year}-{month:02d}" not in report.months_missing


def test_bad_month_high_flat(tmp_path):
    """Mes amb flat_ratio > 2% → status='bad'."""
    year, month = 2020, 6
    expected = _expected_minutes(year, month)
    n = int(expected * 0.95)    # completeness OK
    flat = int(n * 0.05)        # 5% flat bars → bad
    df = _make_candles_df(year, month, n, flat=flat)
    _write_month_parquet(tmp_path, "EURUSD", year, month, df)

    checker = ParityChecker(tmp_path, "EURUSD", "1m", min_records_ratio=0.90, max_flat_ratio=0.02)
    report = checker.run(f"{year}-{month:02d}-01", f"{year}-{month:02d}-28")

    assert len(report.per_month) == 1
    mp = report.per_month[0]
    assert mp.status == "bad"
    assert mp.flat_bars_ratio > 0.02
    assert f"{year}-{month:02d}" in report.months_bad


def test_missing_month(tmp_path):
    """Mes sense parquet → status='missing', records=0."""
    year, month = 2020, 6

    checker = ParityChecker(tmp_path, "EURUSD", "1m")
    report = checker.run(f"{year}-{month:02d}-01", f"{year}-{month:02d}-28")

    assert len(report.per_month) == 1
    mp = report.per_month[0]
    assert mp.status == "missing"
    assert mp.records == 0
    assert mp.completeness_ratio == 0.0
    assert f"{year}-{month:02d}" in report.months_missing
    assert f"{year}-{month:02d}" in report.months_bad


def test_full_report_aggregates(tmp_path):
    """Report amb 3 mesos: 1 ok, 1 bad (low records), 1 missing."""
    symbol = "EURUSD"

    # Mes 1: ok (2020-06)
    expected_jun = _expected_minutes(2020, 6)
    df_ok = _make_candles_df(2020, 6, int(expected_jun * 0.95))
    _write_month_parquet(tmp_path, symbol, 2020, 6, df_ok)

    # Mes 2: bad low records (2020-07)
    expected_jul = _expected_minutes(2020, 7)
    df_bad = _make_candles_df(2020, 7, int(expected_jul * 0.70))
    _write_month_parquet(tmp_path, symbol, 2020, 7, df_bad)

    # Mes 3: missing (2020-08) → no es crea cap fitxer

    checker = ParityChecker(tmp_path, symbol, "1m", min_records_ratio=0.90, max_flat_ratio=0.02)
    report = checker.run("2020-06-01", "2020-08-31")

    assert report.months_total == 3
    assert report.months_ok == 1
    assert len(report.months_bad) == 2   # 2020-07 bad + 2020-08 missing
    assert len(report.months_missing) == 1
    assert "2020-07" in report.months_bad
    assert "2020-08" in report.months_bad
    assert "2020-08" in report.months_missing
    assert "2020-06" not in report.months_bad

    # total_records = ok + bad (not missing)
    expected_total = int(expected_jun * 0.95) + int(expected_jul * 0.70)
    assert report.total_records == expected_total

    # coverage_from/to: primer i últim mes amb parquet (2020-06 fins 2020-07)
    assert report.coverage_from.startswith("2020-06")
    assert report.coverage_to.startswith("2020-07")

    # thresholds documentats
    assert report.thresholds["min_records_ratio"] == 0.90
    assert report.thresholds["max_flat_ratio"] == 0.02
