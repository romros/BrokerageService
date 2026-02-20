#!/usr/bin/env python3
"""
Phase 15 — Tests 0-network per Parquet storage + Historical backfill runner.

Valida:
- write_month crea partició correcta
- read_month retorna candles idèntiques
- rerun idempotent (sobreescriu sense duplicar)
- validació monotonia + duplicats
- read_range per múltiples mesos
- runner backfill (0-network via dukascopy_override)
- skip_existing salta particions existents
- runner: callback on_month_done
- coverage() retorna particions existents
"""

import asyncio
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from infrastructure.storage.parquet_store import ParquetCandleStore, _validate_candles
from application.tools.run_historical_backfill import run_historical_backfill, _months_in_range


def _make_month_candles(year: int, month: int, symbol: str = "EURUSD", n: int = 100) -> list[Candle]:
    """Genera n candles consecutives dins d'un mes (1m cada una)."""
    start_ts = int(datetime(year, month, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    candles = []
    for i in range(n):
        ts = datetime.fromtimestamp(start_ts + i * 60, tz=timezone.utc)
        o = 1.0500 + (i % 10) * 0.0001
        candles.append(Candle(
            symbol=symbol, timestamp=ts,
            open=o, high=o + 0.0005, low=o - 0.0005, close=o + 0.0002,
            volume=0, is_closed=True,
        ))
    return candles


# ---------------------------------------------------------------------------
# Tests ParquetCandleStore
# ---------------------------------------------------------------------------

def test_write_and_read_month():
    """write_month + read_month retornen les mateixes candles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        candles = _make_month_candles(2003, 1, n=50)
        path = store.write_month("EURUSD", 2003, 1, candles)
        assert path.exists(), f"Fitxer no creat: {path}"
        result = store.read_month("EURUSD", 2003, 1)
        assert len(result) == 50
        assert result[0].timestamp == candles[0].timestamp
        assert abs(result[0].open - candles[0].open) < 1e-9
    print("✓ test_write_and_read_month OK")


def test_write_idempotent():
    """Rerun write_month sobreescriu sense duplicar."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        candles = _make_month_candles(2003, 2, n=30)
        store.write_month("EURUSD", 2003, 2, candles)
        store.write_month("EURUSD", 2003, 2, candles)  # rerun
        result = store.read_month("EURUSD", 2003, 2)
        assert len(result) == 30, f"Duplicats detectats: {len(result)}"
    print("✓ test_write_idempotent OK")


def test_read_nonexistent_returns_empty():
    """read_month d'un mes inexistent retorna []."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        result = store.read_month("EURUSD", 1999, 1)
        assert result == []
    print("✓ test_read_nonexistent_returns_empty OK")


def test_has_month():
    """has_month detecta correctament existència."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        assert not store.has_month("EURUSD", 2003, 3)
        store.write_month("EURUSD", 2003, 3, _make_month_candles(2003, 3, n=10))
        assert store.has_month("EURUSD", 2003, 3)
    print("✓ test_has_month OK")


def test_read_range_multi_month():
    """read_range combina múltiples mesos i filtra per rang."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        jan = _make_month_candles(2003, 1, n=20)
        feb = _make_month_candles(2003, 2, n=20)
        store.write_month("EURUSD", 2003, 1, jan)
        store.write_month("EURUSD", 2003, 2, feb)

        start = datetime(2003, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2003, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = store.read_range("EURUSD", start, end)
        assert len(result) == 40
    print("✓ test_read_range_multi_month OK")


def test_validate_duplicates_raises():
    """Validació detecta duplicats."""
    candles = _make_month_candles(2003, 1, n=5)
    candles_dup = candles + [candles[0]]  # duplicat
    try:
        _validate_candles(candles_dup)
        assert False, "Hauria d'haver llançat ValueError"
    except ValueError as e:
        assert "duplicada" in str(e)
    print("✓ test_validate_duplicates_raises OK")


def test_validate_non_monotonic_raises():
    """Validació detecta timestamps no monotònics."""
    candles = _make_month_candles(2003, 1, n=5)
    # Invertim ordre dels dos darrers
    candles[-1], candles[-2] = candles[-2], candles[-1]
    try:
        _validate_candles(candles)
        assert False, "Hauria d'haver llançat ValueError"
    except ValueError as e:
        assert "monotònic" in str(e)
    print("✓ test_validate_non_monotonic_raises OK")


def test_coverage():
    """coverage() retorna llista de particions existents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ParquetCandleStore(root_path=tmpdir)
        store.write_month("EURUSD", 2003, 1, _make_month_candles(2003, 1, n=10))
        store.write_month("EURUSD", 2003, 3, _make_month_candles(2003, 3, n=5))
        cov = store.coverage("EURUSD")
        assert len(cov) == 2
        assert cov[0] == {"year": 2003, "month": 1, "candles_count": 10}
        assert cov[1] == {"year": 2003, "month": 3, "candles_count": 5}
    print("✓ test_coverage OK")


# ---------------------------------------------------------------------------
# Tests run_historical_backfill runner
# ---------------------------------------------------------------------------

def test_runner_writes_months():
    """Runner escriu particions mensuals per rang."""
    jan = _make_month_candles(2003, 1, n=30)
    feb = _make_month_candles(2003, 2, n=25)
    all_candles = jan + feb

    with tempfile.TemporaryDirectory() as tmpdir:
        result = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 2, 28),
            datafiles_root=tmpdir,
            sleep_s=0,
            dukascopy_override=all_candles,
        ))
        assert result["months_written"] == 2
        assert result["months_skipped"] == 0
        assert result["candles_total"] == 55

        store = ParquetCandleStore(root_path=tmpdir)
        assert store.has_month("EURUSD", 2003, 1)
        assert store.has_month("EURUSD", 2003, 2)
    print("✓ test_runner_writes_months OK")


