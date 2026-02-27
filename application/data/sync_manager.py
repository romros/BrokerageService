"""
T8.6 — SyncManager: sync concurrent per mesos amb job tracking.

Característiques:
- N workers asyncio (default 4, configurable via SYNC_WORKERS env)
- Job tracking: job_id, status, progrés real (done/skipped/failed/retries)
- Reentrància: 2a crida amb el mateix rang → retorna job existent si RUNNING
- Persistència lleugera: _coverage/sync_jobs.json (màx 20 jobs)
- Locks per mes: evita doble escriptura concurrent
- Al startup: jobs RUNNING → INTERRUPTED (client ha de re-lançar)

Ús:
    manager = SyncManager(datafiles_root="/datafiles")
    job = await manager.start_job("XAUUSD", "1m", "2022-01-01", "2022-12-31")
    # job.job_id per fer poll
    snapshot = manager.get_job(job.job_id)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

COVERAGE_SUBDIR = "_coverage"
JOBS_FILENAME = "sync_jobs.json"
MAX_JOBS_PERSISTED = 20
DEFAULT_WORKERS = 4
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0
DEFAULT_BACKOFF_MAX = 30.0


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

@dataclass
class SyncJob:
    job_id: str
    job_key: str
    symbol: str
    tf: str
    from_date: str          # YYYY-MM-DD
    to_date: str            # YYYY-MM-DD
    status: str             # RUNNING | DONE | FAILED | INTERRUPTED
    total_units: int        # mesos planificats (a descarregar)
    done: int = 0
    skipped: int = 0
    failed: int = 0
    retries: int = 0        # total retries acumulats
    started_at: str = ""
    updated_at: str = ""
    eta_s: Optional[float] = None
    failed_months: List[str] = field(default_factory=list)
    coverage_from: Optional[str] = None
    coverage_to: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SyncJob":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def snapshot(self) -> dict:
        """Retorna un snapshot JSON-serialitzable del job."""
        total = self.total_units
        elapsed = 0.0
        if self.started_at:
            try:
                started = datetime.fromisoformat(self.started_at)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            except Exception:
                pass
        eta = None
        if self.done > 0 and total > 0 and (self.done + self.failed) < total:
            rate = self.done / max(elapsed, 1)
            remaining = total - self.done - self.skipped - self.failed
            eta = round(remaining / max(rate, 0.001))
        return {
            "job_id": self.job_id,
            "status": self.status,
            "symbol": self.symbol,
            "tf": self.tf,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "total_units": total,
            "done": self.done,
            "skipped": self.skipped,
            "failed": self.failed,
            "retries": self.retries,
            "eta_s": eta,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "coverage_from": self.coverage_from,
            "coverage_to": self.coverage_to,
            "failed_months": self.failed_months,
        }


# ---------------------------------------------------------------------------
# SyncManager
# ---------------------------------------------------------------------------

def _job_key(symbol: str, tf: str, from_date: str, to_date: str) -> str:
    raw = f"{symbol.upper()}:{tf}:{from_date}:{to_date}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _months_in_range(from_d: date, to_d: date) -> list[tuple[int, int]]:
    months = []
    y, m = from_d.year, from_d.month
    while (y, m) <= (to_d.year, to_d.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


class SyncManager:
    """
    Gestor de jobs de sync concurrent.

    Singleton per app — inicialitzat al lifespan i injectat via app.state.sync_manager.
    """

    def __init__(
        self,
        datafiles_root: str,
        workers: Optional[int] = None,
        fetch_override: Optional[Callable] = None,  # per tests 0-network
    ):
        self._datafiles_root = datafiles_root
        self._workers = workers or int(os.getenv("SYNC_WORKERS", str(DEFAULT_WORKERS)))
        self._fetch_override = fetch_override  # callable(symbol, year, month) → list[Candle] | None

        self._jobs: dict[str, SyncJob] = {}           # job_id → SyncJob
        self._jobs_by_key: dict[str, str] = {}        # job_key → job_id
        self._month_locks: dict[tuple, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()            # protegeix _jobs i _jobs_by_key

        self._jobs_path = Path(datafiles_root) / "historical_parquet" / COVERAGE_SUBDIR / JOBS_FILENAME

        self._load_jobs()

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    async def start_job(
        self,
        symbol: str,
        tf: str,
        from_date: str,
        to_date: str,
    ) -> tuple[SyncJob, bool]:
        """
        Inicia un nou job o retorna l'existent si ja RUNNING.

        Returns:
            (job, is_new): job=snapshot actual, is_new=True si s'ha creat ara
        """
        sym = symbol.upper()
        key = _job_key(sym, tf, from_date, to_date)

        async with self._global_lock:
            # Reentrança: retorna job existent si RUNNING
            if key in self._jobs_by_key:
                existing_id = self._jobs_by_key[key]
                existing = self._jobs.get(existing_id)
                if existing and existing.status == "RUNNING":
                    logger.info("sync_manager REUSE job_id=%s symbol=%s", existing_id, sym)
                    return existing, False

            # Nou job: calcula mesos faltants via rebuild
            from application.data.rebuild_coverage import rebuild_coverage_index
            rebuild = await asyncio.get_event_loop().run_in_executor(
                None, rebuild_coverage_index, self._datafiles_root, sym, tf
            )

            from_d = date.fromisoformat(from_date)
            to_d = date.fromisoformat(to_date)
            all_months = _months_in_range(from_d, to_d)

            done_set = {(m.year, m.month) for m in rebuild.months if m.status == "done"}
            months_to_do = [(y, mo) for y, mo in all_months if (y, mo) not in done_set]
            months_skip = len(all_months) - len(months_to_do)

            job_id = uuid.uuid4().hex[:8]
            now = _now_iso()
            job = SyncJob(
                job_id=job_id,
                job_key=key,
                symbol=sym,
                tf=tf,
                from_date=from_date,
                to_date=to_date,
                status="RUNNING",
                total_units=len(months_to_do),
                skipped=months_skip,
                started_at=now,
                updated_at=now,
                coverage_from=rebuild.coverage_from,
                coverage_to=rebuild.coverage_to,
            )

            self._jobs[job_id] = job
            self._jobs_by_key[key] = job_id
            self._persist_jobs()

        # Llança el job en background (no bloqueja)
        asyncio.create_task(self._run_job(job, months_to_do))
        logger.info(
            "sync_manager START job_id=%s symbol=%s units=%d skipped=%d workers=%d",
            job_id, sym, len(months_to_do), months_skip, self._workers,
        )
        return job, True

    def get_job(self, job_id: str) -> Optional[SyncJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 10) -> list[SyncJob]:
        """Retorna els darrers N jobs ordenats per started_at desc."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
        return jobs[:limit]

    # ---------------------------------------------------------------------------
    # Internal: runner
    # ---------------------------------------------------------------------------

    async def _run_job(self, job: SyncJob, months_to_do: list[tuple[int, int]]) -> None:
        """Executa el job amb N workers asyncio."""
        if not months_to_do:
            job.status = "DONE"
            job.updated_at = _now_iso()
            self._persist_jobs()
            logger.info("sync_manager DONE job_id=%s (nothing to do)", job.job_id)
            return

        queue: asyncio.Queue = asyncio.Queue()
        for ym in months_to_do:
            await queue.put(ym)

        async def worker():
            while True:
                try:
                    year, month = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await self._process_month(job, year, month)
                except Exception as e:
                    logger.error("sync_manager worker error %s %d-%02d: %s", job.symbol, year, month, e)
                    async with self._global_lock:
                        job.failed += 1
                        job.failed_months.append(f"{year:04d}-{month:02d}")
                        job.updated_at = _now_iso()
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(self._workers, len(months_to_do)))]
        await asyncio.gather(*workers)

        # Rebuild final per actualitzar coverage
        try:
            from application.data.rebuild_coverage import rebuild_coverage_index
            rebuild = await asyncio.get_event_loop().run_in_executor(
                None, rebuild_coverage_index, self._datafiles_root, job.symbol, job.tf
            )
            job.coverage_from = rebuild.coverage_from
            job.coverage_to = rebuild.coverage_to
        except Exception as e:
            logger.warning("sync_manager post-rebuild error: %s", e)

        job.status = "DONE" if job.failed == 0 else "FAILED"
        job.updated_at = _now_iso()
        self._persist_jobs()
        logger.info(
            "sync_manager FINISHED job_id=%s status=%s done=%d skipped=%d failed=%d retries=%d",
            job.job_id, job.status, job.done, job.skipped, job.failed, job.retries,
        )

    async def _process_month(self, job: SyncJob, year: int, month: int) -> None:
        """
        Processa un mes: check disc → skip o fetch+write.
        Lock per mes evita doble escriptura concurrent.
        """
        lock = self._get_month_lock(job.symbol, job.tf, year, month)
        async with lock:
            from infrastructure.storage.parquet_store import ParquetCandleStore
            store = ParquetCandleStore(root_path=self._datafiles_root)

            # Skip si ja existeix al disc (Parquet = source of truth)
            if store.has_month(job.symbol, year, month):
                async with self._global_lock:
                    job.skipped += 1
                    job.updated_at = _now_iso()
                logger.debug("sync_manager SKIP %s %d-%02d (parquet exists)", job.symbol, year, month)
                return

            # Fetch amb retry + backoff
            from datetime import datetime as _dt
            month_start = _dt(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
            if month == 12:
                month_end = _dt(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            else:
                month_end = _dt(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)

            candles = None
            retries_used = 0
            for attempt in range(DEFAULT_RETRIES + 1):
                try:
                    if self._fetch_override is not None:
                        raw = self._fetch_override(job.symbol, year, month)
                        candles = raw
                    else:
                        from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider
                        provider = DukascopyBackfillProvider(cache_root=self._datafiles_root)
                        candles = await provider.fetch_ohlcv(job.symbol, month_start, month_end)
                    break
                except Exception as e:
                    retries_used = attempt + 1
                    if attempt < DEFAULT_RETRIES:
                        wait = min(DEFAULT_BACKOFF_BASE * (2 ** attempt), DEFAULT_BACKOFF_MAX)
                        logger.warning(
                            "sync_manager FETCH_ERROR %s %d-%02d attempt=%d wait=%.1fs: %s",
                            job.symbol, year, month, attempt + 1, wait, e,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "sync_manager FETCH_FAILED %s %d-%02d all retries exhausted: %s",
                            job.symbol, year, month, e,
                        )

            async with self._global_lock:
                job.retries += retries_used

            if candles is None:
                async with self._global_lock:
                    job.failed += 1
                    job.failed_months.append(f"{year:04d}-{month:02d}")
                    job.updated_at = _now_iso()
                self._persist_jobs()
                return

            # Escriu Parquet
            try:
                store.write_month(job.symbol, year, month, candles)
            except Exception as e:
                logger.error("sync_manager WRITE_ERROR %s %d-%02d: %s", job.symbol, year, month, e)
                async with self._global_lock:
                    job.failed += 1
                    job.failed_months.append(f"{year:04d}-{month:02d}")
                    job.updated_at = _now_iso()
                self._persist_jobs()
                return

            # Actualitza coverage index
            try:
                from application.data.coverage_index import CoverageIndex
                coverage = CoverageIndex(root_path=self._datafiles_root, symbol=job.symbol)
                if candles:
                    from domain.models import Candle
                    ts_list = [int(c.timestamp.timestamp()) for c in candles]
                    coverage.mark_done(year, month, rows=len(ts_list),
                                       coverage_from=ts_list[0], coverage_to=ts_list[-1],
                                       retries=retries_used)
                else:
                    coverage.mark_empty(year, month)
            except Exception as e:
                logger.warning("sync_manager coverage update error %d-%02d: %s", year, month, e)

            async with self._global_lock:
                job.done += 1
                job.updated_at = _now_iso()

            logger.info(
                "sync_manager DONE_MONTH %s %d-%02d candles=%d retries=%d",
                job.symbol, year, month, len(candles) if candles else 0, retries_used,
            )
            self._persist_jobs()

    def _get_month_lock(self, symbol: str, tf: str, year: int, month: int) -> asyncio.Lock:
        key = (symbol.upper(), tf, year, month)
        if key not in self._month_locks:
            self._month_locks[key] = asyncio.Lock()
        return self._month_locks[key]

    # ---------------------------------------------------------------------------
    # Persistència
    # ---------------------------------------------------------------------------

    def _persist_jobs(self) -> None:
        """Escriu sync_jobs.json de forma atòmica (últims MAX_JOBS_PERSISTED jobs)."""
        try:
            self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
            # Ordena per started_at desc, limita a MAX_JOBS_PERSISTED
            all_jobs = sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)
            jobs_to_save = [j.to_dict() for j in all_jobs[:MAX_JOBS_PERSISTED]]
            payload = {"version": 1, "jobs": jobs_to_save}
            tmp = self._jobs_path.with_suffix(".tmp.json")
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            tmp.rename(self._jobs_path)
        except Exception as e:
            logger.warning("sync_manager persist error: %s", e)

    def _load_jobs(self) -> None:
        """Carrega sync_jobs.json al startup. Jobs RUNNING → INTERRUPTED."""
        if not self._jobs_path.exists():
            return
        try:
            with open(self._jobs_path) as f:
                data = json.load(f)
            for jd in data.get("jobs", []):
                try:
                    job = SyncJob.from_dict(jd)
                    if job.status == "RUNNING":
                        job.status = "INTERRUPTED"
                        job.updated_at = _now_iso()
                    self._jobs[job.job_id] = job
                    # Només registra al keys_by_key si és RUNNING (no és el cas post-load)
                except Exception as e:
                    logger.warning("sync_manager load job error: %s", e)
            logger.info("sync_manager loaded %d jobs from %s", len(self._jobs), self._jobs_path)
        except Exception as e:
            logger.warning("sync_manager load error: %s", e)
