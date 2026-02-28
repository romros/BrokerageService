"""
T8.14/T8.16 — Tests unitaris per quality gate mensual (0-network).

Cobertura:
  1. test_acceptable_month:
     parquet 15,000 rows, flat=0% → is_acceptable=True (mode ingest)
  2. test_too_few_rows (integrity):
     QUALITY_MODE=integrity + 500 rows → is_acceptable=False, reason conté "num_rows"
  3. test_high_flat_ratio (integrity):
     QUALITY_MODE=integrity + flat_ratio=0.10 → is_acceptable=False, reason conté "flat_ratio"
  4. test_low_completeness (integrity):
     QUALITY_MODE=integrity + 4,000 rows → is_acceptable=False, reason conté "completeness"
  5. test_sync_manager_quality_gate_retry:
     Mode ingest (default) — fetch retorna pocs rows → is_acceptable=True (no retry)
     → job.done=1, job.failed=0
  6. test_ingest_mode_accepts_low_rows (T8.16):
     QUALITY_MODE=ingest (default) + 500 rows → is_acceptable=True (no rebutja baixa cobertura)
  7. test_integrity_mode_suspect (T8.16):
     QUALITY_MODE=integrity + rows sota threshold → is_suspect=True, suspect_reason no buit
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from application.data.month_quality import (
    MonthQualityStats,
    compute_month_stats,
    expected_minutes_1m,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_candle(year: int, month: int, offset_minutes: int = 0,
                      flat: bool = False):
    from domain.models import Candle
    base = int(datetime(year, month, 1, 10, 0, tzinfo=timezone.utc).timestamp())
    ts = datetime.fromtimestamp(base + offset_minutes * 60, tz=timezone.utc)
    if flat:
        return Candle(
            symbol="EURUSD", timestamp=ts,
            open=1.1000, high=1.1000, low=1.1000, close=1.1000, volume=0.0,
            is_closed=True,
        )
    return Candle(
        symbol="EURUSD", timestamp=ts,
        open=1.1000, high=1.1010, low=1.0990, close=1.1005, volume=100.0,
        is_closed=True,
    )


def _write_parquet_with_candles(path: Path, candles: list) -> None:
    """Escriu un parquet de candles usant el ParquetCandleStore."""
    from infrastructure.storage.parquet_store import ParquetCandleStore
    # Afegim les candles amb timestamps únics
    store = ParquetCandleStore(root_path=str(path.parent.parent.parent.parent.parent.parent))
    # Directament amb pandas per control màxim
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = []
    for c in candles:
        rows.append({
            "ts": int(c.timestamp.timestamp()),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        })
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(str(path), index=False)


def _write_parquet_direct(path: Path, rows: list[dict]) -> None:
    """Escriu un parquet directament amb pandas."""
    import pandas as pd
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(str(path), index=False)


# ---------------------------------------------------------------------------
# Tests month_quality.py
# ---------------------------------------------------------------------------

def test_acceptable_month(tmp_path, monkeypatch):
    """
    Parquet 15,000 rows, flat=0%, completeness≈0.8 → is_acceptable=True.
    Any=2020, mes=6: ~22 dies laborables × 1440 = ~31,680 min esperats.
    15,000/31,680 ≈ 0.47 → just per sota MIN_COMPLETENESS=0.50.
    Usem any=2020, mes=1 (23 laborables × 1440 = 33,120): 15,000/33,120 ≈ 0.45.
    Per garantir pass: usem MIN_COMPLETENESS=0.40 via monkeypatch.
    """
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "10000")
    monkeypatch.setenv("MAX_FLAT_RATIO_GATE", "0.05")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.40")

    # Escriure parquet: 15,000 candles normals (no flat)
    parquet_path = tmp_path / "data.parquet"
    n = 15000
    rows = [
        {"ts": 1577836800 + i * 60, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0}
        for i in range(n)
    ]
    _write_parquet_direct(parquet_path, rows)

    stats = compute_month_stats(parquet_path, year=2020, month=1)

    assert isinstance(stats, MonthQualityStats)
    assert stats.num_rows == n
    assert stats.flat_bars == 0
    assert stats.flat_bars_ratio == 0.0
    assert stats.is_acceptable, f"Hauria de passar el gate, reason={stats.reason}"
    assert stats.reason == ""


def test_too_few_rows(tmp_path, monkeypatch):
    """
    QUALITY_MODE=integrity + Parquet 500 rows → is_acceptable=False, reason conté 'num_rows'.
    """
    monkeypatch.setenv("QUALITY_MODE", "integrity")
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "10000")
    monkeypatch.setenv("MAX_FLAT_RATIO_GATE", "0.05")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.50")

    parquet_path = tmp_path / "data.parquet"
    n = 500
    rows = [
        {"ts": 1577836800 + i * 60, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0}
        for i in range(n)
    ]
    _write_parquet_direct(parquet_path, rows)

    stats = compute_month_stats(parquet_path, year=2020, month=1)

    assert not stats.is_acceptable, "500 rows ha de fallar el gate"
    assert "num_rows" in stats.reason, f"reason ha de mencionar num_rows: {stats.reason}"
    assert stats.num_rows == n


def test_high_flat_ratio(tmp_path, monkeypatch):
    """
    QUALITY_MODE=integrity + Parquet amb 10% flat bars → is_acceptable=False, reason conté 'flat_ratio'.
    12,000 rows: 1,200 flat (O=H=L=C), 10,800 normals.
    """
    monkeypatch.setenv("QUALITY_MODE", "integrity")
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "10000")
    monkeypatch.setenv("MAX_FLAT_RATIO_GATE", "0.05")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.30")

    parquet_path = tmp_path / "data.parquet"
    n_total = 12000
    n_flat = 1200  # 10% flat → > 5% threshold

    rows = []
    for i in range(n_total):
        if i < n_flat:
            # Flat bar: O=H=L=C
            rows.append({"ts": 1577836800 + i * 60,
                         "open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1, "volume": 0.0})
        else:
            rows.append({"ts": 1577836800 + i * 60,
                         "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0})
    _write_parquet_direct(parquet_path, rows)

    stats = compute_month_stats(parquet_path, year=2020, month=1)

    assert not stats.is_acceptable, f"10% flat ha de fallar el gate, stats={stats}"
    assert "flat_ratio" in stats.reason, f"reason ha de mencionar flat_ratio: {stats.reason}"
    assert stats.flat_bars == n_flat
    assert round(stats.flat_bars_ratio, 2) == 0.10


def test_low_completeness(tmp_path, monkeypatch):
    """
    QUALITY_MODE=integrity + 4,000 rows, expected≈33,120 (2020-01) → completeness≈0.12 → is_acceptable=False.
    """
    monkeypatch.setenv("QUALITY_MODE", "integrity")
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "1000")   # baixem min_rows per aïllar completeness
    monkeypatch.setenv("MAX_FLAT_RATIO_GATE", "0.05")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.50")

    parquet_path = tmp_path / "data.parquet"
    n = 4000
    rows = [
        {"ts": 1577836800 + i * 60, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0}
        for i in range(n)
    ]
    _write_parquet_direct(parquet_path, rows)

    # 2020-01: 23 laborables × 1440 = 33,120 min esperats
    expected = expected_minutes_1m(2020, 1)
    stats = compute_month_stats(parquet_path, year=2020, month=1)

    assert expected == 33120, f"expected_minutes_1m(2020,1) hauria de ser 33120, got {expected}"
    assert not stats.is_acceptable, f"completeness baixa ha de fallar el gate, stats={stats}"
    assert "completeness" in stats.reason, f"reason ha de mencionar completeness: {stats.reason}"
    assert stats.completeness_ratio < 0.20


def test_sync_manager_ingest_mode_no_retry():
    """
    T8.16: Mode ingest (default) — fetch retorna 100 rows → gate accepta sense retry.
    job.done=1, job.failed=0. Fetch cridat exactament 1 vegada.
    """
    import asyncio
    import os
    import tempfile

    os.environ.pop("QUALITY_MODE", None)  # ingest és el default

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            attempt_count = [0]

            def fetch_fn(symbol, year, month):
                attempt_count[0] += 1
                # 100 rows → en mode ingest s'accepta (rows > 0)
                return [_make_fake_candle(year, month, i) for i in range(100)]

            from application.data.sync_manager import SyncManager
            manager = SyncManager(datafiles_root=tmpdir, workers=2, fetch_override=fetch_fn)
            job, _ = await manager.start_job("EURUSD", "1m", "2020-01-01", "2020-01-31")
            deadline = asyncio.get_event_loop().time() + 30.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.1)
                current = manager.get_job(job.job_id)
                if current and current.status in ("DONE", "FAILED", "INTERRUPTED"):
                    break

            final = manager.get_job(job.job_id)
            assert final.status == "DONE", f"ingest: hauria de ser DONE, got {final.status}"
            assert final.done == 1, f"ingest: done=1 esperat, got {final.done}"
            assert final.failed == 0, f"ingest: failed=0 esperat, got {final.failed}"
            assert attempt_count[0] == 1, f"ingest: fetch cridat 1 cop, got {attempt_count[0]}"

            from infrastructure.storage.parquet_store import ParquetCandleStore
            store = ParquetCandleStore(root_path=tmpdir)
            assert store.has_month("EURUSD", 2020, 1), "parquet ha de tenir dades"

    asyncio.run(_run())


def test_ingest_mode_accepts_low_rows(tmp_path, monkeypatch):
    """
    T8.16: QUALITY_MODE=ingest (default) + 500 rows → is_acceptable=True.
    Verifica que el mode ingest no rebutja baixa cobertura.
    """
    monkeypatch.delenv("QUALITY_MODE", raising=False)  # ingest és el default
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "10000")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.50")

    parquet_path = tmp_path / "data.parquet"
    rows = [
        {"ts": 1577836800 + i * 60, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0}
        for i in range(500)
    ]
    _write_parquet_direct(parquet_path, rows)

    stats = compute_month_stats(parquet_path, year=2020, month=1)

    assert stats.is_acceptable, f"ingest: 500 rows ha de ser acceptable, reason={stats.reason}"
    assert stats.reason == "", f"ingest: reason ha de ser buit, got {stats.reason!r}"


def test_integrity_mode_suspect(tmp_path, monkeypatch):
    """
    T8.16: QUALITY_MODE=integrity + 5,000 rows (sota MIN_ROWS=10,000) →
    is_acceptable=False, is_suspect=True, suspect_reason no buit.
    """
    monkeypatch.setenv("QUALITY_MODE", "integrity")
    monkeypatch.setenv("MIN_ROWS_MONTH_1M", "10000")
    monkeypatch.setenv("MAX_FLAT_RATIO_GATE", "0.05")
    monkeypatch.setenv("MIN_COMPLETENESS_1M", "0.50")

    parquet_path = tmp_path / "data.parquet"
    rows = [
        {"ts": 1577836800 + i * 60, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 100.0}
        for i in range(5000)
    ]
    _write_parquet_direct(parquet_path, rows)

    stats = compute_month_stats(parquet_path, year=2020, month=1)

    # En mode integrity: is_acceptable=False per sota dels thresholds
    assert not stats.is_acceptable, f"integrity: 5000 rows hauria de fallar, stats={stats}"
    # I is_suspect=True (el motiu és informatiu)
    assert stats.is_suspect, f"integrity: hauria de ser suspect, stats={stats}"
    assert stats.suspect_reason != "", f"integrity: suspect_reason ha de tenir contingut"
