"""
Trade fill model (CCXT/Freqtrade style)

Individual execution/fill per trade. Usat per trade history i reconciliació.
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional


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
