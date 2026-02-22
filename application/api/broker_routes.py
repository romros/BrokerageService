"""
Broker API - REST endpoints unificats

Prefix: /api/v1/broker
POST /orders/open i /orders/close amb JSON body.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Callable, Any

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from infrastructure.storage.gap_validator import GapValidator
from application.api.repair_stats import get_last_repair

from application.api.candle_helpers import resolve_candle_range, read_candles
from application.api.error_codes import (
    ADAPTER_NOT_AVAILABLE,
    CANDLE_STORE_NOT_AVAILABLE,
    DATA_STATUS_NOT_AVAILABLE,
    DATA_QUALITY_GATE_BAD,
    VENUE_NOT_CONFIGURED,
    TIMEFRAME_NOT_SUPPORTED,
    SYMBOL_NOT_FOUND,
    POSITION_NOT_FOUND,
    MIXED_SOURCE_NOT_ALLOWED,
    POSITION_ALREADY_OPEN,
)
from application.api.models import (
    HealthResponse,
    ModeResponse,
    OHLCVCandle,
    OHLCVResponse,
    BalanceResponse,
    OrderOpenRequest,
    OrderCloseRequest,
    TradeItem,
    TradesResponse,
)
from domain.errors import PositionNotFoundError, MarketNotFoundError
from foundation.config.constants import (
    CANONICAL_TIMEZONE,
    CANONICAL_TIMEZONE_NAME,
    DATA_LAYER_ENABLED_ENV,
    DATA_LAYER_STARTUP_GATE_ENV,
    DEFAULT_READ_THROUGH_MAX_MISSING,
    DEFAULT_READ_THROUGH_TIMEOUT_S,
    ENABLE_READ_THROUGH_ENV,
    READ_THROUGH_MAX_MISSING_ENV,
    READ_THROUGH_TIMEOUT_ENV,
    SUPPORTED_TIMEFRAME,
    DEFAULT_CANDLES_LIMIT,
    DEFAULT_OHLCV_LIMIT,
    MAX_CANDLES_LIMIT,
    DEFAULT_TRADES_LIMIT,
    MAX_TRADES_LIMIT,
    KNOWN_VENUES,
    PAPER_MAINTENANCE_MARGIN_RATIO_ENV,
    DEFAULT_PAPER_MAINTENANCE_MARGIN_RATIO,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

# Split vNext: data_router (health, data_status, candles, etc.) | trading_router (orders, balance, etc.)
data_router = APIRouter()
trading_router = APIRouter()

# Combined router (backward compat + monolithic). include_router al final del fitxer (després dels decorators)
router = APIRouter(prefix="/api/v1/broker", tags=["broker"])
_data_only_router = APIRouter(prefix="/api/v1/broker", tags=["broker"])


def get_routers_for_role(role: str | None) -> list:
    """Routers per SERVICE_ROLE. realtime/historical: només data. trading/legacy: data + trading."""
    if role in (None, "trading_service"):
        return [router]
    if role in ("realtime_datalayer", "historical_datalayer"):
        return [_data_only_router]
    return [router]


def _build_routers() -> None:
    """Crida al final del mòdul, després que tots els decorators hagin registrat les rutes."""
    router.include_router(data_router)
    router.include_router(trading_router)
    _data_only_router.include_router(data_router)

_UNSET = object()

# DI
_candle_store: Optional[Any] = None
_adapter_factory: Optional[Callable[[str], Any]] = None
_mode: str = "backtest"
_venue: str = "gtrade"
_market_data_env: str = "mainnet"
_market_data_source: str = "n/a"  # fake|real|n/a — visible a GET /mode i freqtrade_runner
_fallback_provider: Optional[Any] = None  # P7: DukascopyBackfillProvider (read-only)
_primary_backfill_provider: Optional[Any] = None  # P8: LighterCandlestickBackfillProvider (read-through)
_data_layer_write_mode: str = "realtime"
_ostium_ingest_enabled: bool = False
_ostium_ingest_poll_s: int = 2
_data_layer_reader: Optional[Any] = None  # Split vNext Phase 2: IDataLayerReader (HTTP o local)


def set_broker_deps(
    candle_store: Any = _UNSET,
    adapter_factory: Any = _UNSET,
    mode: str = _UNSET,
    venue: str = _UNSET,
    market_data_env: str = _UNSET,
    market_data_source: str = _UNSET,
    fallback_provider: Any = _UNSET,
    primary_backfill_provider: Any = _UNSET,
    data_layer_write_mode: str = _UNSET,
    ostium_ingest_enabled: bool = _UNSET,
    ostium_ingest_poll_s: int = _UNSET,
    data_layer_reader: Any = _UNSET,
) -> None:
    """Inject dependencies for broker routes."""
    global _candle_store, _adapter_factory, _mode, _venue, _market_data_env, _market_data_source
    global _fallback_provider, _primary_backfill_provider, _data_layer_write_mode, _ostium_ingest_enabled, _ostium_ingest_poll_s
    global _data_layer_reader
    if candle_store is not _UNSET:
        _candle_store = candle_store
    if adapter_factory is not _UNSET:
        _adapter_factory = adapter_factory
    if fallback_provider is not _UNSET:
        _fallback_provider = fallback_provider
    if primary_backfill_provider is not _UNSET:
        _primary_backfill_provider = primary_backfill_provider
    if mode is not _UNSET:
        _mode = mode
    if venue is not _UNSET:
        _venue = venue
    if market_data_env is not _UNSET:
        _market_data_env = market_data_env
    if market_data_source is not _UNSET:
        _market_data_source = market_data_source
    if data_layer_write_mode is not _UNSET:
        _data_layer_write_mode = data_layer_write_mode
    if ostium_ingest_enabled is not _UNSET:
        _ostium_ingest_enabled = ostium_ingest_enabled
    if ostium_ingest_poll_s is not _UNSET:
        _ostium_ingest_poll_s = ostium_ingest_poll_s
    if data_layer_reader is not _UNSET:
        _data_layer_reader = data_layer_reader
    logger.info(
        f"Broker API deps: mode={_mode}, venue={_venue}, market_data_env={_market_data_env}, "
        f"market_data_source={_market_data_source}, adapter_factory={'set' if _adapter_factory else 'None'}"
    )


def _http_error(status_code: int, code: str, detail: str):
    """Llança HTTPException amb format {detail, code} consistent."""
    raise HTTPException(status_code=status_code, detail={"detail": detail, "code": code})


def _get_paper_maintenance_ratio() -> float:
    """P3.0: Llegeix PAPER_MAINTENANCE_MARGIN_RATIO des de env."""
    val = os.getenv(PAPER_MAINTENANCE_MARGIN_RATIO_ENV, "")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return DEFAULT_PAPER_MAINTENANCE_MARGIN_RATIO


def _get_adapter_or_http_error(venue: str):
    """
    Retorna l'adapter per venue o llança HTTPException.
    - 503 + ADAPTER_NOT_AVAILABLE: adapter_factory no configurat (server no wired)
    - 422 + VENUE_NOT_CONFIGURED: venue no configurat / no suportat
    """
    if _adapter_factory is None:
        _http_error(
            503,
            ADAPTER_NOT_AVAILABLE,
            "adapter_factory not configured (VENUE=...). Set VENUE=lighter to enable.",
        )
    adapter = _adapter_factory(venue)
    if adapter is None:
        available = _get_available_venues()
        _http_error(
            422,
            VENUE_NOT_CONFIGURED,
            f"venue not configured: {venue}. Available: {available}",
        )
    return adapter


def _get_available_venues() -> list[str]:
    """Venues disponibles segons wiring."""
    if _adapter_factory is None:
        return []
    return [v for v in KNOWN_VENUES if _adapter_factory(v) is not None]


# ============ Response models ============


class PairsResponse(BaseModel):
    pairs: List[dict]


class PriceLatestResponse(BaseModel):
    symbol: str
    bid: float
    ask: float
    mid: float
    timestamp: str


class PositionItem(BaseModel):
    position_id: str
    symbol: str
    side: str
    size: float
    notional: float
    open_price: float
    entry_time: str
    mark_price: Optional[float] = None  # Preu actual (per PnL)
    unrealized_pnl: Optional[float] = None  # PnL no realitzat en USD
    sl_price: Optional[float] = None  # P3.0 bracket
    tp_price: Optional[float] = None  # P3.0 bracket
    liquidation_price: Optional[float] = None  # P3.0 paper risk


class PositionsResponse(BaseModel):
    positions: List[PositionItem]


class OrderOpenResponse(BaseModel):
    success: bool
    position_id: str
    order_id: str
    executed_price: float
    executed_size: float
    tx_hash: str = ""


class OrderCloseResponse(BaseModel):
    success: bool


# ============ Core ============


@data_router.get("/health", response_model=HealthResponse)
async def get_health():
    """Health check. status=degraded si DATA_LAYER_STARTUP_GATE=1 i Data Layer té símbol DEGRADED."""
    status = "ok"
    if os.getenv(DATA_LAYER_STARTUP_GATE_ENV, "0") == "1" and os.getenv(DATA_LAYER_ENABLED_ENV, "0") == "1":
        from application.data.data_layer_metrics import get_data_layer_metrics, SYMBOL_STATE_DEGRADED
        metrics = get_data_layer_metrics()
        if metrics:
            snapshot = metrics.snapshot()
            for sym_data in snapshot.get("symbols", {}).values():
                if sym_data.get("symbol_state") == SYMBOL_STATE_DEGRADED:
                    status = "degraded"
                    break
    return HealthResponse(
        status=status,
        mode=_mode,
        venue=_venue,
        timestamp=datetime.now(),
    )


@data_router.get("/mode", response_model=ModeResponse)
async def get_mode():
    """Mode actual."""
    return ModeResponse(
        mode=_mode,
        is_live=(_mode == "live"),
        is_paper=(_mode == "paper"),
        is_backtest=(_mode == "backtest"),
        venue=_venue,
        market_data_env=_market_data_env,
        market_data_source=_market_data_source,
    )


# ============ Market data ============


@data_router.get("/venues")
async def get_venues():
    """Llista venues realment disponibles segons config/wiring actual."""
    venues = _get_available_venues()
    if not venues and _adapter_factory is None:
        logger.debug("adapter_factory not configured; /broker/venues returns []")
    return {"venues": venues}


@trading_router.get("/pairs", response_model=PairsResponse)
async def get_pairs(venue: str = Query(..., description="Venue (lighter)")):
    """Llista de pairs per venue."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        pairs = await adapter.get_pairs()
        return PairsResponse(
            pairs=[
                {
                    "symbol": p.symbol,
                    "base": p.base,
                    "quote": p.quote,
                    "min_size": 0.01,
                    "max_size": 100,
                    "max_leverage": p.max_leverage or 50,
                }
                for p in pairs
            ]
        )
    except Exception as e:
        logger.error("get_pairs %s: %s", venue, e)
        raise HTTPException(status_code=500, detail=str(e))


