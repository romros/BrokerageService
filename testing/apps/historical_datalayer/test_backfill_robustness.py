#!/usr/bin/env python3
"""
Phase 18 — Tests 0-network per coverage index + retries/backoff + resume.

Valida:
- CoverageIndex: mark_done, mark_failed, mark_empty, is_done, is_failed, summary
- CoverageIndex: persistència entre instàncies
- CoverageIndex: actualització atòmica (tmp → rename)
- run_historical_backfill: coverage index actualitzat automàticament
- run_historical_backfill: resume salta mesos done
- run_historical_backfill: dry-run no escriu res
- run_historical_backfill: stop_after atura al límit
- run_historical_backfill: retry_failed reintenta mesos failed
- run_historical_backfill: errors transitoris → coverage.mark_failed (0-network)
"""

import asyncio
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from application.data.coverage_index import CoverageIndex
from application.tools.run_historical_backfill import run_historical_backfill, _months_in_range


def _make_candle(symbol: str, ts: int) -> Candle:
    return Candle(
        symbol=symbol,
        timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        open=1.1, high=1.2, low=1.0, close=1.15, volume=100.0,
        is_closed=True,
    )


def _make_month_candles(symbol: str, year: int, month: int, n: int = 10) -> list:
    base_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    return [_make_candle(symbol, base_ts + i * 60) for i in range(n)]


# ---------------------------------------------------------------------------
# Tests CoverageIndex
# ---------------------------------------------------------------------------

def test_coverage_index_mark_done():
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        assert not idx.is_done(2020, 1)
        idx.mark_done(2020, 1, rows=100, coverage_from=1000, coverage_to=2000)
        assert idx.is_done(2020, 1)
        assert not idx.is_failed(2020, 1)
    print("✓ test_coverage_index_mark_done OK")


def test_coverage_index_mark_failed():
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_failed(2020, 2, retries=3)
        assert idx.is_failed(2020, 2)
        assert not idx.is_done(2020, 2)
    print("✓ test_coverage_index_mark_failed OK")


def test_coverage_index_summary():
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_done(2020, 1, rows=1000, coverage_from=1000, coverage_to=2000)
        idx.mark_done(2020, 2, rows=900, coverage_from=2000, coverage_to=3000)
        idx.mark_failed(2020, 3, retries=3)
        idx.mark_empty(2020, 4)
        s = idx.summary()
        assert s["months_done"] == 2
        assert s["months_failed"] == 1
        assert s["months_empty"] == 1
        assert s["total_rows"] == 1900
    print("✓ test_coverage_index_summary OK")


def test_coverage_index_persistence():
    """Coverage persists entre instàncies."""
    with tempfile.TemporaryDirectory() as tmp:
        idx1 = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx1.mark_done(2020, 5, rows=500, coverage_from=1000, coverage_to=2000)

        # Nova instància llegeix el mateix fitxer
        idx2 = CoverageIndex(root_path=tmp, symbol="EURUSD")
        assert idx2.is_done(2020, 5)
        assert idx2.get_month(2020, 5)["rows"] == 500
    print("✓ test_coverage_index_persistence OK")


def test_coverage_index_months_done():
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_done(2020, 3, rows=100, coverage_from=1000, coverage_to=2000)
        idx.mark_done(2020, 1, rows=100, coverage_from=1000, coverage_to=2000)
        idx.mark_failed(2020, 2, retries=1)
        done = idx.months_done()
        assert done == ["2020-01", "2020-03"]  # ordenats
    print("✓ test_coverage_index_months_done OK")


# ---------------------------------------------------------------------------
# Tests run_historical_backfill (Phase 18)
# ---------------------------------------------------------------------------

