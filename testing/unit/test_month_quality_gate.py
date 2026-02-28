"""
T8.14 — Tests unitaris per quality gate mensual (0-network).

Cobertura:
  1. test_acceptable_month:
     parquet 15,000 rows, flat=0%, completeness≈0.8 → is_acceptable=True
  2. test_too_few_rows:
     parquet 500 rows → is_acceptable=False, reason conté "num_rows"
  3. test_high_flat_ratio:
     parquet amb flat_ratio=0.10 → is_acceptable=False, reason conté "flat_ratio"
  4. test_low_completeness:
     4,000 rows, expected≈40,000 → completeness≈0.10 → is_acceptable=False
  5. test_sync_manager_quality_gate_retry:
     SyncManager + fetch_fn que primer retorna 100 rows (falla gate),
     segon intent retorna 15,000 rows (passa gate) → job.done=1, job.failed=0
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
    Parquet 500 rows → is_acceptable=False, reason conté 'num_rows'.
    """
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
    Parquet amb 10% flat bars → is_acceptable=False, reason conté 'flat_ratio'.
    12,000 rows: 1,200 flat (O=H=L=C), 10,800 normals.
    """
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
    4,000 rows, expected≈33,120 (2020-01) → completeness≈0.12 → is_acceptable=False.
    """
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


def test_sync_manager_quality_gate_retry():
    """
    T8.14: SyncManager + fetch_fn que primer retorna 100 rows (falla gate MIN_ROWS=10,000),
    segon intent retorna 15,000 rows (passa gate) → job.done=1, job.failed=0.

    Verifica que el quality gate es integra correctament al loop de retry del sync_manager.
    """
    import asyncio
    import os
    import tempfile

    # Configurar thresholds via env vars (per a tots els processos)
    os.environ["MIN_ROWS_MONTH_1M"] = "10000"
    os.environ["MAX_FLAT_RATIO_GATE"] = "0.05"
    os.environ["MIN_COMPLETENESS_1M"] = "0.30"

    try:
        async def _run():
            with tempfile.TemporaryDirectory() as tmpdir:
                attempt_count = [0]

                def fetch_fn(symbol, year, month):
                    attempt_count[0] += 1
                    if attempt_count[0] == 1:
                        # Primer intent: 100 rows → falla MIN_ROWS=10,000
                        return [
                            _make_fake_candle(year, month, i)
                            for i in range(100)
                        ]
                    else:
                        # Segon intent: 15,000 rows → passa gate (amb MIN_COMPLETENESS=0.30)
                        return [
                            _make_fake_candle(year, month, i)
                            for i in range(15000)
                        ]

                from application.data.sync_manager import SyncManager
                manager = SyncManager(
                    datafiles_root=tmpdir,
                    workers=2,
                    fetch_override=fetch_fn,
                )

                job, _ = await manager.start_job("EURUSD", "1m", "2020-01-01", "2020-01-31")
                deadline = asyncio.get_event_loop().time() + 30.0
                while asyncio.get_event_loop().time() < deadline:
                    await asyncio.sleep(0.1)
                    current = manager.get_job(job.job_id)
                    if current and current.status in ("DONE", "FAILED", "INTERRUPTED"):
                        break

                final = manager.get_job(job.job_id)

                assert final is not None
                assert final.status == "DONE", f"job status hauria de ser DONE, got {final.status}"
                assert final.done == 1, f"job.done hauria de ser 1 (segon intent OK), got {final.done}"
                assert final.failed == 0, f"job.failed hauria de ser 0, got {final.failed}"
                assert attempt_count[0] >= 2, f"fetch_fn hauria d'haver estat cridada ≥2 vegades, got {attempt_count[0]}"

                # Verificar que el parquet final té dades
                from infrastructure.storage.parquet_store import ParquetCandleStore
                store = ParquetCandleStore(root_path=tmpdir)
                assert store.has_month("EURUSD", 2020, 1), "El parquet final ha de tenir dades (ha_month=True)"

        asyncio.run(_run())

    finally:
        # Netejar env vars per no afectar altres tests
        for key in ("MIN_ROWS_MONTH_1M", "MAX_FLAT_RATIO_GATE", "MIN_COMPLETENESS_1M"):
            os.environ.pop(key, None)