@trading_router.get("/price/latest", response_model=PriceLatestResponse)
async def get_price_latest(
    venue: str = Query(...),
    symbol: str = Query(...),
):
    """Preu actual (bid, ask, mid)."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        px = await adapter.get_latest_price(symbol)
        return PriceLatestResponse(
            symbol=symbol,
            bid=px.bid,
            ask=px.ask,
            mid=px.mid,
            timestamp=px.timestamp.isoformat() if px.timestamp else datetime.now().isoformat(),
        )
    except MarketNotFoundError as e:
        _http_error(404, SYMBOL_NOT_FOUND, str(e))
    except Exception as e:
        logger.error("get_price_latest %s %s: %s", venue, symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_policy(symbol: str) -> Any:
    """Resol DataPolicy per símbol (lazy import)."""
    from application.data.data_source_policy import resolve_data_policy
    from application.data.ostium_compat_registry import get_ostium_primary_allowed
    from application.data.compat_registry import get_compat_status

    return resolve_data_policy(
        symbol=symbol,
        ostium_ingest_enabled=_ostium_ingest_enabled,
        get_ostium_primary_allowed_fn=get_ostium_primary_allowed,
        get_compat_status_fn=get_compat_status,
    )


def _build_p5_headers(
    candle_range: Any,
    start: datetime,
    end: datetime,
    symbol: str,
    source: str = "primary",
    cutover_ts: Optional[int] = None,
    read_through_stats: Optional[Any] = None,
    policy: Optional[Any] = None,
) -> dict[str, str]:
    """P5/P7/P8: Headers d'observabilitat OHLCV (coverage, gaps, repair)."""
    from application.data.data_source_policy import source_for_header

    report = GapValidator.validate(
        candle_range.candles, start, end, symbol=symbol
    )
    max_gap_s = (
        max(g.count * 60 for g in report.gaps)
        if report.gaps
        else 0
    )
    if read_through_stats is not None:
        repair_status = read_through_stats.repair_status
        repair_filled = read_through_stats.filled
        repair_requested = read_through_stats.requested
    else:
        repair_at, repair_filled, repair_symbol = get_last_repair()
        repair_status = "applied" if repair_filled > 0 and repair_symbol == symbol else "none"
        repair_requested = repair_filled

    display_source = source_for_header(source, policy) if policy else source
    headers: dict[str, str] = {
        "X-Data-Source": display_source,
        "X-Data-Coverage-From": str(int(start.timestamp())),
        "X-Data-Coverage-To": str(int(end.timestamp())),
        "X-Data-Missing-Minutes": str(report.missing_count),
        "X-Data-Max-Gap-S": str(max_gap_s),
        "X-Data-Repair": repair_status,
        "X-Data-Repair-Filled": str(repair_filled),
        "X-Data-Repair-Requested": str(repair_requested),
    }
    if source == "mixed" and cutover_ts is not None:
        headers["X-Data-Cutover-Ts"] = str(cutover_ts)
    if policy and policy.primary_source == "ostium_recorded":
        headers["X-Data-Primary-Source"] = "ostium_recorded"
    return headers


