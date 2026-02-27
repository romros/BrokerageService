"""
Data API — Phase 14/16/19/20/T8.1.

Prefix: /api/v1/data

GET  /ohlcv/{symbol}      → candles OHLCV registry-aware (Ostium local o Dukascopy fallback)
                            Si existeix Parquet históric → DuckDB (Phase 16)
                            Mixed stitching parquet+realtime (Phase 20)
GET  /coverage/{symbol}   → Coverage index per símbol (Phase 19)
POST /sync                → Sync idempotent Dukascopy→Parquet (T8.1)

Dissenyat per ser consumit per un adaptador Freqtrade backtest.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
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
# T8.1: Sync endpoint — backfill idempotent Dukascopy → Parquet
# ---------------------------------------------------------------------------

MAX_SYNC_YEARS = 10  # guardrail: màxim anys per crida sense chunking

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


@router.post("/sync")
async def post_sync(req: SyncRequest):
    """
    Sync idempotent Dukascopy → Parquet per un símbol/timeframe (T8.1).

    Comportament:
      - Detecta cobertura existent (CoverageIndex)
      - Baixa NOMÉS el delta [last_covered+1_mes, to]
      - Si ja és up_to_date → retorna status=up_to_date sense descarregar res
      - Idempotent: cridar 2 cops seguits → 2n sempre status=up_to_date

    Guardrails:
      - Màxim MAX_SYNC_YEARS anys per crida
      - tf ha de ser '1m'

    Response:
      {
        "status": "up_to_date|synced|partial|error",
        "symbol": "XAUUSD",
        "tf": "1m",
        "requested_from": "2016-01-01",
        "requested_to": "2026-02-27",
        "months_written": 3,
        "months_skipped": 120,
        "months_failed": 0,
        "candles_written": 134523,
        "coverage_from": "2016-01-01",
        "coverage_to": "2026-02-01"
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

    # Resolució de dates
    if req.to_date:
        try:
            to_d = date.fromisoformat(req.to_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"detail": "to invàlid; format YYYY-MM-DD", "code": INVALID_PARAMS})
    else:
        to_d = today

    datafiles_root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)

    # Detectar cobertura existent per decidir from_d (delta)
    from application.data.coverage_index import CoverageIndex
    idx = CoverageIndex(root_path=datafiles_root, symbol=sym)
    done_months = idx.months_done()

    if req.from_date:
        try:
            from_d = date.fromisoformat(req.from_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"detail": "from invàlid; format YYYY-MM-DD", "code": INVALID_PARAMS})
    elif done_months:
        # Avancem des de l'últim mes cobert + 1
        last_done = done_months[-1]
        y, m = int(last_done[:4]), int(last_done[5:7])
        m += 1
        if m > 12:
            m = 1
            y += 1
        from_d = date(y, m, 1)
    else:
        from_d = DUKASCOPY_EARLIEST

    from_d = max(from_d, DUKASCOPY_EARLIEST)

    # Guardrail: màxim MAX_SYNC_YEARS anys per crida
    max_to = date(from_d.year + MAX_SYNC_YEARS, from_d.month, from_d.day)
    if to_d > max_to:
        raise HTTPException(
            status_code=422,
            detail={
                "detail": f"rang massa gran (>{MAX_SYNC_YEARS} anys per crida); divideix en crides més curtes",
                "code": INVALID_PARAMS,
            },
        )

    # Comprovar si ja és up_to_date
    if from_d > to_d:
        # Calcular coverage actual per la resposta
        coverage_from_str = done_months[0] if done_months else None
        coverage_to_str = done_months[-1] if done_months else None
        return JSONResponse(content={
            "status": "up_to_date",
            "symbol": sym,
            "tf": req.tf,
            "requested_from": str(from_d),
            "requested_to": str(to_d),
            "months_written": 0,
            "months_skipped": 0,
            "months_failed": 0,
            "candles_written": 0,
            "coverage_from": coverage_from_str,
            "coverage_to": coverage_to_str,
        })

    # Executar backfill (async, però asyncio.run no funciona dins event loop — usem await directament)
    from application.tools.run_historical_backfill import run_historical_backfill
    result = await run_historical_backfill(
        symbol=sym,
        from_date=from_d,
        to_date=to_d,
        datafiles_root=datafiles_root,
        skip_existing=True,
        sleep_s=0.5,
        retry_failed=False,
        update_coverage=True,
    )

    # Recalcular coverage després del sync
    idx2 = CoverageIndex(root_path=datafiles_root, symbol=sym)
    done2 = idx2.months_done()
    coverage_from_str = done2[0] if done2 else None
    coverage_to_str = done2[-1] if done2 else None

    if result["months_failed"] > 0 and result["months_written"] == 0:
        status = "error"
    elif result["months_failed"] > 0:
        status = "partial"
    elif result["months_written"] == 0:
        status = "up_to_date"
    else:
        status = "synced"

    return JSONResponse(content={
        "status": status,
        "symbol": sym,
        "tf": req.tf,
        "requested_from": str(from_d),
        "requested_to": str(to_d),
        "months_written": result["months_written"],
        "months_skipped": result["months_skipped"],
        "months_failed": result["months_failed"],
        "candles_written": result["candles_total"],
        "coverage_from": coverage_from_str,
        "coverage_to": coverage_to_str,
    })


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
        "/sync",
        post_sync,
        methods=["POST"],
        summary="Sync idempotent Dukascopy→Parquet (T8.1)",
    )
    return hist_router
