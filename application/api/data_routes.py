"""
Data API — Phase 14/16/19/20.

Prefix: /api/v1/data

GET /ohlcv/{symbol}      → candles OHLCV registry-aware (Ostium local o Dukascopy fallback)
                           Si existeix Parquet históric → DuckDB (Phase 16)
                           Mixed stitching parquet+realtime (Phase 20)
GET /coverage/{symbol}   → Coverage index per símbol (Phase 19)

Dissenyat per ser consumit per un adaptador Freqtrade backtest.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

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
    return hist_router