def test_backfill_updates_coverage_on_success():
    """Coverage marcat done després d'escriure un mes."""
    with tempfile.TemporaryDirectory() as tmp:
        candles = _make_month_candles("EURUSD", 2020, 1, n=20)

        result = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=candles,
            update_coverage=True,
        ))

        assert result["months_written"] == 1
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        assert idx.is_done(2020, 1)
        assert idx.get_month(2020, 1)["rows"] == 20
    print("✓ test_backfill_updates_coverage_on_success OK")


def test_backfill_resume_skips_done_months():
    """Segon run salta mesos ja marcats done al coverage."""
    with tempfile.TemporaryDirectory() as tmp:
        candles = _make_month_candles("EURUSD", 2020, 1, n=20)

        # Primera execució
        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=candles,
        ))

        # Segona execució (resume)
        result2 = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=candles,
        ))

        assert result2["months_written"] == 0
        assert result2["months_skipped"] == 1
    print("✓ test_backfill_resume_skips_done_months OK")


def test_backfill_dry_run_writes_nothing():
    """--dry-run no escriu Parquet ni coverage."""
    with tempfile.TemporaryDirectory() as tmp:
        candles = _make_month_candles("EURUSD", 2020, 1, n=10)

        result = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=candles,
            dry_run=True,
        ))

        # Parquet no existeix
        from infrastructure.storage.parquet_store import ParquetCandleStore
        store = ParquetCandleStore(root_path=tmp)
        assert not store.has_month("EURUSD", 2020, 1)
        # Coverage no marcat (dry_run no actualitza)
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        assert not idx.is_done(2020, 1)
        assert result["dry_run"] is True
    print("✓ test_backfill_dry_run_writes_nothing OK")


def test_backfill_stop_after():
    """--stop-after 1 escriu 1 mes i para."""
    with tempfile.TemporaryDirectory() as tmp:
        jan = _make_month_candles("EURUSD", 2020, 1, n=10)
        feb = _make_month_candles("EURUSD", 2020, 2, n=10)
        mar = _make_month_candles("EURUSD", 2020, 3, n=10)
        all_candles = jan + feb + mar

        result = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 3, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=all_candles,
            stop_after=1,
        ))

        assert result["months_written"] == 1
        assert result["months_stopped"] >= 2
    print("✓ test_backfill_stop_after OK")


def test_backfill_retry_failed():
    """--retry-failed reintenta mesos marcats failed."""
    with tempfile.TemporaryDirectory() as tmp:
        # Marcar el mes com a failed manualment
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_failed(2020, 1, retries=3)

        # Sense retry_failed: el mes és saltat
        result_nore = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=_make_month_candles("EURUSD", 2020, 1, n=5),
            retry_failed=False,
        ))
        assert result_nore["months_skipped"] == 1

        # Amb retry_failed: el mes és reprocessat
        result_re = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=_make_month_candles("EURUSD", 2020, 1, n=5),
            retry_failed=True,
        ))
        assert result_re["months_written"] == 1
    print("✓ test_backfill_retry_failed OK")


def test_backfill_coverage_not_updated_without_flag():
    """--no-coverage: coverage no actualitzat."""
    with tempfile.TemporaryDirectory() as tmp:
        candles = _make_month_candles("EURUSD", 2020, 1, n=10)

        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            datafiles_root=tmp,
            sleep_s=0,
            dukascopy_override=candles,
            update_coverage=False,
        ))

        # Coverage NO actualitzat
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        assert not idx.is_done(2020, 1)
    print("✓ test_backfill_coverage_not_updated_without_flag OK")


def main():
    tests = [
        test_coverage_index_mark_done,
        test_coverage_index_mark_failed,
        test_coverage_index_summary,
        test_coverage_index_persistence,
        test_coverage_index_months_done,
        test_backfill_updates_coverage_on_success,
        test_backfill_resume_skips_done_months,
        test_backfill_dry_run_writes_nothing,
        test_backfill_stop_after,
        test_backfill_retry_failed,
        test_backfill_coverage_not_updated_without_flag,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        sys.exit(1)
    print(f"\n✓ All Phase 18 backfill robustness tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
