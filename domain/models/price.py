"""
Price data models
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional



@dataclass
class PriceData:
    """Price data with bid/ask/mid"""
    symbol: str
    bid: float
    ask: float
    mid: float
    timestamp: datetime

    @property
    def spread(self) -> float:
        """Calculate spread (ask - bid)"""
        return self.ask - self.bid

    @property
    def spread_percent(self) -> float:
        """Calculate spread as percentage of mid price"""
        if self.mid == 0:
            return 0.0
        return (self.spread / self.mid) * 100


@dataclass

@dataclass
class Tick:
    """Single price tick (for building candles)"""
    symbol: str
    price: float
    timestamp: datetime
    volume: Optional[float] = None
