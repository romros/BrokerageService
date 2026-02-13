"""
Broker API - REST endpoints unificats

Prefix: /api/v1/broker
POST /orders/open i /orders/close amb JSON body.
"""

from datetime import datetime
from typing import Optional, List, Callable, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

from application.api.candle_helpers import resolve_candle_range, read_candles
from application.api.models import (
    HealthResponse,
    ModeResponse,
    OHLCVCandle,
    OHLCVResponse,
    BalanceResponse,
    OrderOpenRequest,
    OrderCloseRequest,
)
from domain.errors import PositionNotFoundError, MarketNotFoundError
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


def set_broker_deps(
    candle_store: Any = _UNSET,
    adapter_factory: Any = _UNSET,
    mode: str = _UNSET,
    venue: str = _UNSET,
    market_data_env: str = _UNSET,
) -> None:
    """Inject dependencies for broker routes."""
    global _candle_store, _adapter_factory, _mode, _venue, _market_data_env
    if candle_store is not _UNSET:
        _candle_store = candle_store
    if adapter_factory is not _UNSET:
        _adapter_factory = adapter_factory
    if mode is not _UNSET:
        _mode = mode
    if venue is not _UNSET:
        _venue = venue
    if market_data_env is not _UNSET:
        _market_data_env = market_data_env
    logger.info(
        f"Broker API deps: mode={_mode}, venue={_venue}, market_data_env={_market_data_env}, "
        f"adapter_factory={'set' if _adapter_factory else 'None'}"
    )


def _http_error(status_code: int, code: str, detail: str):
    """Llança HTTPException amb format {detail, code} consistent."""
    raise HTTPException(status_code=status_code, detail={"detail": detail, "code": code})


def _get_adapter_or_http_error(venue: str):
    """
    Retorna l'adapter per venue o llança HTTPException.
    - 503 + ADAPTER_NOT_AVAILABLE: adapter_factory no configurat (server no wired)
    - 422 + VENUE_NOT_CONFIGURED: venue no configurat / no suportat
    """
    if _adapter_factory is None:
        _http_error(
            503,
            "ADAPTER_NOT_AVAILABLE",
            "adapter_factory not configured (VENUE=...). Set VENUE=lighter to enable.",
        )
    adapter = _adapter_factory(venue)
    if adapter is None:
        available = _get_available_venues()
        _http_error(
            422,
            "VENUE_NOT_CONFIGURED",
            f"venue not configured: {venue}. Available: {available}",
        )
    return adapter


def _get_available_venues() -> list[str]:
    """Venues disponibles. Només lighter per ara."""
    if _adapter_factory is None:
        return []
    if _adapter_factory("lighter") is not None:
        return ["lighter"]
    return []


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
        _http_error(404, "SYMBOL_NOT_FOUND", str(e))
    except Exception as e:
        logger.error("get_price_latest %s %s: %s", venue, symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


def _read_candles_response(
    symbol: str,
    limit: int,
    since: Optional[int],
    to: Optional[int],
    validate_gaps: bool = True,
) -> OHLCVResponse:
    """Lògica compartida per candles/ohlcv."""
    store = _require_candle_store()
    symbol = _normalize_symbol(symbol)
    tz = ZoneInfo("America/New_York")
    end = datetime.now(tz)
    start, end = resolve_candle_range(end=end, limit=limit, since_epoch=since, to_epoch=to, tz=tz)
    r = read_candles(store, symbol=symbol, start=start, end=end, validate_gaps=validate_gaps)
    return _map_ohlcv_response(r, symbol, start, end)


@router.get("/ohlcv/{symbol}", response_model=OHLCVResponse)
async def get_ohlcv(
    symbol: str,
    tf: str = Query(default="1m"),
    since: Optional[int] = Query(None),
    to: Optional[int] = Query(None),
    limit: int = Query(default=1000, ge=1, le=10000),
):
    """Candles OHLCV per símbol (path). Compatible amb test_rest_smoke."""
    if tf != "1m":
        _http_error(422, "TIMEFRAME_NOT_SUPPORTED", "Only 1m timeframe supported")
    try:
        return _read_candles_response(symbol, limit, since, to, validate_gaps=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_ohlcv %s: %s", symbol, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candles", response_model=OHLCVResponse)
async def get_candles(
    symbol: str = Query(...),
    timeframe: str = Query(default="1m"),
    limit: int = Query(default=100, ge=1, le=10000),
    since: Optional[int] = Query(None),
    to: Optional[int] = Query(None),
):
    """Candles OHLCV (query param symbol). Sense venue (candle_store)."""
    if timeframe != "1m":
        _http_error(422, "TIMEFRAME_NOT_SUPPORTED", "Only 1m timeframe supported")
    try:
        return _read_candles_response(symbol, limit, since, to, validate_gaps=True)
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
    """Posicions obertes."""
    adapter = _get_adapter_or_http_error(venue)
    try:
        positions = await adapter.get_open_positions()
        return _map_positions_response(venue, positions)
    except Exception as e:
        logger.error("get_positions %s: %s", venue, e)
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
        return OrderOpenResponse(
            success=result.success,
            position_id=result.position_id or "",
            order_id=result.order_id or "",
            executed_price=result.executed_price or 0,
            executed_size=result.executed_size or 0,
            tx_hash=getattr(result, "tx_hash", "") or "",
        )
    except MarketNotFoundError as e:
        _http_error(404, "SYMBOL_NOT_FOUND", str(e))
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
        _http_error(404, "POSITION_NOT_FOUND", str(e))
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
        _http_error(503, "CANDLE_STORE_NOT_AVAILABLE", "Candle store not available")
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
        timeframe="1m",
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


def _map_positions_response(venue: str, positions: list) -> PositionsResponse:
    """Mapa llista Position domain a PositionsResponse."""
    items = [
        PositionItem(
            position_id=f"{venue}:{p.pair_id}",
            symbol=p.symbol,
            side="LONG" if p.is_long else "SHORT",
            size=(p.notional or 0) / (p.open_price or 1),
            notional=p.notional or 0,
            open_price=p.open_price,
            entry_time=p.open_time.isoformat() if p.open_time else "",
        )
        for p in positions
    ]
    return PositionsResponse(positions=items)