async def _compute_ohlcv_content(
    symbol: str,
    limit: int,
    since: Optional[int],
    to: Optional[int],
    validate_gaps: bool = True,
) -> tuple[dict, dict[str, str]]:
    """Lògica compartida per candles/ohlcv. Retorna (content_dict, headers_dict)."""
    store = _require_candle_store()
    symbol = _normalize_symbol(symbol)
    policy = _resolve_policy(symbol)
    end = datetime.now(CANONICAL_TIMEZONE)
    start, end = resolve_candle_range(end=end, limit=limit, since_epoch=since, to_epoch=to, tz=CANONICAL_TIMEZONE)
    since_ts = int(start.timestamp())
    to_ts = int(end.timestamp())

    use_p7 = since is not None or to is not None
    if use_p7 and _fallback_provider is not None:
        from application.services.candle_stitching_service import get_candles_with_source  # lazy: evita carregar P7 si no es demana rang

        def _compat_fn(s: str) -> str:
            return "PASS" if policy.mixed_allowed else "FAIL"

        try:
            r, source, cutover_ts = await get_candles_with_source(
                symbol=symbol,
                since_ts=since_ts,
                to_ts=to_ts,
                limit=limit,
                csv_store=store,
                fallback_provider=_fallback_provider,
                get_compat_status_fn=_compat_fn,
            )
            resp = _map_ohlcv_response(r, symbol, start, end)
            headers = _build_p5_headers(r, start, end, symbol, source=source, cutover_ts=cutover_ts, policy=policy)
            return resp.model_dump(mode="json"), headers
        except ValueError as e:
            if "MIXED_SOURCE_NOT_ALLOWED" in str(e):
                _http_error(
                    422,
                    MIXED_SOURCE_NOT_ALLOWED,
                    "Mixed source not allowed for this symbol/range (compat_probe not PASS)",
                )
            raise
        except RuntimeError as e:
            if "FALLBACK_NOT_AVAILABLE" in str(e):
                _http_error(503, CANDLE_STORE_NOT_AVAILABLE, "Fallback provider not available")
            raise
    elif use_p7 and _fallback_provider is None:
        cutover_dt = store.get_earliest_timestamp(symbol)
        cutover_ts = int(cutover_dt.timestamp()) if cutover_dt else None
        from application.services.candle_stitching_service import resolve_source  # lazy: evita carregar P7 si no es demana rang

        compat_status = "PASS" if policy.mixed_allowed else "FAIL"
        source = resolve_source(since_ts, to_ts, cutover_ts, compat_status)
        if source == "deny":
            _http_error(
                422,
                MIXED_SOURCE_NOT_ALLOWED,
                "Mixed source not allowed for this symbol/range (compat_probe not PASS)",
            )
        if source in ("fallback", "mixed"):
            _http_error(503, CANDLE_STORE_NOT_AVAILABLE, "Fallback provider not available")

    r = read_candles(store, symbol=symbol, start=start, end=end, validate_gaps=validate_gaps)
    read_through_stats = None
    if _primary_backfill_provider is not None:
        enabled = os.getenv(ENABLE_READ_THROUGH_ENV, "").strip() == "1"
        if enabled:
            from application.services.read_through_service import maybe_fill_gaps_response_only

            def _compat_fn(s: str) -> str:
                p = _resolve_policy(s)
                return "PASS" if p.mixed_allowed else "FAIL"

            max_missing = int(os.getenv(READ_THROUGH_MAX_MISSING_ENV, str(DEFAULT_READ_THROUGH_MAX_MISSING)))
            timeout_s = float(os.getenv(READ_THROUGH_TIMEOUT_ENV, str(DEFAULT_READ_THROUGH_TIMEOUT_S)))
            r, read_through_stats = await maybe_fill_gaps_response_only(
                symbol=symbol,
                candle_range=r,
                primary_provider=_primary_backfill_provider,
                fallback_provider=_fallback_provider,
                get_compat_status_fn=_compat_fn,
                enabled=True,
                max_missing=max_missing,
                timeout_s=timeout_s,
            )
    resp = _map_ohlcv_response(r, symbol, start, end)
    headers = _build_p5_headers(r, start, end, symbol, source="primary", read_through_stats=read_through_stats, policy=policy)
    return resp.model_dump(mode="json"), headers


