"""
FastAPI routes - REST endpoints

Implements:
- Core endpoints (health, mode)
- Market data endpoints (ohlcv)
- Trading endpoints (positions, balance)
"""


from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body
from zoneinfo import ZoneInfo

from application.api.models import (


    OHLCVRequest,
    OHLCVResponse,
    OHLCVCandle,
    HealthResponse,
    ModeResponse,
    ErrorResponse,
    OpenPositionRequest,
    OpenPositionResponse,
    ClosePositionRequest,
    ClosePositionResponse,
    UpdateSLRequest,
    UpdateTPRequest,
    PositionResponse,
    PositionsListResponse,
    BalanceResponse,
)
from domain.interfaces import ICandleStore, IExecutionEngine
from domain.models import OrderRequest, OrderSide
from infrastructure.storage.idempotency_store import IdempotencyStore
from foundation.logging import get_logger

logger = get_logger(__name__)

# Router
router = APIRouter()


# ============ DEPENDENCY INJECTION ============
# These will be injected by main.py
_candle_store: Optional[ICandleStore] = None
_execution_engine: Optional[IExecutionEngine] = None
_idempotency_store: Optional[IdempotencyStore] = None
_mode: str = "backtest"  # Default mode
_venue: str = "gtrade"  # Default venue


def set_dependencies(
    candle_store: ICandleStore,
    execution_engine: Optional[IExecutionEngine] = None,
    idempotency_store: Optional[IdempotencyStore] = None,
    mode: str = "backtest",
    venue: str = "gtrade",
) -> None:
    """
    Set dependencies for routes

    Called by main.py during app initialization
    """
    global _candle_store, _execution_engine, _idempotency_store, _mode, _venue
    _candle_store = candle_store
    _execution_engine = execution_engine
    _idempotency_store = idempotency_store
    _mode = mode
    _venue = venue
    logger.info(f"API dependencies set: mode={mode}, venue={venue}, trading_enabled={execution_engine is not None}")


