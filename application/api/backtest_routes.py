"""
Backtest API — Phase 12.

Prefix: /api/v1/backtests

POST /run          → inicia backtest offline (síncron), retorna run_id + resum
GET  /runs/{run_id} → retorna artifact JSON del run (carregat des de disc)

Persistència: artifact JSON a datafiles/backtests/<run_id>_<symbol>.json
run_id derivat del nom de fitxer (YYYYMMDD_HHMMSS format).
"""

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from application.api.error_codes import BACKTEST_RUN_FAILED, BACKTEST_NOT_FOUND, BACKTEST_INVALID_PARAMS
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])

BACKTESTS_SUBDIR = "backtests"
SUPPORTED_STRATEGIES = frozenset({"simple_trend"})
SUPPORTED_TIMEFRAMES = frozenset({"1m"})
MAX_DAYS = 30


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BacktestRunRequest(BaseModel):
    symbol: str = Field(..., description="Símbol (EURUSD, XAUUSD, ...)")
    days: float = Field(default=1.0, ge=0.01, le=MAX_DAYS, description="Finestra temporal en dies")
    timeframe: str = Field(default="1m", description="Timeframe (1m)")
    strategy: str = Field(default="simple_trend", description="Estratègia (simple_trend)")
    lookback: int = Field(default=5, ge=1, le=100, description="Lookback candles")
    hold_minutes: int = Field(default=10, ge=1, le=1440, description="Durada màxima posició (minuts)")

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        s = v.strip().upper()
        if not s or not s.isalnum() or len(s) > 10:
            raise ValueError("symbol invàlid")
        return s

    @field_validator("timeframe")
    @classmethod
    def timeframe_supported(cls, v: str) -> str:
        if v not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"timeframe '{v}' no suportat; suportats: {sorted(SUPPORTED_TIMEFRAMES)}")
        return v

    @field_validator("strategy")
    @classmethod
    def strategy_supported(cls, v: str) -> str:
        if v not in SUPPORTED_STRATEGIES:
            raise ValueError(f"strategy '{v}' no suportada; suportades: {sorted(SUPPORTED_STRATEGIES)}")
        return v


class XDataSummary(BaseModel):
    source: str
    candles_count: int
    missing_minutes: int
    max_gap_s: int
    coverage_from: int
    coverage_to: int


class BacktestKPIs(BaseModel):
    trades_count: int
    wins: int
    losses: int
    win_rate_pct: float
    pnl_total_pct: float
    roi_pct: float
    max_drawdown_pct: float


class BacktestRunResponse(BaseModel):
    run_id: str
    status: str  # "completed" | "failed"
    symbol: str
    timeframe: str
    strategy: str
    window_days: float
    x_data: XDataSummary
    kpis: BacktestKPIs
    artifact_id: str  # = run_id (per GET posterior)


class BacktestRunResult(BaseModel):
    run_id: str
    status: str
    symbol: str
    timeframe: str
    strategy: str
    window: dict
    x_data: XDataSummary
    kpis: BacktestKPIs
    trades_sample: list
    artifact_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_backtests_dir() -> Path:
    root = os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)
    d = Path(root) / BACKTESTS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_artifact_by_run_id(run_id: str, backtests_dir: Path) -> Optional[Path]:
    """Cerca el fitxer artifact que comenci amb run_id + '_'."""
    for p in backtests_dir.glob(f"{run_id}_*.json"):
        return p
    return None


def _artifact_to_run_id(artifact_path: Path) -> str:
    """Extreu run_id (YYYYMMDD_HHMMSS) del nom de fitxer."""
    # Format: YYYYMMDD_HHMMSS_SYMBOL.json → run_id = YYYYMMDD_HHMMSS
    parts = artifact_path.stem.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}_{parts[1]}"
    return artifact_path.stem


