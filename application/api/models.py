"""
API request/response models (Pydantic)

These are API-specific models that map to/from domain models.
"""


from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, Field, field_validator


class OHLCVRequest(BaseModel):
    """Request parameters for /ohlcv endpoint"""
    tf: str = Field(default="1m", description="Timeframe (only '1m' supported)")
    since: Optional[datetime] = Field(default=None, description="Start timestamp (inclusive)")
    to: Optional[datetime] = Field(default=None, description="End timestamp (exclusive)")
    limit: int = Field(default=1000, ge=1, le=10000, description="Max candles to return")


class OHLCVCandle(BaseModel):
    """Single OHLCV candle (API response)"""
    ts: int = Field(description="Timestamp (epoch seconds)")
    open: float
    high: float
    low: float
    close: float
    volume: float


class OHLCVResponse(BaseModel):
    """Response for /ohlcv endpoint"""
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    count: int
    is_complete: bool = Field(description="True if no gaps in range")
    missing_count: int = Field(default=0, description="Number of missing candles")
    candles: List[OHLCVCandle]


class HealthResponse(BaseModel):
    """Response for /health endpoint"""
    status: str  # "ok" | "degraded" | "error"
    mode: str  # "live" | "paper" | "backtest"
    venue: str  # "lighter" | etc.
    timestamp: datetime


class ModeResponse(BaseModel):
    """Response for /mode endpoint"""
    mode: str
    is_live: bool
    is_paper: bool
    is_backtest: bool
    venue: str


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime


# ============ TRADING MODELS ============


class OpenPositionRequest(BaseModel):
    """Request to open a position"""
    client_order_id: str = Field(description="Idempotency key (required)")
    symbol: str = Field(description="Trading pair (e.g., XAUUSD)")
    side: str = Field(description="'buy' (long) or 'sell' (short)")
    collateral: float = Field(gt=0, description="USDC collateral amount")
    leverage: float = Field(ge=1, le=100, description="Leverage (1-100x)")
    sl_price: Optional[float] = Field(default=None, description="Stop loss price")
    tp_price: Optional[float] = Field(default=None, description="Take profit price")


class OpenPositionResponse(BaseModel):
    """Response for opening a position"""
    success: bool
    position_id: str
    executed_price: float
    executed_size: float  # Notional value
    fee: float
    slippage: float  # In basis points
    fees_breakdown: Optional[Dict[str, float]] = Field(
        default=None,
        description="Detailed fee breakdown (spread_cost, open_fee, price_impact_cost, total_entry_cost)"
    )
    timestamp: datetime


class ClosePositionRequest(BaseModel):
    """Request to close a position"""
    client_order_id: str = Field(description="Idempotency key (required)")


class ClosePositionResponse(BaseModel):
    """Response for closing a position"""
    success: bool
    position_id: str
    executed_price: float
    fee: float
    realized_pnl: float  # Net PnL (after fees)
    realized_pnl_percent: float  # Net PnL %
    pnl_gross: Optional[float] = Field(
        default=None,
        description="Gross PnL before fees"
    )
    pnl_gross_percent: Optional[float] = Field(
        default=None,
        description="Gross PnL % before fees"
    )
    fees_breakdown: Optional[Dict[str, float]] = Field(
        default=None,
        description="Detailed fee breakdown (close_fee, borrowing_cost, total_exit_cost)"
    )
    timestamp: datetime


class UpdateSLRequest(BaseModel):
    """Request to update stop loss"""
    sl_price: Optional[float] = Field(description="New stop loss price (null to remove)")


class UpdateTPRequest(BaseModel):
    """Request to update take profit"""
    tp_price: Optional[float] = Field(description="New take profit price (null to remove)")


class PositionResponse(BaseModel):
    """Single position (API response)"""
    position_id: str
    symbol: str
    side: str  # "LONG" | "SHORT"
    collateral: float
    leverage: float
    notional: float
    open_price: float
    current_price: float
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_percent: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    open_time: datetime


class PositionsListResponse(BaseModel):
    """Response for listing positions"""
    count: int
    positions: List[PositionResponse]


class BalanceResponse(BaseModel):
    """Response for account balance"""
    usdc: float
    available_margin: float
    used_margin: float
    total_equity: float
    margin_usage_percent: float


# ============ BROKER API REQUEST MODELS (canònic) ============


class OrderOpenRequest(BaseModel):
    """Request per POST /orders/open"""
    venue: str = Field(description="Venue (lighter)")
    symbol: str = Field(description="Símbol (ex: ETH)")
    side: str = Field(description="long o short")
    collateral: float = Field(gt=0, description="USDC collateral")
    leverage: float = Field(ge=1, le=100, description="Leverage 1-100")
    sl_price: Optional[float] = Field(default=None, description="Stop loss price")
    tp_price: Optional[float] = Field(default=None, description="Take profit price")

    @field_validator("side")
    @classmethod
    def side_must_be_long_or_short(cls, v: str) -> str:
        s = v.lower()
        if s not in ("long", "short"):
            raise ValueError("side must be long or short")
        return s


class OrderCloseRequest(BaseModel):
    """Request per POST /orders/close"""
    venue: str = Field(description="Venue (lighter)")
    position_id: str = Field(description="ID de la posició (ex: lighter:0)")
    percent: float = Field(default=100.0, gt=0, le=100, description="Percentatge (0, 100]")
