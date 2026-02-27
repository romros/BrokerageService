"""
Data API — Phase 14/16/19/20/T8.1/T8.6.

Prefix: /api/v1/data

GET  /ohlcv/{symbol}           → candles OHLCV registry-aware (Ostium local o Dukascopy fallback)
                                  Si existeix Parquet históric → DuckDB (Phase 16)
                                  Mixed stitching parquet+realtime (Phase 20)
GET  /coverage/{symbol}        → Coverage index per símbol (Phase 19)
POST /coverage/{symbol}/rebuild → Rebuild coverage index des del disc (T8.2)
POST /sync                     → Inicia sync async (T8.6) — retorna job_id immediatament
GET  /sync                     → Llista jobs recents
GET  /sync/{job_id}            → Progrés d'un job concret

Dissenyat per ser consumit per un adaptador Freqtrade backtest.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from application.api.error_codes import INVALID_PARAMS
from application.data.backtest_market_data import get_ohlcv_backtest
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger

import os

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])

SUPPORTED_TIMEFRAMES = frozenset({"1m"})
DEFAULT_LIMIT = 1000
MAX_LIMIT = 5000


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    tf: str = Query(default="1m", description="Timeframe (només 1m)"),
    from_ts: Optional[int] = Query(default=None, description="Inici rang (epoch UTC)"),
    to_ts: Optional[int] = Query(default=None, description="Fi rang (epoch UTC)"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Màxim candles retornades"),
    offset: int = Query(default=0, ge=0, description="Offset per paginació (legacy; usa next_ts per rangs llargs)"),
    next_ts: Optional[int] = Query(default=None, description="Cursor paginació DuckDB (timestamp exclusiu inici)"),
):
    """
    Retorna candles OHLCV registry-aware.

    - Si existeix Parquet históric (Phase 16) → DuckDB amb cursor next_ts
    - symbol graduat (allowed_for_backtest=true) → ostium_local
    - altrament → dukascopy fallback

    Format candles: [[ts_epoch, open, high, low, close, volume], ...]
    X-Data-* headers inclosos per qualitat de dades.
    """
    # Validar symbol
    sym = symbol.strip().upper()
    if not sym or not sym.isalnum() or len(sym) > 10:
        raise HTTPException(
            status_code=422,
            detail={"detail": "symbol invàlid", "code": INVALID_PARAMS},
        )

    # Validar timeframe
    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"timeframe '{tf}' no suportat; suportats: {sorted(SUPPORTED_TIMEFRAMES)}", "code": INVALID_PARAMS},
        )

    datafiles_root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)

    # Phase 16: routing DuckDB si existeix Parquet históric
    from infrastructure.query.duckdb_query_service import DuckDBQueryService
    duckdb_svc = DuckDBQueryService(root_path=datafiles_root)

    if duckdb_svc.has_data(sym):
        parquet_result = duckdb_svc.query_ohlcv(
            symbol=sym,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
            next_ts=next_ts,
        )

        # Phase 20: mixed stitching parquet + realtime
        from application.data.mixed_ohlcv_stitcher import stitch_ohlcv_mixed, compute_xdata_headers_mixed
        stitched = stitch_ohlcv_mixed(
            parquet_candles=parquet_result["candles"],
            symbol=sym,
            datafiles_root=datafiles_root,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
            next_ts_cursor=next_ts,
        )

        xdata_headers = compute_xdata_headers_mixed(
            candles=stitched["candles"],
            source=stitched["source"],
            from_ts=from_ts,
            to_ts=to_ts,
        )
        response_body = {
            "symbol": sym,
            "timeframe": tf,
            "source": stitched["source"],
            "candles": stitched["candles"],
            "total": parquet_result["total_in_range"],
            "limit": limit,
            "next_ts": stitched["next_ts"],
        }
        return JSONResponse(content=response_body, headers=xdata_headers)

    # Camí legacy (Phase 14): Ostium local o Dukascopy
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if to_ts is not None:
        end = datetime.fromtimestamp(to_ts, tz=timezone.utc)
    else:
        end = now
    if from_ts is not None:
        start = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    else:
        start = end - timedelta(minutes=limit + offset + 60)

    if start >= end:
        raise HTTPException(
            status_code=422,
            detail={"detail": "from_ts ha de ser anterior a to_ts", "code": INVALID_PARAMS},
        )

    body, xdata_headers = await get_ohlcv_backtest(
        symbol=sym,
        start=start,
        end=end,
        datafiles_root=datafiles_root,
    )

    all_candles = body.get("candles", [])

    page = all_candles[offset: offset + limit]
    next_offset = offset + limit if (offset + limit) < len(all_candles) else None

    candles_array = [
        [c["ts"], c["open"], c["high"], c["low"], c["close"], c["volume"]]
        for c in page
    ]

    response_body = {
        "symbol": sym,
        "timeframe": tf,
        "source": xdata_headers.get("X-Data-Source", "unknown"),
        "candles": candles_array,
        "total": len(all_candles),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "next_ts": None,
    }

    return JSONResponse(content=response_body, headers=xdata_headers)


# ---------------------------------------------------------------------------
# Phase 19: Coverage API
# ---------------------------------------------------------------------------

@router.get("/coverage/{symbol}")
async def get_coverage(
    symbol: str,
    tf: str = Query(default="1m", description="Timeframe (només 1m)"),
):
    """
    Retorna el coverage index del Parquet históric per un símbol.

    Response:
    {
      "symbol": "EURUSD",
      "timeframe": "1m",
      "summary": {months_total, months_done, months_failed, months_empty, total_rows},
      "months": {"2020-01": {"status": "done", "rows": 31653, ...}, ...}
    }

    Si no existeix coverage index → summary buit + months buit (no 404).
    """
    sym = symbol.strip().upper()
    if not sym or not sym.isalnum() or len(sym) > 10:
        raise HTTPException(
            status_code=422,
            detail={"detail": "symbol invàlid", "code": INVALID_PARAMS},
        )

    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"timeframe '{tf}' no suportat", "code": INVALID_PARAMS},
        )

    datafiles_root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)

    from application.data.coverage_index import CoverageIndex
    idx = CoverageIndex(root_path=datafiles_root, symbol=sym)
    has_index = idx._path.exists()
    summary = idx.summary()

    return JSONResponse(content={
        "symbol": sym,
        "timeframe": tf,
        "has_index": has_index,
        "summary": summary,
        "months": idx._data.get("months", {}),
    })


# ---------------------------------------------------------------------------
# T8.2: Rebuild coverage index des del disc (Parquet = source of truth)
# ---------------------------------------------------------------------------

@router.post("/coverage/{symbol}/rebuild")
async def post_rebuild_coverage(
    symbol: str,
    tf: str = Query(default="1m", description="Timeframe (només 1m)"),
):
    """
    Reconstrueix el coverage index llegint els Parquets reals al disc.

    - Font de veritat: fitxers .parquet
    - No baixa dades, no modifica Parquets
    - Idempotent: 2a execució retorna changed=false si res ha canviat
    - Detecta mesos missing (entre primer i últim done però absents al disc)

    Response:
    {
      "symbol": "XAUUSD",
      "timeframe": "1m",
      "months_done": 264,
      "months_empty": 13,
      "months_missing": ["2022-11", "2022-12"],
      "total_rows": 7500000,
      "coverage_from": "2003-05",
      "coverage_to": "2026-02",
      "changed": true,
      "index_path": "/datafiles/historical_parquet/_coverage/XAUUSD_tf1m.json"
    }
    """
    sym = symbol.strip().upper()
    if not sym or not sym.isalnum() or len(sym) > 10:
        raise HTTPException(
            status_code=422,
            detail={"detail": "symbol invàlid", "code": INVALID_PARAMS},
        )
    if tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"timeframe '{tf}' no suportat", "code": INVALID_PARAMS},
        )

    datafiles_root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)

    from application.data.rebuild_coverage import rebuild_coverage_index
    result = await asyncio.get_event_loop().run_in_executor(
        None, rebuild_coverage_index, datafiles_root, sym, tf
    )

    return JSONResponse(content={
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "months_done": result.months_done,
        "months_empty": result.months_empty,
        "months_missing": result.months_missing,
        "total_rows": result.total_rows,
        "coverage_from": result.coverage_from,
        "coverage_to": result.coverage_to,
        "changed": result.changed,
        "index_path": result.index_path,
    })


# ---------------------------------------------------------------------------
# T8.6: Sync async amb SyncManager — job tracking + N workers
# ---------------------------------------------------------------------------

DUKASCOPY_EARLIEST = date(2003, 1, 1)  # primera data disponible a Dukascopy


class SyncRequest(BaseModel):
    symbol: str = Field(..., description="Símbol (ex: XAUUSD, EURUSD)")
    tf: str = Field("1m", description="Timeframe (només 1m suportat)")
    from_date: Optional[str] = Field(
        None,
        alias="from",
        description="Data inici YYYY-MM-DD (default: cobertura existent o 2003-01-01)",
    )
    to_date: Optional[str] = Field(
        None,
        alias="to",
        description="Data fi YYYY-MM-DD (default: avui)",
    )

    model_config = {"populate_by_name": True}


def _get_sync_manager(request: Request):
    """Obté el SyncManager des del app.state o crea un de fallback (test/dev)."""
    mgr = getattr(request.app.state, "sync_manager", None)
    if mgr is None:
        # Fallback: crea manager inline (no persisteix entre crides)
        from application.data.sync_manager import SyncManager
        datafiles_root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)
        mgr = SyncManager(datafiles_root=datafiles_root)
        request.app.state.sync_manager = mgr
        logger.warning("SyncManager creat inline (no inicialitzat al lifespan)")
    return mgr


@router.post("/sync")
async def post_sync(req: SyncRequest, request: Request):
    """
    Inicia un job de sync async Dukascopy→Parquet (T8.6).

    Retorna immediatament amb job_id i status=RUNNING.
    El job s'executa en background amb N workers concurrent.

    Reentrança: 2a crida amb el mateix rang → retorna el job existent (is_new=false).

    Response:
      {
        "job_id": "a1b2c3d4",
        "is_new": true,
        "status": "RUNNING",
        "symbol": "XAUUSD",
        "tf": "1m",
        "total_units": 12,
        "done": 0,
        "skipped": 262,
        "failed": 0,
        "retries": 0,
        "started_at": "2026-02-27T10:00:00Z",
        "updated_at": "2026-02-27T10:00:00Z",
        "failed_months": [],
        "coverage_from": null,
        "coverage_to": null,
        "message": "new_job"
      }
    """
    sym = req.symbol.strip().upper()
    if not sym or not sym.isalnum() or len(sym) > 10:
        raise HTTPException(status_code=422, detail={"detail": "symbol invàlid", "code": INVALID_PARAMS})

    if req.tf not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"tf '{req.tf}' no suportat; suportats: {sorted(SUPPORTED_TIMEFRAMES)}", "code": INVALID_PARAMS},
        )

    today = date.today()

    if req.to_date:
        try:
            to_d = date.fromisoformat(req.to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"detail": "to invàlid; format YYYY-MM-DD", "code": INVALID_PARAMS})
    else:
        to_d = today

    if req.from_date:
        try:
            from_d = date.fromisoformat(req.from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"detail": "from invàlid; format YYYY-MM-DD", "code": INVALID_PARAMS})
    else:
        from_d = DUKASCOPY_EARLIEST

    from_d = max(from_d, DUKASCOPY_EARLIEST)

    if from_d > to_d:
        raise HTTPException(
            status_code=422,
            detail={"detail": "from ha de ser anterior o igual a to", "code": INVALID_PARAMS},
        )

    manager = _get_sync_manager(request)
    job, is_new = await manager.start_job(sym, req.tf, str(from_d), str(to_d))

    snap = job.snapshot()
    snap["is_new"] = is_new
    snap["message"] = "new_job" if is_new else "existing_job"
    return JSONResponse(content=snap)


@router.get("/sync")
async def list_sync_jobs(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50, description="Màxim jobs retornats"),
):
    """
    Llista els jobs de sync recents, ordenats per started_at desc.
    """
    manager = _get_sync_manager(request)
    jobs = manager.list_jobs(limit=limit)
    return JSONResponse(content={"jobs": [j.snapshot() for j in jobs], "total": len(jobs)})


@router.get("/sync/{job_id}")
async def get_sync_job(job_id: str, request: Request):
    """
    Retorna el progrés d'un job de sync concret.

    Response:
      {
        "job_id": "a1b2c3d4",
        "status": "RUNNING|DONE|FAILED|INTERRUPTED",
        "symbol": "XAUUSD",
        "tf": "1m",
        "total_units": 12,
        "done": 7,
        "skipped": 262,
        "failed": 0,
        "retries": 1,
        "eta_s": 150.0,
        "coverage_from": "2003-05",
        "coverage_to": "2022-12",
        "failed_months": [],
        "started_at": "...",
        "updated_at": "..."
      }
    """
    manager = _get_sync_manager(request)
    job = manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"detail": f"job '{job_id}' no trobat", "code": "JOB_NOT_FOUND"})
    return JSONResponse(content=job.snapshot())


# ---------------------------------------------------------------------------
# Phase C: Historical DataLayer — router sense prefix /api/v1/data
# Montat pel historical_datalayer (nginx fa strip de /data/, arriba com /)
# Endpoints: /ohlcv/{symbol}  /coverage/{symbol}
# ---------------------------------------------------------------------------

def get_historical_router() -> APIRouter:
    """
    Retorna un APIRouter sense prefix per a historical_datalayer.
    Els mateixos handlers que `router` (/api/v1/data/*) però a / directament.
    Nginx fa: /data/ohlcv/EURUSD → strip → /ohlcv/EURUSD → historical:8002
    """
    hist_router = APIRouter(tags=["historical-data"])
    hist_router.add_api_route(
        "/ohlcv/{symbol}",
        get_ohlcv,
        methods=["GET"],
        summary="OHLCV (historical)",
    )
    hist_router.add_api_route(
        "/coverage/{symbol}",
        get_coverage,
        methods=["GET"],
        summary="Coverage index (historical)",
    )
    hist_router.add_api_route(
        "/coverage/{symbol}/rebuild",
        post_rebuild_coverage,
        methods=["POST"],
        summary="Rebuild coverage index des del disc (T8.2)",
    )
    # T8.6: Sync async amb SyncManager
    hist_router.add_api_route(
        "/sync",
        post_sync,
        methods=["POST"],
        summary="Inicia sync async Dukascopy→Parquet (T8.6)",
    )
    hist_router.add_api_route(
        "/sync",
        list_sync_jobs,
        methods=["GET"],
        summary="Llista jobs sync recents",
    )
    hist_router.add_api_route(
        "/sync/{job_id}",
        get_sync_job,
        methods=["GET"],
        summary="Progrés d'un job sync",
    )
    return hist_router
