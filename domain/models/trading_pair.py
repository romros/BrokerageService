"""
Trading pair model
"""


from dataclasses import dataclass
from typing import Optional



@dataclass
class TradingPair:
    """Trading pair information"""
    pair_id: int
    symbol: str  # e.g., "BTC-USD"
    base: str  # e.g., "BTC"
    quote: str  # e.g., "USD"
    min_leverage: float
    max_leverage: Optional[float]  # None if not available from venue (e.g., Lighter)
    maker_fee_percent: float
    taker_fee_percent: float
    is_market_open: bool = True
    overnight_max_leverage: Optional[float] = None  # For stocks
