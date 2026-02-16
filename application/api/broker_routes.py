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
    VENUE_NOT_CONFIGURED,
    TIMEFRAME_NOT_SUPPORTED,
    SYMBOL_NOT_FOUND,
    POSITION_NOT_FOUND,
    MIXED_SOURCE_NOT_ALLOWED,
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

router = APIRouter(prefix="/api/v1/broker", tags=["broker"])

_UNSET = object()

# DI
_candle_store: Optional[Any] = None
_adapter_factory: Optional[Callable[[str], Any]] = None
_mode: str = "backtest"
_venue: str = "gtrade"
_market_data_env: str = "mainnet"
_market_data_source: str = "n/a"  # fake|real|n/a — visible a GET /mode i freqtrade_runner
_fallback_provider: Optional[Any] = None  # P7: DukascopyBackfillProvider (read-only)


def set_broker_deps(
    candle_store: Any = _UNSET,
    adapter_factory: Any = _UNSET,
    mode: str = _UNSET,
    venue: str = _UNSET,
    market_data_env: str = _UNSET,
    market_data_source: str = _UNSET,
    fallback_provider: Any = _UNSET,
) -> None:
    """Inject dependencies for broker routes."""
    global _candle_store, _adapter_factory, _mode, _venue, _market_data_env, _market_data_source, _fallback_provider
    if candle_store is not _UNSET:
        _candle_store = candle_store
    if adapter_factory is not _UNSET:
        _adapter_factory = adapter_factory
    if fallback_provider is not _UNSET:
        _fallback_provider = fallback_provider
    if mode is not _UNSET:
        _mode = mode
    if venue is not _UNSET:
        _venue = venue
    if market_data_env is not _UNSET:
        _market_data_env = market_data_env
    if market_data_source is not _UNSET:
        _market_data_source = market_data_source
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


@router.get("/health", response_model=HealthResponse)
async def get_health():
    """Health check."""
    return HealthResponse(
        status="ok",
        mode=_mode,
        venue=_venue,
        timestamp=datetime.now(),
    )


@router.get("/mode", response_model=ModeResponse)
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


@router.get("/venues")
async def get_venues():
    """Llista venues realment disponibles segons config/wiring actual."""
    venues = _get_available_venues()
    if not venues and _adapter_factory is None:
        logger.debug("adapter_factory not configured; /broker/venues returns []")
    return {"venues": venues}


@router.get("/pairs", response_model=PairsResponse)
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


@router.get("/price/latest", response_model=PriceLatestResponse)
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


def _build_p5_headers(
    candle_range: Any,
    start: datetime,
    end: datetime,
    symbol: str,
    source: str = "primary",
    cutover_ts: Optional[int] = None,
) -> dict[str, str]:
    """P5/P7: Headers d'observabilitat OHLCV (coverage, gaps, repair)."""
    report = GapValidator.validate(
        candle_range.candles, start, end, symbol=symbol
    )
    max_gap_s = (
        max(g.count * 60 for g in report.gaps)
        if report.gaps
        else 0
    )
    repair_at, repair_filled, repair_symbol = get_last_repair()
    repair_status = "applied" if repair_filled > 0 and repair_symbol == symbol else "none"

    headers: dict[str, str] = {
        "X-Data-Source": source,
        "X-Data-Coverage-From": str(int(start.timestamp())),
        "X-Data-Coverage-To": str(int(end.timestamp())),
        "X-Data-Missing-Minutes": str(report.missing_count),
        "X-Data-Max-Gap-S": str(max_gap_s),
        "X-Data-Repair": repair_status,
        "X-Data-Repair-Filled": str(repair_filled if repair_status == "applied" else 0),
    }
    if source == "mixed" and cutover_ts is not None:
        headers["X-Data-Cutover-Ts"] = str(cutover_ts)
    return headers


async def _read_candles_response(
    symbol: str,
    limit: int,
    since: Optional[int],
    to: Optional[int],
    validate_gaps: bool = True,
) -> JSONResponse:
    """Lògica compartida per candles/ohlcv. P7: rang explícit (since/to) → stitching."""
    store = _require_candle_store()
    symbol = _normalize_symbol(symbol)
    end = datetime.now(CANONICAL_TIMEZONE)
    start, end = resolve_candle_range(end=end, limit=limit, since_epoch=since, to_epoch=to, tz=CANONICAL_TIMEZONE)
    since_ts = int(start.timestamp())
    to_ts = int(end.timestamp())

    use_p7 = since is not None or to is not None
    if use_p7 and _fallback_provider is not None:
        from application.data.compat_registry import get_compat_status  # lazy: evita carregar P7 si no es demana rang
        from application.services.candle_stitching_service import get_candles_with_source  # lazy: evita carregar P7 si no es demana rang

        try:
            r, source, cutover_ts = await get_candles_with_source(
                symbol=symbol,
                since_ts=since_ts,
                to_ts=to_ts,
                limit=limit,
                csv_store=store,
                fallback_provider=_fallback_provider,
                get_compat_status_fn=lambda s: get_compat_status(s),
            )
            resp = _map_ohlcv_response(r, symbol, start, end)
            headers = _build_p5_headers(r, start, end, symbol, source=source, cutover_ts=cutover_ts)
            return JSONResponse(content=resp.model_dump(mode="json"), headers=headers)
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
        from application.data.compat_registry import get_compat_status  # lazy: evita carregar P7 si no es demana rang
        source = resolve_source(since_ts, to_ts, cutover_ts, get_compat_status(symbol))
        if source == "deny":
            _http_error(
                422,
                MIXED_SOURCE_NOT_ALLOWED,
                "Mixed source not allowed for this symbol/range (compat_probe not PASS)",
            )
        if source in ("fallback", "mixed"):
            _http_error(503, CANDLE_STORE_NOT_AVAILABLE, "Fallback provider not available")

    r = read_candles(store, symbol=symbol, start=start, end=end, validate_gaps=validate_gaps)
    resp = _map_ohlcv_response(r, symbol, start, end)
    headers = _build_p5_headers(r, start, end, symbol, source="primary")
    return JSONResponse(content=resp.model_dump(mode="json"), headers=headers)