def test_runner_skip_existing():
    """Runner salta particions existents (skip_existing=True)."""
    candles = _make_month_candles(2003, 1, n=20)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Primera passada: escriu
        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 1, 31),
            datafiles_root=tmpdir,
            sleep_s=0,
            dukascopy_override=candles,
        ))
        # Segona passada: skip_existing=True → salta
        result2 = asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 1, 31),
            datafiles_root=tmpdir,
            sleep_s=0,
            skip_existing=True,
            dukascopy_override=candles,
        ))
        assert result2["months_written"] == 0
        assert result2["months_skipped"] == 1
    print("✓ test_runner_skip_existing OK")


def test_runner_no_skip_overwrites():
    """Runner sobreescriu particions si skip_existing=False."""
    candles_v1 = _make_month_candles(2003, 1, n=10)
    candles_v2 = _make_month_candles(2003, 1, n=20)

    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 1, 31),
            datafiles_root=tmpdir,
            sleep_s=0,
            dukascopy_override=candles_v1,
        ))
        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 1, 31),
            datafiles_root=tmpdir,
            sleep_s=0,
            skip_existing=False,
            dukascopy_override=candles_v2,
        ))
        store = ParquetCandleStore(root_path=tmpdir)
        result = store.read_month("EURUSD", 2003, 1)
        assert len(result) == 20, f"Esperava 20, obtingut {len(result)}"
    print("✓ test_runner_no_skip_overwrites OK")


def test_runner_on_month_done_callback():
    """on_month_done callback cridat per cada mes."""
    candles = _make_month_candles(2003, 1, n=15)
    callbacks = []

    with tempfile.TemporaryDirectory() as tmpdir:
        asyncio.run(run_historical_backfill(
            symbol="EURUSD",
            from_date=date(2003, 1, 1),
            to_date=date(2003, 1, 31),
            datafiles_root=tmpdir,
            sleep_s=0,
            dukascopy_override=candles,
            on_month_done=lambda y, m, n: callbacks.append((y, m, n)),
        ))
        assert len(callbacks) == 1
        assert callbacks[0] == (2003, 1, 15)
    print("✓ test_runner_on_month_done_callback OK")


def test_months_in_range():
    """_months_in_range genera els mesos correctes."""
    months = _months_in_range(date(2003, 11, 1), date(2004, 2, 28))
    assert months == [(2003, 11), (2003, 12), (2004, 1), (2004, 2)]
    print("✓ test_months_in_range OK")


def main():
    tests = [
        test_write_and_read_month,
        test_write_idempotent,
        test_read_nonexistent_returns_empty,
        test_has_month,
        test_read_range_multi_month,
        test_validate_duplicates_raises,
        test_validate_non_monotonic_raises,
        test_coverage,
        test_runner_writes_months,
        test_runner_skip_existing,
        test_runner_no_skip_overwrites,
        test_runner_on_month_done_callback,
        test_months_in_range,
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
    print(f"\n✓ All Phase 15 Parquet/backfill tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
