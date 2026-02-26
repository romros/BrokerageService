"""
Trade fill model (CCXT/Freqtrade style)

Individual execution/fill per trade. Usat per trade history i reconciliació.
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# P3.0: close_reason per trade history
CLOSE_REASON_MANUAL = "manual"
CLOSE_REASON_STOP_LOSS = "stop_loss"
CLOSE_REASON_TAKE_PROFIT = "take_profit"
CLOSE_REASON_LIQUIDATION = "liquidation"
CLOSE_REASON_TTL = "ttl"  # T7.1: forçar close per temps (time-to-live)


@dataclass
class TradeFill:
    """Individual trade fill (execution) — CCXT/Freqtrade compatible"""
    trade_id: str
    symbol: str
    side: str  # "buy" | "sell" (normalitzat des de long/short)
    price: float
    size: float
    fee: float = 0.0
    fee_currency: Optional[str] = None
    timestamp: Optional[datetime] = None
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    # P3.0: close_reason per trade history (manual|stop_loss|take_profit|liquidation)
    close_reason: Optional[str] = None
    open_ts: Optional[datetime] = None
    close_ts: Optional[datetime] = None
    open_price: Optional[float] = None
    close_price: Optional[float] = None