@router.get("/ohlcv/{symbol}")
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
    try:
        return await _read_candles_response(symbol, limit, since, to, validate_gaps=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_ohlcv %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coverage")
async def get_coverage(
    symbol: str = Query(..., description="Symbol (e.g. EURUSD)"),
    resolution: str = Query(default="1m", description="Resolution (only 1m supported)"),
):
    """
    P5: Data coverage per symbol — earliest/latest ts del store, window_72h stats.
    """
    if resolution != "1m":
        _http_error(422, TIMEFRAME_NOT_SUPPORTED, f"Only 1m resolution supported")
    store = _require_candle_store()
    symbol = _normalize_symbol(symbol)

    earliest_ts = None
    latest_ts = None
    earliest_dt = store.get_earliest_timestamp(symbol)
    latest_dt = store.get_last_timestamp(symbol)
    if earliest_dt:
        earliest_ts = int(earliest_dt.timestamp())
    if latest_dt:
        latest_ts = int(latest_dt.timestamp())

    # window_72h: computed from store read_range
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
        "source": "primary",
        "notes": "UTC start-of-minute, closed only",
    }


@router.get("/data_status")
async def get_data_status():
    """
    P7c: Data Layer telemetria (counters, last_ts per símbol).
    503 si metrics no wired (sense pipeline).
    """
    from application.data.data_layer_metrics import get_data_layer_metrics  # lazy: evita carregar data_layer si no hi ha pipeline

    metrics = get_data_layer_metrics()
    if metrics is None:
        _http_error(503, DATA_STATUS_NOT_AVAILABLE, "Data Layer metrics not available (no pipeline)")

    snapshot = metrics.snapshot()
    return {
        "symbols": snapshot["symbols"],
        "ws_reconnects": snapshot["ws_reconnects"],
        "server_time": datetime.now(timezone.utc).isoformat(),
        "canonical_tz": CANONICAL_TIMEZONE_NAME,
        "mode": _mode,
        "market_data_env": _market_data_env,
    }


@router.get("/candles")
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
    try:
        return await _read_candles_response(symbol, limit, since, to, validate_gaps=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_candles %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ Trading ============


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(venue: str = Query(...)):
    """Balance compte."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        bal = await adapter.get_balance()
        return _map_balance_response(bal)
    except Exception as e:
        logger.error("get_balance %s: %s", venue, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=PositionsResponse)
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


@router.get("/trades", response_model=TradesResponse)
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
    """Lògica comuna per obrir posició. Validacions ja fetes al model."""
    adapter = _get_adapter_or_http_error(req.venue)
    is_long = req.side.lower() == "long"
    try:
        result = await adapter.open_position(
            symbol=req.symbol,
            is_long=is_long,
            collateral=req.collateral,
            leverage=req.leverage,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            client_order_id=None,
        )
        # P3.1: Garantir position_id amb prefix venue per paper (consistent amb GET /positions)
        pid = result.position_id or ""
        if pid and req.venue == "paper" and ":" not in pid:
            pid = f"paper:{pid}"
        return OrderOpenResponse(
            success=result.success,
            position_id=pid,
            order_id=result.order_id or "",
            executed_price=result.executed_price or 0,
            executed_size=result.executed_size or 0,
            tx_hash=getattr(result, "tx_hash", "") or "",
        )
    except MarketNotFoundError as e:
        _http_error(404, SYMBOL_NOT_FOUND, str(e))
    except Exception as e:
        logger.error("order_open %s %s: %s", req.venue, req.symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


async def _do_order_close(req: OrderCloseRequest) -> OrderCloseResponse:
    """Lògica comuna per tancar posició. Validacions ja fetes al model."""
    adapter = _get_adapter_or_http_error(req.venue)
    position_id = req.position_id
    if ":" not in position_id and req.venue == "lighter":
        position_id = f"lighter:{position_id}"
    try:
        ok = await adapter.close_position(position_id, percent=req.percent)
        return OrderCloseResponse(success=ok)
    except PositionNotFoundError as e:
        _http_error(404, POSITION_NOT_FOUND, str(e))
    except Exception as e:
        logger.error("order_close %s %s: %s", req.venue, position_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/open", response_model=OrderOpenResponse)
async def order_open(body: OrderOpenRequest = Body(...)):
    """Obrir posició. JSON body. side: long|short."""
    return await _do_order_open(body)


@router.post("/orders/close", response_model=OrderCloseResponse)
async def order_close(body: OrderCloseRequest = Body(...)):
    """Tancar posició. JSON body. percent dins (0, 100]."""
    return await _do_order_close(body)


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