async def _read_candles_response(
    symbol: str,
    limit: int,
    since: Optional[int],
    to: Optional[int],
    validate_gaps: bool = True,
) -> JSONResponse:
    """Wrapper que retorna JSONResponse (per rutes)."""
    content, headers = await _compute_ohlcv_content(symbol, limit, since, to, validate_gaps)
    return JSONResponse(content=content, headers=headers)


async def _local_compute_ohlcv(
    symbol: str,
    tf: str,
    limit: int,
    since: Optional[int],
    to: Optional[int],
) -> tuple[dict, dict[str, str]]:
    """Per LocalDataLayerReader. tf validat per la ruta."""
    return await _compute_ohlcv_content(symbol, limit, since, to, validate_gaps=True)


@data_router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    tf: str = Query(default=SUPPORTED_TIMEFRAME),
    since: Optional[int] = Query(None),
    to: Optional[int] = Query(None),
    limit: int = Query(default=DEFAULT_OHLCV_LIMIT, ge=1, le=MAX_CANDLES_LIMIT),
):
    """Candles OHLCV per símbol (path). Compatible amb test_rest_smoke."""
    if tf != SUPPORTED_TIMEFRAME:
        _http_error(422, TIMEFRAME_NOT_SUPPORTED, f"Only {SUPPORTED_TIMEFRAME} timeframe supported")
    if _data_layer_reader is not None:
        try:
            body, headers = await _data_layer_reader.get_ohlcv(
                symbol=symbol, tf=tf, limit=limit, since=since, to=to
            )
            return JSONResponse(content=body, headers=headers)
        except Exception as e:
            from packages.shared.realtime_datalayer_client import RealtimeDataLayerError
            if isinstance(e, RealtimeDataLayerError):
                logger.warning("data_layer_reader (HTTP) failed: %s", e)
                _http_error(503, DATA_STATUS_NOT_AVAILABLE, f"Realtime Data Layer unavailable: {e}")
            raise
    try:
        return await _read_candles_response(symbol, limit, since, to, validate_gaps=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_ohlcv %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


def _local_compute_coverage(symbol: str, resolution: str) -> dict:
    """P5: Data coverage per symbol. Per LocalDataLayerReader."""
    store = _require_candle_store()
    symbol = _normalize_symbol(symbol)
    policy = _resolve_policy(symbol)

    earliest_ts = None
    latest_ts = None
    earliest_dt = store.get_earliest_timestamp(symbol)
    latest_dt = store.get_last_timestamp(symbol)
    if earliest_dt:
        earliest_ts = int(earliest_dt.timestamp())
    if latest_dt:
        latest_ts = int(latest_dt.timestamp())

    end = datetime.now(CANONICAL_TIMEZONE)
    start_72h = end - timedelta(hours=72)
    r = read_candles(store, symbol=symbol, start=start_72h, end=end, validate_gaps=True)
    report = GapValidator.validate(r.candles, start_72h, end, symbol=symbol)
    max_gap_s = max(g.count * 60 for g in report.gaps) if report.gaps else 0

    return {
        "symbol": symbol,
        "resolution": resolution,
        "earliest_ts": earliest_ts,
        "latest_ts": latest_ts,
        "window_72h": {
            "expected_minutes": report.expected_count,
            "candles": report.actual_count,
            "missing_minutes": report.missing_count,
            "max_gap_s": max_gap_s,
        },
        "source": policy.primary_source,
        "notes": "UTC start-of-minute, closed only",
    }


@data_router.get("/coverage")
async def get_coverage(
    symbol: str = Query(..., description="Symbol (e.g. EURUSD)"),
    resolution: str = Query(default="1m", description="Resolution (only 1m supported)"),
):
    """
    P5: Data coverage per symbol — earliest/latest ts del store, window_72h stats.
    """
    if resolution != "1m":
        _http_error(422, TIMEFRAME_NOT_SUPPORTED, f"Only 1m resolution supported")
    if _data_layer_reader is not None:
        try:
            return _data_layer_reader.get_coverage(symbol=symbol, resolution=resolution)
        except Exception as e:
            from packages.shared.realtime_datalayer_client import RealtimeDataLayerError
            if isinstance(e, RealtimeDataLayerError):
                logger.warning("data_layer_reader (HTTP) failed: %s", e)
                _http_error(503, DATA_STATUS_NOT_AVAILABLE, f"Realtime Data Layer unavailable: {e}")
            raise
    return _local_compute_coverage(symbol=symbol, resolution=resolution)


def _local_compute_data_status() -> dict:
    """P7c: Data Layer telemetria. Per LocalDataLayerReader."""
    from application.data.data_layer_lifecycle import get_data_layer_status as get_lifecycle
    from application.data.data_layer_metrics import get_data_layer_metrics  # lazy: evita carregar data_layer si no hi ha pipeline

    lifecycle_status, lifecycle_reason = get_lifecycle()
    metrics = get_data_layer_metrics()

    # Habilitat però encara sense mètriques (initializing) → 200 amb data_layer_status=initializing
    if metrics is None:
        if lifecycle_status in ("initializing", "warming_up", "ready", "degraded"):
            return {
                "data_layer_status": lifecycle_status,
                "initializing_reason": lifecycle_reason or "metrics not yet wired",
                "symbols": {},
                "ws_reconnects": 0,
                "server_time": datetime.now(timezone.utc).isoformat(),
                "canonical_tz": CANONICAL_TIMEZONE_NAME,
                "mode": _mode,
                "market_data_env": _market_data_env,
                "write_mode": _data_layer_write_mode,
                "ingest_enabled": _ostium_ingest_enabled,
                "ingest_poll_s": _ostium_ingest_poll_s,
            }
        _http_error(503, DATA_STATUS_NOT_AVAILABLE, "Data Layer metrics not available (no pipeline)")

    snapshot = metrics.snapshot()
    symbols_data = dict(snapshot["symbols"])

    # Enriquir per símbol: ingest_allowed, primary_eligible, quarantined, quarantine_reason
    if _ostium_ingest_enabled:
        from application.data.ostium_compat_registry import get_ostium_primary_allowed
        from application.data.ostium_symbol_policy import (
            get_ostium_ingest_symbols,
            get_ostium_quarantine,
            is_ostium_quarantined,
        )
        ingest_symbols = set(get_ostium_ingest_symbols())
        quarantine_symbols = get_ostium_quarantine()
        primary_by_symbol = {}
        for sym, m in list(symbols_data.items()):
            config_quarantine = sym in quarantine_symbols
            degraded = m.get("symbol_state") == "DEGRADED"
            dupes = m.get("duplicates", 0) or m.get("ts_step_errors", 0)
            runtime_quarantine = degraded and dupes > 0
            quarantined = config_quarantine or runtime_quarantine
            if config_quarantine:
                reason = "config"
            elif runtime_quarantine:
                reason = m.get("degrade_reason") or "DEGRADED"
            else:
                reason = ""
            m["ingest_allowed"] = sym in ingest_symbols and not config_quarantine
            m["primary_eligible"] = get_ostium_primary_allowed(sym)
            m["quarantined"] = quarantined
            m["quarantine_reason"] = reason
            primary_by_symbol[sym] = m["primary_eligible"]
        # Afegir símbols quarantined (config) que no estan al snapshot
        for sym in sorted(quarantine_symbols):
            if sym not in symbols_data:
                symbols_data[sym] = {
                    "ingest_allowed": False,
                    "primary_eligible": False,
                    "quarantined": True,
                    "quarantine_reason": "config",
                }
            else:
                symbols_data[sym]["ingest_allowed"] = False
                symbols_data[sym]["primary_eligible"] = False
                symbols_data[sym]["quarantined"] = True
                symbols_data[sym]["quarantine_reason"] = symbols_data[sym].get("quarantine_reason") or "config"
            primary_by_symbol[sym] = False

    result = {
        "data_layer_status": lifecycle_status,
        "symbols": symbols_data,
        "ws_reconnects": snapshot["ws_reconnects"],
        "server_time": datetime.now(timezone.utc).isoformat(),
        "canonical_tz": CANONICAL_TIMEZONE_NAME,
        "mode": _mode,
        "market_data_env": _market_data_env,
        "write_mode": _data_layer_write_mode,
        "ingest_enabled": _ostium_ingest_enabled,
        "ingest_poll_s": _ostium_ingest_poll_s,
    }
    if lifecycle_status == "initializing" and lifecycle_reason:
        result["initializing_reason"] = lifecycle_reason
    if _ostium_ingest_enabled:
        result["ingest_source"] = "ostium_realtime"
        result["primary_allowed_by_symbol"] = primary_by_symbol if primary_by_symbol else {
            sym: s.get("primary_eligible", False) for sym, s in symbols_data.items()
        }
    # Tick recorder (forense): enabled, outdir, last_tick_ts, lines_written, dupes_detected
    from application.services.ostium_tick_recorder import get_ostium_tick_recorder  # lazy
    tick_rec = get_ostium_tick_recorder()
    result["tick_recorder"] = tick_rec.get_status() if tick_rec else {"enabled": False}
    return result


@data_router.get("/data_status")
async def get_data_status():
    """
    P7c: Data Layer telemetria (counters, last_ts per símbol).
    200 sempre que el servei estigui viu; data_layer_status=initializing durant arrencada.
    503 només quan Data Layer mai s'ha habilitat (no pipeline).
    """
    if _data_layer_reader is not None:
        try:
            return _data_layer_reader.get_data_status()
        except Exception as e:
            from packages.shared.realtime_datalayer_client import RealtimeDataLayerError
            if isinstance(e, RealtimeDataLayerError):
                logger.warning("data_layer_reader (HTTP) failed: %s", e)
                _http_error(503, DATA_STATUS_NOT_AVAILABLE, f"Realtime Data Layer unavailable: {e}")
            raise
    return _local_compute_data_status()


@data_router.get("/candles")
async def get_candles(
    symbol: str = Query(...),
    timeframe: str = Query(default=SUPPORTED_TIMEFRAME),
    limit: int = Query(default=DEFAULT_CANDLES_LIMIT, ge=1, le=MAX_CANDLES_LIMIT),
    since: Optional[int] = Query(None),
    to: Optional[int] = Query(None),
):
    """Candles OHLCV (query param symbol). Sense venue (candle_store)."""
    if timeframe != SUPPORTED_TIMEFRAME:
        _http_error(422, TIMEFRAME_NOT_SUPPORTED, f"Only {SUPPORTED_TIMEFRAME} timeframe supported")
    if _data_layer_reader is not None:
        try:
            body, headers = await _data_layer_reader.get_ohlcv(
                symbol=symbol, tf=timeframe, limit=limit, since=since, to=to
            )
            return JSONResponse(content=body, headers=headers)
        except Exception as e:
            from packages.shared.realtime_datalayer_client import RealtimeDataLayerError
            if isinstance(e, RealtimeDataLayerError):
                logger.warning("data_layer_reader (HTTP) failed: %s", e)
                _http_error(503, DATA_STATUS_NOT_AVAILABLE, f"Realtime Data Layer unavailable: {e}")
            raise
    try:
        return await _read_candles_response(symbol, limit, since, to, validate_gaps=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_candles %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Trading ============


@trading_router.get("/balance", response_model=BalanceResponse)
async def get_balance(venue: str = Query(...)):
    """Balance compte."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        bal = await adapter.get_balance()
        return _map_balance_response(bal)
    except Exception as e:
        logger.error("get_balance %s: %s", venue, e)
        raise HTTPException(status_code=500, detail=str(e))


@trading_router.get("/positions", response_model=PositionsResponse)
async def get_positions(venue: str = Query(...)):
    """Posicions obertes amb mark_price i unrealized_pnl."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        positions = await adapter.get_open_positions()
        # Mark price: preferir el de la posició (Lighter retorna unrealized_pnl oficial → derivem mark_price)
        # Fallback: order book mid del nostre price feed
        mark_prices: dict[str, float] = {}
        for p in positions:
            if p.symbol not in mark_prices:
                if getattr(p, "mark_price", None) is not None:
                    mark_prices[p.symbol] = p.mark_price
                else:
                    try:
                        px = await adapter.get_latest_price(p.symbol)
                        mark_prices[p.symbol] = px.mid
                    except Exception as e:
                        logger.warning("get_positions: no mark price for %s: %s", p.symbol, e)
        ratio = _get_paper_maintenance_ratio()
        return _map_positions_response(venue, positions, mark_prices, maintenance_margin_ratio=ratio)
    except Exception as e:
        logger.error("get_positions %s: %s", venue, e)
        raise HTTPException(status_code=500, detail=str(e))


@trading_router.get("/trades", response_model=TradesResponse)
async def get_trades(
    venue: str = Query(..., description="Venue (lighter)"),
    symbol: Optional[str] = Query(None, description="Filter per symbol"),
    since: Optional[int] = Query(None, description="Epoch seconds (inclusive)"),
    to: Optional[int] = Query(None, description="Epoch seconds (exclusive)"),
    limit: int = Query(default=DEFAULT_TRADES_LIMIT, ge=1, le=MAX_TRADES_LIMIT, description="Max fills"),
):
    """Trade history (fills) — CCXT/Freqtrade compatible."""
    adapter = _get_adapter_or_http_error(venue)
    since_dt = datetime.fromtimestamp(since, tz=timezone.utc) if since else None
    to_dt = datetime.fromtimestamp(to, tz=timezone.utc) if to else None
    try:
        fills = await adapter.get_trade_history(
            symbol=symbol,
            since=since_dt,
            to=to_dt,
            limit=limit,
        )
        items = [
            TradeItem(
                trade_id=f.trade_id,
                symbol=f.symbol,
                side=f.side,
                price=f.price,
                size=f.size,
                fee=f.fee,
                fee_currency=f.fee_currency,
                timestamp=f.timestamp.isoformat() if f.timestamp else "",
                order_id=f.order_id,
                position_id=f.position_id,
                close_reason=getattr(f, "close_reason", None),
            )
            for f in fills
        ]
        return TradesResponse(trades=items)
    except Exception as e:
        logger.error("get_trades %s: %s", venue, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Orders ============


async def _do_order_open(req: OrderOpenRequest) -> OrderOpenResponse:
    """Lògica comuna per obrir posició. Delega a TradingCore (Phase E)."""
    from application.trading.trading_core import (
        TradingCore,
        AdapterNotAvailableError,
        VenueNotConfiguredError,
    )
    from application.errors import DataQualityGateBadError, LiveTradingDisabledError, RiskLimitExceededError
    from application.api.error_codes import LIVE_TRADING_DISABLED, RISK_LIMIT_EXCEEDED
    from application.services.position_guard import PositionAlreadyOpenError

    core = TradingCore(
        adapter_factory=_adapter_factory,
        data_layer_reader=_data_layer_reader,
        known_venues=list(KNOWN_VENUES),
        mode=_mode,
    )
    try:
        result = await core.open_order(req)
    except DataQualityGateBadError as e:
        _http_error(
            422,
            DATA_QUALITY_GATE_BAD,
            f"NO_TRADE: quality gate BAD for {e.symbol} — {e.reason}",
        )
    except LiveTradingDisabledError as e:
        _http_error(403, LIVE_TRADING_DISABLED, str(e))
    except RiskLimitExceededError as e:
        _http_error(422, RISK_LIMIT_EXCEEDED, str(e))
    except PositionAlreadyOpenError as e:
        _http_error(409, POSITION_ALREADY_OPEN, str(e))
    except AdapterNotAvailableError as e:
        _http_error(503, ADAPTER_NOT_AVAILABLE, str(e))
    except VenueNotConfiguredError as e:
        _http_error(422, VENUE_NOT_CONFIGURED, str(e))
    except MarketNotFoundError as e:
        _http_error(404, SYMBOL_NOT_FOUND, str(e))
    except Exception as e:
        logger.error("order_open %s %s: %s", req.venue, req.symbol, e)
        raise HTTPException(status_code=500, detail=str(e))
    return OrderOpenResponse(
        success=result.success,
        position_id=result.position_id,
        order_id=result.order_id,
        executed_price=result.executed_price,
        executed_size=result.executed_size,
        tx_hash=result.tx_hash,
    )


async def _do_order_close(req: OrderCloseRequest) -> OrderCloseResponse:
    """Lògica comuna per tancar posició. Delega a TradingCore (Phase E)."""
    from application.trading.trading_core import (
        TradingCore,
        AdapterNotAvailableError,
        VenueNotConfiguredError,
    )

    core = TradingCore(
        adapter_factory=_adapter_factory,
        data_layer_reader=_data_layer_reader,
        known_venues=list(KNOWN_VENUES),
    )
    try:
        result = await core.close_order(req)
        return OrderCloseResponse(success=result.success)
    except AdapterNotAvailableError as e:
        _http_error(503, ADAPTER_NOT_AVAILABLE, str(e))
    except VenueNotConfiguredError as e:
        _http_error(422, VENUE_NOT_CONFIGURED, str(e))
    except PositionNotFoundError as e:
        _http_error(404, POSITION_NOT_FOUND, str(e))
    except Exception as e:
        logger.error("order_close %s %s: %s", req.venue, req.position_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@trading_router.post("/orders/open", response_model=OrderOpenResponse)
async def order_open(body: OrderOpenRequest = Body(...)):
    """Obrir posició. JSON body. side: long|short."""
    return await _do_order_open(body)


@trading_router.post("/orders/close", response_model=OrderCloseResponse)
async def order_close(body: OrderCloseRequest = Body(...)):
    """Tancar posició. JSON body. percent dins (0, 100]."""
    return await _do_order_close(body)


@trading_router.get("/preflight")
async def get_preflight(
    venue: str = Query(default="paper", description="Venue a comprovar (paper, ostium, lighter)"),
    symbol: str = Query(default="EURUSD", description="Símbol per data_quality check"),
):
    """
    Phase I: Preflight check — retorna l'estat del sistema per operar.

    Comprova:
    - mode i venue configurats
    - live_enabled (ENABLE_LIVE_TRADING)
    - data_quality per symbol (si data_layer_reader disponible)
    - ostium_health (si venue==ostium i adapter disponible)
    - ready: True si tots els checks OK

    Retorna 200 sempre (may_trade camp indica si és segur operar).
    """
    from application.config.live_guards_config import (
        enable_live_trading_from_env,
        max_collateral_usd_from_env,
        max_leverage_from_env,
        live_symbol_allowlist_from_env,
    )

    sym_upper = symbol.upper()
    result: dict = {
        "venue": _venue,
        "requested_venue": venue,
        "mode": _mode,
        "live_enabled": enable_live_trading_from_env(),
        "risk_caps": {
            "max_collateral_usd": max_collateral_usd_from_env(),
            "max_leverage": max_leverage_from_env(),
            "live_symbol_allowlist": live_symbol_allowlist_from_env(),
        },
        "symbol": sym_upper,
        "checks": {},
        "ready": False,
    }

    checks: dict = {}

    # Check: data_quality
    if _data_layer_reader is not None:
        try:
            from application.services.data_quality_guard import assert_data_quality_ok
            await assert_data_quality_ok(_data_layer_reader, symbol=sym_upper)
            checks["data_quality"] = {"ok": True}
        except Exception as e:
            checks["data_quality"] = {"ok": False, "reason": str(e)}
    else:
        checks["data_quality"] = {"ok": True, "note": "no data_layer_reader (skip)"}

    # Check: venue_adapter + health
    adapter = _adapter_factory(venue) if _adapter_factory else None
    if adapter is not None:
        try:
            healthy = await adapter.health_check()
            checks["venue_health"] = {"ok": healthy, "venue": venue}
        except Exception as e:
            checks["venue_health"] = {"ok": False, "error": str(e)}
    else:
        checks["venue_health"] = {"ok": False, "note": f"adapter '{venue}' no disponible"}

    # Check: live_enabled (si mode==live)
    if str(_mode).lower() == "live":
        live_ok = enable_live_trading_from_env()
        checks["live_enabled"] = {"ok": live_ok, "note": "ENABLE_LIVE_TRADING" if not live_ok else ""}
    else:
        checks["live_enabled"] = {"ok": True, "note": f"mode={_mode} (no live)"}

    result["checks"] = checks
    result["ready"] = all(c.get("ok", False) for c in checks.values())

    return result


# ============ Internal helpers (SRP) ============


def _require_candle_store():
    """Retorna candle_store o llança 503 + CANDLE_STORE_NOT_AVAILABLE."""
    if _candle_store is None:
        _http_error(503, CANDLE_STORE_NOT_AVAILABLE, "Candle store not available")
    return _candle_store


def _normalize_symbol(symbol: str) -> str:
    """Normalitza símbol (uppercase)."""
    return symbol.upper()


def _map_ohlcv_response(candle_range: Any, symbol: str, start: datetime, end: datetime) -> OHLCVResponse:
    """Mapa CandleRange a OHLCVResponse."""
    candles = [
        OHLCVCandle(
            ts=int(c.timestamp.timestamp()),
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candle_range.candles
    ]
    return OHLCVResponse(
        symbol=symbol,
        timeframe=SUPPORTED_TIMEFRAME,
        start=start,
        end=end,
        count=len(candles),
        is_complete=candle_range.is_complete,
        missing_count=candle_range.missing_count,
        candles=candles,
    )


def _map_balance_response(bal: Any) -> BalanceResponse:
    """Mapa Balance domain a BalanceResponse."""
    return BalanceResponse(
        usdc=bal.usdc,
        available_margin=bal.available_margin,
        used_margin=bal.used_margin,
        total_equity=bal.total_equity,
        margin_usage_percent=bal.margin_usage_percent,
    )


def _compute_liquidation_price(
    open_price: float,
    notional: float,
    collateral: float,
    is_long: bool,
    maintenance_margin_ratio: float,
) -> Optional[float]:
    """P3.0: Liquidation price (determinista). equity = collateral + unrealized_pnl."""
    if notional <= 0 or open_price <= 0:
        return None
    size = notional / open_price
    maintenance_margin = notional * maintenance_margin_ratio
    # equity = collateral + (liq_price - open_price)*size (long) or (open_price - liq_price)*size (short)
    # At liquidation: equity = maintenance_margin
    if is_long:
        # collateral + (liq - open)*size = maintenance_margin
        liq_price = open_price + (maintenance_margin - collateral) / size
    else:
        # collateral + (open - liq)*size = maintenance_margin
        liq_price = open_price - (maintenance_margin - collateral) / size
    return liq_price


def _map_positions_response(
    venue: str,
    positions: list,
    mark_prices: Optional[dict[str, float]] = None,
    maintenance_margin_ratio: float = 0.05,
) -> PositionsResponse:
    """Mapa llista Position domain a PositionsResponse amb mark_price, sl/tp, liquidation_price."""
    mark_prices = mark_prices or {}
    items = []
    for p in positions:
        size = (p.notional or 0) / (p.open_price or 1)
        mark_price = mark_prices.get(p.symbol)
        unrealized_pnl: Optional[float] = getattr(p, "unrealized_pnl", None)
        if unrealized_pnl is None and mark_price is not None and p.open_price:
            if p.is_long:
                unrealized_pnl = (mark_price - p.open_price) * size
            else:
                unrealized_pnl = (p.open_price - mark_price) * size
        liq_price = _compute_liquidation_price(
            p.open_price, p.notional or 0, p.collateral, p.is_long, maintenance_margin_ratio
        )
        pid = f"{venue}:{p.venue_position_id}" if getattr(p, "venue_position_id", None) else f"{venue}:{p.pair_id}"
        items.append(
            PositionItem(
                position_id=pid,
                symbol=p.symbol,
                side="LONG" if p.is_long else "SHORT",
                size=size,
                notional=p.notional or 0,
                open_price=p.open_price,
                entry_time=p.open_time.isoformat() if p.open_time else "",
                mark_price=mark_price,
                unrealized_pnl=unrealized_pnl,
                sl_price=getattr(p, "sl_price", None),
                tp_price=getattr(p, "tp_price", None),
                liquidation_price=liq_price,
            )
        )
    return PositionsResponse(positions=items)


# Registrar rutes (després que els decorators @data_router / @trading_router hagin executat)
_build_routers()