# ============ CORE ENDPOINTS ============

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint

    Returns service status and basic info
    """
    # For now, simple health check
    # Future: check venue adapter, storage, etc.
    return HealthResponse(
        status="ok",
        mode=_mode,
        venue=_venue,
        timestamp=datetime.now(),
    )


@router.get("/mode", response_model=ModeResponse)
async def get_mode():
    """
    Get current mode information
    """
    return ModeResponse(
        mode=_mode,
        is_live=(_mode == "live"),
        is_paper=(_mode == "paper"),
        is_backtest=(_mode == "backtest"),
        venue=_venue,
    )


# ============ MARKET DATA ENDPOINTS ============

@router.get("/ohlcv/{symbol}", response_model=OHLCVResponse)
async def get_ohlcv(
    symbol: str,
    tf: str = Query(default="1m", description="Timeframe (only '1m' supported)"),
    since: Optional[int] = Query(default=None, description="Start timestamp (epoch seconds)"),
    to: Optional[int] = Query(default=None, description="End timestamp (epoch seconds)"),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max candles to return"),
):
    """
    Get OHLCV candles for symbol

    Args:
        symbol: Trading pair (e.g., "XAUUSD", "EURUSD")
        tf: Timeframe (only "1m" supported in MVP)
        since: Start timestamp in epoch seconds (inclusive)
        to: End timestamp in epoch seconds (exclusive)
        limit: Maximum number of candles to return

    Returns:
        OHLCV data with completeness info

    Notes:
        - Returns candles in canonical timezone (America/New_York)
        - Guarantees no gaps within returned range (or flags incomplete=true)
        - If range not specified, returns last 'limit' candles
    """
    if _candle_store is None:
        raise HTTPException(status_code=500, detail="Candle store not initialized")

    # Validate timeframe
    if tf != "1m":
        raise HTTPException(
            status_code=400,
            detail=f"Only '1m' timeframe supported, got '{tf}'"
        )

    # Normalize symbol (uppercase)
    symbol = symbol.upper()

    # Canonical timezone
    canonical_tz = ZoneInfo("America/New_York")

    # Determine time range
    if to is not None:
        end = datetime.fromtimestamp(to, tz=canonical_tz)
    else:
        end = datetime.now(canonical_tz)

    if since is not None:
        start = datetime.fromtimestamp(since, tz=canonical_tz)
    else:
        # Default: last 'limit' minutes
        start = end - timedelta(minutes=limit)

    # Validate range
    total_minutes = int((end - start).total_seconds() / 60)
    if total_minutes > limit:
        # Truncate to limit
        start = end - timedelta(minutes=limit)

    logger.info(f"OHLCV request: {symbol} [{start} to {end}] (limit={limit})")

    try:
        # Read from store
        candle_range = _candle_store.read_range(
            symbol=symbol,
            start=start,
            end=end,
            validate_gaps=True,
        )

        # Convert to API response
        api_candles = [
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
            timeframe=tf,
            start=start,
            end=end,
            count=len(api_candles),
            is_complete=candle_range.is_complete,
            missing_count=candle_range.missing_count,
            candles=api_candles,
        )

    except Exception as e:
        logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============ TRADING ENDPOINTS ============


@router.post("/positions", response_model=OpenPositionResponse)
async def open_position(request: OpenPositionRequest = Body(...)):
    """
    Open a new position

    Args:
        request: Position parameters with client_order_id for idempotency

    Returns:
        Position details with execution info

    Notes:
        - Idempotent: duplicate client_order_id returns cached result
        - Paper mode: simulated execution with slippage/fees
        - Requires current market price (uses latest candle close)
    """
    if _execution_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Trading not available in current mode (execution engine not initialized)"
        )

    if _idempotency_store is None:
        raise HTTPException(status_code=500, detail="Idempotency store not initialized")

    # Check for duplicate request
    cached_result = _idempotency_store.get(request.client_order_id)
    if cached_result is not None:
        logger.info(f"Idempotent request hit: {request.client_order_id}")
        return cached_result

    # Validate side
    try:
        side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid side: {request.side} (must be 'buy' or 'sell')")

    # Get current market price from latest candle
    symbol = request.symbol.upper()
    try:
        last_ts = _candle_store.get_last_timestamp(symbol)
        if last_ts is None:
            raise HTTPException(status_code=404, detail=f"No market data for {symbol}")

        # Read last candle
        canonical_tz = ZoneInfo("America/New_York")
        candle_range = _candle_store.read_range(
            symbol=symbol,
            start=last_ts,
            end=last_ts + timedelta(minutes=1),
            validate_gaps=False,
        )

        if not candle_range.candles:
            raise HTTPException(status_code=404, detail=f"No recent price data for {symbol}")

        current_price = candle_range.candles[0].close

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get current price for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get market price: {e}")

    # Create order request
    order_request = OrderRequest(
        symbol=symbol,
        side=side,
        collateral=request.collateral,
        leverage=request.leverage,
        sl_price=request.sl_price,
        tp_price=request.tp_price,
    )

    # Execute order
    try:
        result = await _execution_engine.open_position(
            request=order_request,
            client_order_id=request.client_order_id,
            current_price=current_price,
        )

        if not result.success:
            raise HTTPException(status_code=400, detail=result.error_message or "Order execution failed")

        # Build API response
        response = OpenPositionResponse(
            success=True,
            position_id=result.position_id,
            executed_price=result.executed_price,
            executed_size=result.executed_size,
            fee=result.fee,
            slippage=result.slippage,
            fees_breakdown=result.fees_breakdown,
            timestamp=result.timestamp,
        )

        # Cache result for idempotency
        _idempotency_store.set(request.client_order_id, response)

        logger.info(f"✓ Position opened: {result.position_id} ({request.client_order_id})")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open position: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=PositionsListResponse)
async def get_positions():
    """
    Get all open positions

    Returns:
        List of open positions with current PnL
    """
    if _execution_engine is None:
        raise HTTPException(status_code=503, detail="Trading not available")

    try:
        positions = await _execution_engine.get_all_positions()

        # Convert to API response
        api_positions = []
        for pos in positions:
            # Calculate unrealized PnL
            price_diff = pos.current_price - pos.open_price
            if not pos.is_long:
                price_diff = -price_diff

            unrealized_pnl = price_diff * pos.leverage * pos.collateral / pos.open_price
            unrealized_pnl_percent = (unrealized_pnl / pos.collateral) * 100

            api_positions.append(
                PositionResponse(
                    position_id=pos.position_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    collateral=pos.collateral,
                    leverage=pos.leverage,
                    notional=pos.notional,
                    open_price=pos.open_price,
                    current_price=pos.current_price,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_percent=unrealized_pnl_percent,
                    sl_price=pos.sl_price,
                    tp_price=pos.tp_price,
                    open_time=pos.open_time,
                )
            )

        return PositionsListResponse(
            count=len(api_positions),
            positions=api_positions,
        )

    except Exception as e:
        logger.error(f"Failed to fetch positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/positions/{position_id}", response_model=ClosePositionResponse)
async def close_position(position_id: str, request: ClosePositionRequest = Body(...)):
    """
    Close an existing position

    Args:
        position_id: Position to close
        request: Contains client_order_id for idempotency

    Returns:
        Close result with realized PnL
    """
    if _execution_engine is None:
        raise HTTPException(status_code=503, detail="Trading not available")

    if _idempotency_store is None:
        raise HTTPException(status_code=500, detail="Idempotency store not initialized")

    # Check for duplicate request
    cached_result = _idempotency_store.get(request.client_order_id)
    if cached_result is not None:
        logger.info(f"Idempotent request hit: {request.client_order_id}")
        return cached_result

    # Get position to determine symbol
    position = await _execution_engine.get_position(position_id)
    if position is None:
        raise HTTPException(status_code=404, detail=f"Position {position_id} not found")

    # Get current market price
    try:
        last_ts = _candle_store.get_last_timestamp(position.symbol)
        if last_ts is None:
            raise HTTPException(status_code=404, detail=f"No market data for {position.symbol}")

        candle_range = _candle_store.read_range(
            symbol=position.symbol,
            start=last_ts,
            end=last_ts + timedelta(minutes=1),
            validate_gaps=False,
        )

        if not candle_range.candles:
            raise HTTPException(status_code=404, detail=f"No recent price data for {position.symbol}")

        current_price = candle_range.candles[0].close

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get current price for {position.symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get market price: {e}")

    # Close position
    try:
        result = await _execution_engine.close_position(
            position_id=position_id,
            client_order_id=request.client_order_id,
            current_price=current_price,
        )

        if not result.success:
            raise HTTPException(status_code=400, detail=result.error_message or "Close order failed")

        # Build API response
        response = ClosePositionResponse(
            success=True,
            position_id=result.position_id,
            executed_price=result.executed_price,
            fee=result.fee,
            realized_pnl=result.realized_pnl,
            realized_pnl_percent=result.realized_pnl_percent,
            pnl_gross=result.pnl_gross,
            pnl_gross_percent=result.pnl_gross_percent,
            fees_breakdown=result.fees_breakdown,
            timestamp=result.timestamp,
        )

        # Cache result for idempotency
        _idempotency_store.set(request.client_order_id, response)

        logger.info(f"✓ Position closed: {result.position_id} ({request.client_order_id})")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close position: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/positions/{position_id}/sl")
async def update_stop_loss(position_id: str, request: UpdateSLRequest = Body(...)):
    """
    Update stop loss for a position

    Args:
        position_id: Position to update
        request: New stop loss price (null to remove)

    Returns:
        Success message
    """
    if _execution_engine is None:
        raise HTTPException(status_code=503, detail="Trading not available")

    try:
        await _execution_engine.update_sl(position_id, request.sl_price)
        return {"success": True, "position_id": position_id, "sl_price": request.sl_price}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update SL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/positions/{position_id}/tp")
async def update_take_profit(position_id: str, request: UpdateTPRequest = Body(...)):
    """
    Update take profit for a position

    Args:
        position_id: Position to update
        request: New take profit price (null to remove)

    Returns:
        Success message
    """
    if _execution_engine is None:
        raise HTTPException(status_code=503, detail="Trading not available")

    try:
        await _execution_engine.update_tp(position_id, request.tp_price)
        return {"success": True, "position_id": position_id, "tp_price": request.tp_price}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update TP: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance", response_model=BalanceResponse)
async def get_balance():
    """
    Get account balance

    Returns:
        Current balance with margin usage
    """
    if _execution_engine is None:
        raise HTTPException(status_code=503, detail="Trading not available")

    try:
        balance = await _execution_engine.get_balance()

        return BalanceResponse(
            usdc=balance.usdc,
            available_margin=balance.available_margin,
            used_margin=balance.used_margin,
            total_equity=balance.total_equity,
            margin_usage_percent=balance.margin_usage_percent,
        )

    except Exception as e:
        logger.error(f"Failed to fetch balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))