def _result_to_response(data: dict) -> BacktestRunResponse:
    cov = data.get("coverage", {})
    return BacktestRunResponse(
        run_id=data["run_ts"],
        status="completed",
        symbol=data["symbol"],
        timeframe=data.get("timeframe", "1m"),
        strategy=data.get("strategy", {}).get("name", "simple_trend"),
        window_days=data.get("window", {}).get("days", 1.0),
        x_data=XDataSummary(
            source=cov.get("source", "unknown"),
            candles_count=cov.get("candles_count", 0),
            missing_minutes=cov.get("missing_minutes", 0),
            max_gap_s=cov.get("max_gap_s", 0),
            coverage_from=cov.get("coverage_from", 0),
            coverage_to=cov.get("coverage_to", 0),
        ),
        kpis=BacktestKPIs(**data["kpis"]),
        artifact_id=data["run_ts"],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs() -> dict:
    """
    Llista run_ids dels artifacts existents (pot ser buit).
    Smoke gateway: GET /backtests/runs → 200.
    """
    backtests_dir = _get_backtests_dir()
    run_ids = []
    for p in backtests_dir.glob("*_*.json"):
        rid = _artifact_to_run_id(p)
        if rid and rid not in run_ids:
            run_ids.append(rid)
    run_ids.sort(reverse=True)  # més recents primer
    return {"runs": run_ids}


@router.post("/run", response_model=BacktestRunResponse, status_code=200)
async def post_run(req: BacktestRunRequest):
    """
    Inicia backtest offline (síncron).

    Resol source via registry (Ostium local / Dukascopy), executa estratègia,
    genera KPIs i escriu artifact JSON.
    """
    from datetime import datetime, timedelta, timezone
    from application.tools.run_backtest import run_backtest

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = now
    start = end - timedelta(days=req.days)

    backtests_dir = _get_backtests_dir()

    try:
        result = await run_backtest(
            symbol=req.symbol,
            start=start,
            end=end,
            datafiles_root=os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
            lookback=req.lookback,
            hold_minutes=req.hold_minutes,
            artifact_dir=backtests_dir,
        )
    except Exception as e:
        logger.error("backtest API run error symbol=%s: %s", req.symbol, e)
        raise HTTPException(
            status_code=500,
            detail={"detail": f"backtest run failed: {e}", "code": BACKTEST_RUN_FAILED},
        )

    return _result_to_response(result)


@router.get("/runs/{run_id}", response_model=BacktestRunResult)
async def get_run(run_id: str):
    """
    Retorna resultat d'un run existent (carregat des de l'artifact JSON).
    """
    if not run_id or len(run_id) > 20 or not all(c.isdigit() or c == "_" for c in run_id):
        raise HTTPException(
            status_code=422,
            detail={"detail": "run_id invàlid", "code": BACKTEST_INVALID_PARAMS},
        )

    backtests_dir = _get_backtests_dir()
    artifact_path = _find_artifact_by_run_id(run_id, backtests_dir)

    if artifact_path is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"run_id '{run_id}' no trobat", "code": BACKTEST_NOT_FOUND},
        )

    try:
        data = json.loads(artifact_path.read_text())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"detail": f"artifact read error: {e}", "code": BACKTEST_RUN_FAILED},
        )

    cov = data.get("coverage", {})
    return BacktestRunResult(
        run_id=data["run_ts"],
        status="completed",
        symbol=data["symbol"],
        timeframe=data.get("timeframe", "1m"),
        strategy=data.get("strategy", {}).get("name", "simple_trend"),
        window=data.get("window", {}),
        x_data=XDataSummary(
            source=cov.get("source", "unknown"),
            candles_count=cov.get("candles_count", 0),
            missing_minutes=cov.get("missing_minutes", 0),
            max_gap_s=cov.get("max_gap_s", 0),
            coverage_from=cov.get("coverage_from", 0),
            coverage_to=cov.get("coverage_to", 0),
        ),
        kpis=BacktestKPIs(**data["kpis"]),
        trades_sample=data.get("trades_sample", []),
        artifact_id=data["run_ts"],
    )
