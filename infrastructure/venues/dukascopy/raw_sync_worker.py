"""
BS.T9.07 — Worker de sync RAW BI5 M1 BID: resumible, no-corruptible, background.

Jobs persistits a {datafiles_root}/jobs/raw_sync/{job_id}.json.
Lock: {datafiles_root}/jobs/raw_sync.lock — un sol worker alhora.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from application.data.dukascopy_bi5 import build_m1_url, _download_bytes
from foundation.config.constants import DEFAULT_RAW_SYNC_SYMBOLS, RAW_SYNC_SYMBOLS_ENV
from foundation.logging import get_logger
from infrastructure.venues.dukascopy.raw_bi5_store import RawBi5M1Store

logger = get_logger(__name__)

JOBS_SUBDIR = "jobs/raw_sync"
LOCK_FILENAME = "raw_sync.lock"
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0
DEFAULT_BACKOFF_MAX = 30.0
DEFAULT_CONCURRENCY = 4
# Estats de job (policy; no hardcode a la lògica)
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


def get_supported_symbols() -> List[str]:
    """
    Retorna la llista de símbols suportats per RAW sync.
    Font: variable d'entorn SYMBOLS (ex: "EURUSD,XAUUSD") o default EURUSD,XAUUSD.
    """
    raw = os.getenv(RAW_SYNC_SYMBOLS_ENV, DEFAULT_RAW_SYNC_SYMBOLS)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _days_in_range(from_d: date, to_d: date) -> List[date]:
    """Rang [from_d, to_d) (to_d exclusiu), un dia = from_date, to_date = day+1."""
    out = []
    cur = from_d
    while cur < to_d:
        out.append(cur)
        cur += timedelta(days=1)
    return out


@dataclass
class RawSyncJob:
    job_id: str
    status: str  # queued | running | done | failed
    symbols: List[str]
    from_date: str
    to_date: str
    force: bool
    days_total: int = 0
    days_done: int = 0
    days_skipped: int = 0
    days_failed: int = 0
    last_error: Optional[str] = None
    failed_day_last: Optional[str] = None  # últim dia fallit (YYYY-MM-DD) per retry sense last_error
    started_at: str = ""
    updated_at: str = ""
    # Per resume: últim dia completat per símbol (opcional, es pot inferir de watermark)
    progress_by_symbol: dict = field(default_factory=dict)  # symbol -> last_day_iso

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RawSyncJob":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def snapshot(self) -> dict:
        total = self.days_total or 1
        pct = round(100.0 * (self.days_done + self.days_skipped + self.days_failed) / total, 1)
        return {
            "job_id": self.job_id,
            "status": self.status,
            "symbols": self.symbols,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "force": self.force,
            "days_total": self.days_total,
            "days_done": self.days_done,
            "days_skipped": self.days_skipped,
            "days_failed": self.days_failed,
            "progress_pct": pct,
            "last_error": self.last_error,
            "failed_day_last": self.failed_day_last,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }


class RawSyncWorker:
    """
    Executa sync RAW BI5 per un job: planifica dies, descarrega amb retries, escriu atòmic.
    Resume: carrega job, continua des del progress.
    """

    def __init__(
        self,
        datafiles_root: str,
        concurrency: int = DEFAULT_CONCURRENCY,
        retries: int = DEFAULT_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_max: float = DEFAULT_BACKOFF_MAX,
    ):
        self._root = Path(datafiles_root)
        self._jobs_dir = self._root / JOBS_SUBDIR
        self._lock_path = self._root / "jobs" / LOCK_FILENAME
        self._store = RawBi5M1Store(str(self._root))
        self._concurrency = max(1, concurrency)
        self._retries = retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _acquire_lock(self) -> bool:
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._lock_path.exists():
            try:
                content = self._lock_path.read_text().strip()
                # Format: pid ou job_id per debug
                return False
            except Exception:
                pass
        try:
            self._lock_path.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except OSError:
            return False

    def _release_lock(self) -> None:
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except OSError:
            pass

    def _persist_job(self, job: RawSyncJob) -> None:
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        p = self._job_path(job.job_id)
        tmp = p.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        tmp.rename(p)

    def get_job(self, job_id: str) -> Optional[RawSyncJob]:
        p = self._job_path(job_id)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return RawSyncJob.from_dict(json.load(f))
        except Exception:
            return None

    def list_jobs(self, limit: int = 20) -> List[RawSyncJob]:
        if not self._jobs_dir.exists():
            return []
        jobs = []
        for f in sorted(self._jobs_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.name.endswith(".tmp.json"):
                continue
            try:
                with open(f, encoding="utf-8") as fp:
                    jobs.append(RawSyncJob.from_dict(json.load(fp)))
            except Exception:
                continue
            if len(jobs) >= limit:
                break
        return jobs

    def create_job(
        self,
        symbols: List[str],
        from_date: str,
        to_date: str,
        force: bool = False,
    ) -> RawSyncJob:
        from_d = date.fromisoformat(from_date)
        to_d = date.fromisoformat(to_date)
        total = 0
        for _ in symbols:
            total += len(_days_in_range(from_d, to_d))
        job_id = uuid.uuid4().hex[:12]
        job = RawSyncJob(
            job_id=job_id,
            status=JOB_STATUS_QUEUED,
            symbols=symbols,
            from_date=from_date,
            to_date=to_date,
            force=force,
            days_total=total,
            started_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._persist_job(job)
        return job

    def _download_day(self, symbol: str, year: int, month: int, day: int) -> Optional[bytes]:
        url = build_m1_url(symbol, year, month, day)
        for attempt in range(self._retries):
            try:
                data = _download_bytes(url)
                return data
            except Exception as e:
                logger.warning(
                    "DOWNLOAD: symbol=%s day=%d-%02d-%02d attempt=%d error=%s",
                    symbol, year, month, day, attempt + 1, e,
                )
                if attempt < self._retries - 1:
                    wait = min(self._backoff_base * (2 ** attempt), self._backoff_max)
                    time.sleep(wait)
        return None

    async def run_job(self, job_id: str) -> RawSyncJob:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status not in (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING):
            return job

        if not self._acquire_lock():
            job.last_error = "Another raw sync job is running (lock held)"
            job.status = JOB_STATUS_FAILED
            job.updated_at = _now_iso()
            self._persist_job(job)
            return job

        job.status = JOB_STATUS_RUNNING
        job.updated_at = _now_iso()
        self._persist_job(job)

        try:
            from_d = date.fromisoformat(job.from_date)
            to_d = date.fromisoformat(job.to_date)
            done = job.days_done
            skipped = job.days_skipped
            failed = job.days_failed

            for symbol in job.symbols:
                sym = symbol.strip().upper()
                for d in _days_in_range(from_d, to_d):
                    if job.status == JOB_STATUS_FAILED:
                        break
                    y, m, day = d.year, d.month, d.day
                    if not self._store.exists_day(sym, y, m, day) or job.force:
                        raw = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda sy=sym, yr=y, mo=m, da=day: self._download_day(sy, yr, mo, da),
                        )
                        if raw is None:
                            failed += 1
                            job.last_error = f"Download failed: {sym} {d.isoformat()}"
                            job.failed_day_last = d.isoformat()
                            job.days_failed = failed
                            job.updated_at = _now_iso()
                            self._persist_job(job)
                            continue
                        written = self._store.write_day_atomic(
                            sym, y, m, day, raw,
                            build_m1_url(sym, y, m, day),
                            force=job.force,
                        )
                        if written is not None:
                            done += 1
                            self._store.write_watermark(
                                sym,
                                last_complete_day=d.isoformat(),
                                last_attempt_day=d.isoformat(),
                                last_success_at=_now_iso(),
                                last_error=None,
                            )
                            logger.info("RAW_SYNC: job_id=%s symbol=%s day=%s", job_id, sym, d.isoformat())
                        else:
                            skipped += 1
                    else:
                        skipped += 1
                    job.days_done = done
                    job.days_skipped = skipped
                    job.days_failed = failed
                    job.updated_at = _now_iso()
                    self._persist_job(job)

            job.status = JOB_STATUS_DONE
            job.last_error = None
        except Exception as e:
            job.status = JOB_STATUS_FAILED
            job.last_error = str(e)
            logger.exception("RAW_SYNC job %s failed: %s", job_id, e)
        finally:
            job.updated_at = _now_iso()
            self._persist_job(job)
            self._release_lock()

        return job
