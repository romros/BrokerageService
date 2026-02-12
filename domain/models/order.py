"""
Order models
"""


from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Dict


class OrderType(str, Enum):
    """Order type"""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderSide(str, Enum):
    """Order side (direction)"""
    BUY = "buy"  # Long
    SELL = "sell"  # Short


@dataclass
class OrderRequest:
    """Request to open a position"""
    symbol: str
    side: OrderSide
    collateral: float  # USDC amount
    leverage: float  # 1-100x
    order_type: OrderType = OrderType.MARKET
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    limit_price: Optional[float] = None  # For limit orders
    stop_price: Optional[float] = None  # For stop orders


@dataclass
class OrderResult:
    """Result of order execution (open/close position)"""
    success: bool
    position_id: str  # Format: "{pair_id}:{trade_index}" or "paper_{uuid}"
    order_id: Optional[str] = None

    # Execution details
    executed_price: Optional[float] = None
    executed_size: Optional[float] = None  # Notional value
    fee: Optional[float] = None
    slippage: Optional[float] = None  # In basis points

    # PnL (for close orders)
    realized_pnl: Optional[float] = None  # Net PnL (after fees)
    realized_pnl_percent: Optional[float] = None  # Net PnL %
    pnl_gross: Optional[float] = None  # Gross PnL (before fees)
    pnl_gross_percent: Optional[float] = None  # Gross PnL %

    # Fee breakdown (detailed costs)
    fees_breakdown: Optional[Dict[str, float]] = None

    # Blockchain-specific (gTrade live mode)
    tx_hash: Optional[str] = None

    # Error handling
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    @property
    def pair_id(self) -> Optional[int]:
        """Extract pair_id from position_id (backward compatibility)"""
        if ":" in self.position_id:
            try:
                return int(self.position_id.split(":")[0])
            except ValueError:
                return None
        return None

    @property
    def trade_index(self) -> Optional[int]:
        """Extract trade_index from position_id (backward compatibility)"""
        if ":" in self.position_id:
            try:
                return int(self.position_id.split(":")[1])
            except ValueError:
                return None
        return None
