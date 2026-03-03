"""
Tests unitaris per BS.T9.13 — ParquetTicksStore + builder helpers.

Cobertura:
  1. test_partition_path_format:       path v2 layout correcte
  2. test_write_month_atomic:          escriptura atòmica (.tmp → rename)
  3. test_write_month_empty_skip:      candles=[] → no crea fitxer
  4. test_has_month_false_if_missing:  has_month=False si no existeix
  5. test_has_month_true_after_write:  has_month=True després d'escriure
  6. test_write_month_overwrite:       --force sobreescriu (idempotent)
  7. test_months_in_range_single:      1 mes exacte
  8. test_months_in_range_multi:       rang multi-mes
  9. test_months_in_range_exclusive:   to_date primer dia del mes → no inclòs
 10. test_month_range_utc:             start/end UTC correctes per un mes
 11. test_compute_gaps_none:           cap gap si candles consecutives
 12. test_compute_gaps_detected:       gap detectat correctament
 13. test_duckdb_legacy_root:          DUKASCOPY_PARQUET_ACTIVE absent → root legacy
 14. test_duckdb_ticks_root:           DUKASCOPY_PARQUET_ACTIVE=ticks → root v2
 15. test_coverage_empty:              coverage buit si no hi ha particions
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.tools.build_dukascopy_parquet_ticks import (
    ParquetTicksStore,
    _months_in_range,
    _month_range_utc,
    _compute_gaps,
)
from domain.models import Candle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(ts_epoch: int, val: float = 1.1) -> Candle:
    return Candle(
        symbol="EURUSD",
        timestamp=datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
        open=val, high=val + 0.001, low=val - 0.001, close=val,
        volume=0.0, is_closed=True,
    )


def _consecutive_candles(start_ts: int, count: int) -> list[Candle]:
    return [_make_candle(start_ts + i * 60) for i in range(count)]


# ---------------------------------------------------------------------------
# Tests ParquetTicksStore
# ---------------------------------------------------------------------------

def test_partition_path_format() -> bool:
    """El path v2 ha de seguir el layout {root}/{SYMBOL}/tf=1m/year=YYYY/month=MM/data.parquet."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        p = store._partition_path("EURUSD", 2025, 3)
        expected = Path(tmp) / "EURUSD" / "tf=1m" / "year=2025" / "month=03" / "data.parquet"
        ok = p == expected
        if not ok:
            print(f"  FAIL: got {p}, expected {expected}")
        return ok


def test_write_month_atomic() -> bool:
    """L'escriptura ha de crear el fitxer final (no .tmp)."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        candles = _consecutive_candles(1_740_787_200, 5)  # 2025-03-01 00:00 UTC
        written = store.write_month("EURUSD", 2025, 3, candles)
        ok = written is not None and written.exists()
        tmp_path = written.with_suffix(".tmp.parquet") if written else None
        ok = ok and (tmp_path is None or not tmp_path.exists())
        if not ok:
            print(f"  FAIL: written={written}, tmp_exists={tmp_path and tmp_path.exists()}")
        return ok


def test_write_month_empty_skip() -> bool:
    """candles=[] → no s'ha de crear cap fitxer."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        result = store.write_month("EURUSD", 2025, 3, [])
        ok = result is None
        # Verificar que no hi ha cap fitxer creat
        parquet_path = store._partition_path("EURUSD", 2025, 3)
        ok = ok and not parquet_path.exists()
        if not ok:
            print(f"  FAIL: result={result}, parquet_exists={parquet_path.exists()}")
        return ok


def test_has_month_false_if_missing() -> bool:
    """has_month=False si no s'ha escrit mai."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        ok = not store.has_month("EURUSD", 2025, 3)
        if not ok:
            print("  FAIL: has_month hauria de ser False per mes no escrit")
        return ok


def test_has_month_true_after_write() -> bool:
    """has_month=True després d'escriure candles."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        candles = _consecutive_candles(1_740_787_200, 10)
        store.write_month("EURUSD", 2025, 3, candles)
        ok = store.has_month("EURUSD", 2025, 3)
        if not ok:
            print("  FAIL: has_month hauria de ser True")
        return ok


