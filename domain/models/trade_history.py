"""
Trade history model
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional



@dataclass
class TradeHistory:
    """Closed trade history"""
    trade_id: str
    pair_id: int
    trade_index: int
    symbol: str
    is_long: bool
    collateral: float
    leverage: float
    open_price: float
    close_price: float
    open_time: datetime
    close_time: datetime
    pnl: float  # Profit/Loss in USDC
    pnl_percent: float  # Profit/Loss percentage
    funding_fee: float
    rollover_fee: float
    total_fees: float
    close_reason: str  # "manual", "tp", "sl", "liquidation"
    tx_hash: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        """Trade duration in seconds"""
        return (self.close_time - self.open_time).total_seconds()

    @property
    def duration_hours(self) -> float:
        """Trade duration in hours"""
        return self.duration_seconds / 3600

    @property
    def net_pnl(self) -> float:
        """Net PnL after fees"""
        return self.pnl - self.total_fees
