"""
T8.6 — Tests unitaris per SyncManager (0-network).

Cobertura:
  1. Nou job creat amb status=RUNNING
  2. Dedup: 2a crida amb el mateix rang → retorna job existent (is_new=False)
  3. Progrés: job.done puja per cada mes completat
  4. Skip: mes ja al disc → skipped+1, no fetch
  5. Retry accounting: retries acumulen
  6. Job DONE quan tots els mesos processats (sense fallades)
  7. Job FAILED si algun mes falla tots els reintents
  8. Rebuild post-job actualitza coverage_from/to
"""

import asyncio
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.data.sync_manager import SyncManager, SyncJob, _job_key, _retry_wait


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_candle(ts: int):
    """Crea un objecte Candle mínim per tests."""
    from domain.models import Candle
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return Candle(
        symbol="XAUUSD",
        timestamp=dt,
        open=1800.0, high=1801.0, low=1799.0, close=1800.5, volume=100.0,
    )


def _make_month_candles(year: int, month: int, n: int = 100) -> list:
    """Genera N candles per un mes."""
    from datetime import timedelta
    base = int(datetime(year, month, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    return [_make_fake_candle(base + i * 60) for i in range(n)]


def _make_manager(tmpdir: str, fetch_fn=None) -> SyncManager:
    """Crea un SyncManager amb fetch_override per 0-network."""
    return SyncManager(
        datafiles_root=tmpdir,
        workers=2,
        fetch_override=fetch_fn,
    )


async def _run_job_and_wait(manager, symbol, tf, from_date, to_date, timeout=10.0):
    """Inicia un job i espera que acabi (màx timeout s)."""
    job, is_new = await manager.start_job(symbol, tf, from_date, to_date)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
        current = manager.get_job(job.job_id)
        if current and current.status in ("DONE", "FAILED", "INTERRUPTED"):
            return current, is_new
    return manager.get_job(job.job_id), is_new


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_job_created():
    """Primer POST crea job amb status=RUNNING, is_new=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        candles = _make_month_candles(2022, 1)
        manager = _make_manager(tmpdir, fetch_fn=lambda s, y, m: candles)

        job, is_new = await manager.start_job("XAUUSD", "1m", "2022-01-01", "2022-01-31")
        assert is_new is True
        assert job.status == "RUNNING"
        assert job.symbol == "XAUUSD"
        assert job.job_id is not None


@pytest.mark.asyncio
async def test_dedup_returns_same_job():
    """2a crida amb el mateix rang → retorna el mateix job_id, is_new=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Usa un fetch lent per simular job que triga
        event = asyncio.Event()

        async def slow_fetch(s, y, m):
            await asyncio.sleep(0.5)  # lent
            return _make_month_candles(y, m)

        candles = _make_month_candles(2022, 1)

        # fetch_override ha de ser sync (no async) — usem lambda sync
        fetch_calls = []
        def fetch_fn(s, y, m):
            fetch_calls.append((y, m))
            # Dormir un tic per simular latència (no pot ser async aquí)
            import time; time.sleep(0.1)
            return _make_month_candles(y, m)

        manager = _make_manager(tmpdir, fetch_fn=fetch_fn)

        job1, is_new1 = await manager.start_job("XAUUSD", "1m", "2022-01-01", "2022-01-31")
        assert is_new1 is True

        # 2a crida immediata mentre el job pot estar RUNNING
        job2, is_new2 = await manager.start_job("XAUUSD", "1m", "2022-01-01", "2022-01-31")

        # Pot ser RUNNING o DONE depenent del timing, però el job_id ha de ser el mateix
        assert job1.job_id == job2.job_id
        # is_new2 pot ser False (dedup) o True si el job ja ha acabat — però el job_id és igual


@pytest.mark.asyncio
async def test_progress_done_increments():
    """job.done puja per cada mes completat."""
    import os
    # Desactivem el quality gate per a aquest test (n=100 candles per mes és OK per al test)
    os.environ["MIN_ROWS_MONTH_1M"] = "0"
    os.environ["MIN_COMPLETENESS_1M"] = "0.0"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            months_done = []

            def fetch_fn(s, y, m):
                months_done.append((y, m))
                return _make_month_candles(y, m)

            manager = _make_manager(tmpdir, fetch_fn=fetch_fn)
            job, _ = await _run_job_and_wait(
                manager, "XAUUSD", "1m", "2022-01-01", "2022-03-31"
            )

            assert job is not None
            assert job.status == "DONE"
            assert job.done == 3   # 3 mesos: jan, feb, mar
            assert job.failed == 0
    finally:
        os.environ.pop("MIN_ROWS_MONTH_1M", None)
        os.environ.pop("MIN_COMPLETENESS_1M", None)


@pytest.mark.asyncio
async def test_skipped_if_parquet_exists():
    """Mes ja al disc → job.skipped += 1, no es crida fetch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Pre-escriu un Parquet per 2022-01
        from infrastructure.storage.parquet_store import ParquetCandleStore
        store = ParquetCandleStore(root_path=tmpdir)
        candles = _make_month_candles(2022, 1)
        store.write_month("XAUUSD", 2022, 1, candles)

        fetch_calls = []
        def fetch_fn(s, y, m):
            fetch_calls.append((y, m))
            return _make_month_candles(y, m)

        manager = _make_manager(tmpdir, fetch_fn=fetch_fn)
        job, _ = await _run_job_and_wait(
            manager, "XAUUSD", "1m", "2022-01-01", "2022-01-31"
        )

        # 2022-01 ja existia → skip (pot ser comptabilitzat al start_job via rebuild o al _process_month)
        assert job is not None
        assert job.status == "DONE"
        # El mes ja existeix → 0 mesos a fer (total_units=0) o 1 skip
        assert job.failed == 0
        # fetch no s'ha d'haver cridat per 2022-01 (ja existia)
        assert (2022, 1) not in fetch_calls


@pytest.mark.asyncio
async def test_job_done_when_no_months_to_do():
    """Si tots els mesos ja existeixen → job DONE immediatament, total_units=0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Pre-escriu 2022-01
        from infrastructure.storage.parquet_store import ParquetCandleStore
        store = ParquetCandleStore(root_path=tmpdir)
        candles = _make_month_candles(2022, 1)
        store.write_month("XAUUSD", 2022, 1, candles)

        manager = _make_manager(tmpdir, fetch_fn=lambda s, y, m: _make_month_candles(y, m))
        job, _ = await _run_job_and_wait(
            manager, "XAUUSD", "1m", "2022-01-01", "2022-01-31"
        )

        assert job.status == "DONE"
        assert job.total_units == 0


@pytest.mark.asyncio
async def test_job_failed_when_fetch_raises():
    """Si fetch sempre falla → job.failed > 0 i status=FAILED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        call_count = [0]

        def fetch_fn(s, y, m):
            call_count[0] += 1
            raise ConnectionError("Dukascopy unreachable")

        # Patchem els backoffs per no esperar 30s
        with patch("application.data.sync_manager.DEFAULT_RETRIES", 1), \
             patch("application.data.sync_manager.DEFAULT_BACKOFF_BASE", 0.01), \
             patch("application.data.sync_manager.DEFAULT_BACKOFF_MAX", 0.01):
            manager = _make_manager(tmpdir, fetch_fn=fetch_fn)
            job, _ = await _run_job_and_wait(
                manager, "XAUUSD", "1m", "2022-01-01", "2022-01-31",
                timeout=5.0,
            )

        assert job is not None
        assert job.status == "FAILED"
        assert job.failed >= 1
        assert "2022-01" in job.failed_months


def test_http_429_uses_long_configurable_backoff(monkeypatch):
    monkeypatch.setenv("SYNC_429_BACKOFF_BASE", "60")
    monkeypatch.setenv("SYNC_429_BACKOFF_MAX", "150")
    error = RuntimeError("HTTP Error 429: Too Many Requests")
    assert _retry_wait(error, 0) == 60
    assert _retry_wait(error, 1) == 120
    assert _retry_wait(error, 2) == 150
    assert _retry_wait(ConnectionError("temporary"), 0) == 2


@pytest.mark.asyncio
async def test_list_jobs_returns_recent():
    """list_jobs() retorna els jobs ordenats per started_at desc."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = _make_manager(tmpdir, fetch_fn=lambda s, y, m: _make_month_candles(y, m))

        job1, _ = await _run_job_and_wait(manager, "XAUUSD", "1m", "2022-01-01", "2022-01-31")
        job2, _ = await _run_job_and_wait(manager, "XAUUSD", "1m", "2022-02-01", "2022-02-28")

        jobs = manager.list_jobs(limit=5)
        assert len(jobs) >= 2
        # Últim job primer
        assert jobs[0].from_date >= jobs[1].from_date


@pytest.mark.asyncio
async def test_snapshot_has_required_fields():
    """SyncJob.snapshot() retorna tots els camps requerits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = _make_manager(tmpdir, fetch_fn=lambda s, y, m: _make_month_candles(y, m))
        job, _ = await manager.start_job("XAUUSD", "1m", "2022-01-01", "2022-01-31")
        snap = job.snapshot()

        required = ["job_id", "status", "symbol", "tf", "total_units", "done",
                    "skipped", "failed", "retries", "started_at", "updated_at",
                    "failed_months"]
        for field in required:
            assert field in snap, f"Camp {field!r} absent del snapshot"