def test_write_month_overwrite() -> bool:
    """Escriure dos cops el mateix mes sobreescriu idempotentment."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        candles1 = _consecutive_candles(1_740_787_200, 5)
        candles2 = _consecutive_candles(1_740_787_200, 10)
        store.write_month("EURUSD", 2025, 3, candles1)
        store.write_month("EURUSD", 2025, 3, candles2)
        # Llegim i verifiquem que tenim les candles del segon write
        import pyarrow.parquet as pq
        path = store._partition_path("EURUSD", 2025, 3)
        meta = pq.read_metadata(str(path))
        ok = meta.num_rows == 10
        if not ok:
            print(f"  FAIL: num_rows={meta.num_rows}, esperava 10")
        return ok


# ---------------------------------------------------------------------------
# Tests helpers
# ---------------------------------------------------------------------------

def test_months_in_range_single() -> bool:
    """Un mes exacte → 1 entrada."""
    months = _months_in_range("2025-03-01", "2025-04-01")
    ok = months == [(2025, 3)]
    if not ok:
        print(f"  FAIL: {months}")
    return ok


def test_months_in_range_multi() -> bool:
    """Rang de 3 mesos → 3 entrades."""
    months = _months_in_range("2025-01-01", "2025-04-01")
    ok = months == [(2025, 1), (2025, 2), (2025, 3)]
    if not ok:
        print(f"  FAIL: {months}")
    return ok


def test_months_in_range_exclusive() -> bool:
    """to_date=primer dia del mes → aquell mes NO s'inclou."""
    months = _months_in_range("2025-03-01", "2025-03-01")
    ok = months == []
    if not ok:
        print(f"  FAIL: {months} (hauria de ser buit)")
    return ok


def test_month_range_utc() -> bool:
    """start/end UTC per 2025-03 ha de ser 2025-03-01 00:00 → 2025-04-01 00:00."""
    start, end = _month_range_utc(2025, 3)
    ok = (
        start == datetime(2025, 3,  1, 0, 0, 0, tzinfo=timezone.utc) and
        end   == datetime(2025, 4,  1, 0, 0, 0, tzinfo=timezone.utc)
    )
    if not ok:
        print(f"  FAIL: start={start}, end={end}")
    return ok


def test_compute_gaps_none() -> bool:
    """Cap gap si candles consecutives cada 60s."""
    candles = _consecutive_candles(1_000_000, 10)
    gaps = _compute_gaps(candles)
    ok = len(gaps) == 0
    if not ok:
        print(f"  FAIL: {gaps}")
    return ok


def test_compute_gaps_detected() -> bool:
    """Gap de 2 minuts (120s) ha de ser detectat."""
    candles = [
        _make_candle(1_000_000),
        _make_candle(1_000_060),
        _make_candle(1_000_180),  # gap: 120s en comptes de 60s
        _make_candle(1_000_240),
    ]
    gaps = _compute_gaps(candles)
    ok = len(gaps) == 1 and gaps[0]["gap_s"] == 120
    if not ok:
        print(f"  FAIL: gaps={gaps}")
    return ok


# ---------------------------------------------------------------------------
# Tests DuckDBQueryService switch
# ---------------------------------------------------------------------------

def test_duckdb_legacy_root() -> bool:
    """DUKASCOPY_PARQUET_ACTIVE absent → root legacy + source=historical_parquet."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k != "DUKASCOPY_PARQUET_ACTIVE"}
        with patch.dict(os.environ, env, clear=True):
            from infrastructure.query.duckdb_query_service import DuckDBQueryService
            svc = DuckDBQueryService(root_path=tmp)
        ok = svc._source_label == "historical_parquet"
        if not ok:
            print(f"  FAIL: source_label={svc._source_label}")
        return ok


def test_duckdb_ticks_root() -> bool:
    """DUKASCOPY_PARQUET_ACTIVE=ticks → source=dukascopy_ticks_v1."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {"DUKASCOPY_PARQUET_ACTIVE": "ticks"}, clear=False):
            from infrastructure.query import duckdb_query_service
            import importlib
            importlib.reload(duckdb_query_service)
            svc = duckdb_query_service.DuckDBQueryService(root_path=tmp)
        ok = svc._source_label == "dukascopy_ticks_v1"
        if not ok:
            print(f"  FAIL: source_label={svc._source_label}")
        return ok


def test_coverage_empty() -> bool:
    """coverage() retorna [] si no hi ha particions."""
    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetTicksStore(root_path=tmp)
        cov = store.coverage("EURUSD")
        ok = cov == []
        if not ok:
            print(f"  FAIL: {cov}")
        return ok


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TESTS = [
    test_partition_path_format,
    test_write_month_atomic,
    test_write_month_empty_skip,
    test_has_month_false_if_missing,
    test_has_month_true_after_write,
    test_write_month_overwrite,
    test_months_in_range_single,
    test_months_in_range_multi,
    test_months_in_range_exclusive,
    test_month_range_utc,
    test_compute_gaps_none,
    test_compute_gaps_detected,
    test_duckdb_legacy_root,
    test_duckdb_ticks_root,
    test_coverage_empty,
]


def main() -> int:
    passed = 0
    failed = 0
    for test_fn in _TESTS:
        name = test_fn.__name__
        try:
            ok = test_fn()
        except Exception as e:
            print(f"  ERROR: {name}: {e}")
            ok = False
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}")

    total = passed + failed
    print(f"\n{passed}/{total} tests passats")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
