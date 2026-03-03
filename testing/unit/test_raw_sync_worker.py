"""
BS.T9.07 — Tests unitaris per RawSyncWorker (0-network).

- get_supported_symbols (env/default)
- create_job, get_job, list_jobs, snapshot
- persist job → reload
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.config.constants import DEFAULT_RAW_SYNC_SYMBOLS, RAW_SYNC_SYMBOLS_ENV
from infrastructure.venues.dukascopy.raw_sync_worker import (
    JOB_STATUS_QUEUED,
    RawSyncJob,
    RawSyncWorker,
    get_supported_symbols,
)


def test_get_supported_symbols_default():
    if RAW_SYNC_SYMBOLS_ENV in os.environ:
        del os.environ[RAW_SYNC_SYMBOLS_ENV]
    syms = get_supported_symbols()
    assert "EURUSD" in syms
    assert "XAUUSD" in syms
    assert all(s == s.upper() for s in syms)


def test_get_supported_symbols_env():
    os.environ[RAW_SYNC_SYMBOLS_ENV] = "EURUSD, GBPUSD , XAUUSD"
    try:
        syms = get_supported_symbols()
        assert syms == ["EURUSD", "GBPUSD", "XAUUSD"]
    finally:
        if RAW_SYNC_SYMBOLS_ENV in os.environ:
            del os.environ[RAW_SYNC_SYMBOLS_ENV]


def test_create_job_get_job_list_jobs(tmp_path):
    worker = RawSyncWorker(str(tmp_path))
    job = worker.create_job(["EURUSD"], "2024-01-01", "2024-01-05", force=False)
    assert job.job_id
    assert job.status == JOB_STATUS_QUEUED
    assert job.symbols == ["EURUSD"]
    assert job.from_date == "2024-01-01"
    assert job.to_date == "2024-01-05"
    assert job.days_total == 5  # 5 days
    loaded = worker.get_job(job.job_id)
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.days_total == 5
    listed = worker.list_jobs(limit=5)
    assert len(listed) >= 1
    assert any(j.job_id == job.job_id for j in listed)
    snap = job.snapshot()
    assert "job_id" in snap
    assert snap["days_total"] == 5
    assert "progress_pct" in snap


def test_job_snapshot_has_required_fields(tmp_path):
    worker = RawSyncWorker(str(tmp_path))
    job = worker.create_job(["XAUUSD"], "2024-01-01", "2024-01-02", force=False)
    snap = job.snapshot()
    for key in ("job_id", "status", "symbols", "from_date", "to_date", "days_total", "days_done",
                "days_skipped", "days_failed", "progress_pct", "last_error", "started_at", "updated_at"):
        assert key in snap, f"missing {key}"


def main():
    import tempfile
    tests = [
        test_get_supported_symbols_default,
        test_get_supported_symbols_env,
        test_create_job_get_job_list_jobs,
        test_job_snapshot_has_required_fields,
    ]
    for t in tests:
        if t.__name__ == "test_create_job_get_job_list_jobs" or t.__name__ == "test_job_snapshot_has_required_fields":
            with tempfile.TemporaryDirectory() as tmp:
                t(Path(tmp))
        else:
            t()
        print(f"OK {t.__name__}")
    print("OK test_raw_sync_worker (all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
