"""
Position models
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING


if TYPE_CHECKING:
    # TYPE_CHECKING: evita circular position ↔ position_ref (només per type hints)
    from .position_ref import PositionRef


@dataclass
class Position:
    """Open position"""
    pair_id: int
    trade_index: int
    symbol: str
    is_long: bool  # True=Long, False=Short
    collateral: float
    leverage: float
    open_price: float
    current_price: float
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    open_time: datetime = None
    notional: Optional[float] = None  # Position size in USD
    wallet_address: Optional[str] = None  # Trader wallet (for PositionRef)
    venue_position_id: Optional[str] = None  # ID venue-specific (ex. paper_xxx); si set, s'usa per close
    # De Lighter AccountApi.account(): mark_price i unrealized_pnl oficials (eviten discrepància vs web)
    mark_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None

    @property
    def side(self) -> str:
        return "LONG" if self.is_long else "SHORT"

    @property
    def position_id(self) -> str:
        """Unique position identifier"""
        if self.venue_position_id:
            return self.venue_position_id
        return f"{self.pair_id}:{self.trade_index}"

    def get_ref(self) -> Optional["PositionRef"]:
        """
        Get canonical position reference

        Returns None if wallet_address is not set.
        """
        if not self.wallet_address:
            return None

        # Lazy: evita circular position ↔ position_ref (runtime)
        from .position_ref import PositionRef
        return PositionRef(
            wallet_address=self.wallet_address,
            pair_id=self.pair_id,
            trade_index=self.trade_index,
        )

    def __post_init__(self):
        if self.open_time is None:
            self.open_time = datetime.utcnow()
        if self.notional is None:
            self.notional = self.collateral * self.leverage


@dataclass
class PositionMetrics:
    """Real-time position metrics"""
    position_id: str
    unrealized_pnl: float
    unrealized_pnl_percent: float
    funding_fee: float
    rollover_fee: float
    liquidation_price: float
    current_price: float
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
