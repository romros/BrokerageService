"""
IBrokerageService - Abstract interface for all brokerage implementations

Modes:
- Live: Real trading with Ostium SDK
- Paper: Live data but simulated execution
- Backtest: Historical data with simulated execution
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, AsyncIterator

from domain.models import (


    PriceData,
    Position,
    PositionMetrics,
    OrderRequest,
    OrderResult,
    Balance,
    TradingPair,
    TradeHistory,
)


class IBrokerageService(ABC):
    """
    Abstract brokerage interface

    All methods are async to support both blockchain operations (Ostium)
    and simulated operations (backtest/paper)
    """

    # ============ LIFECYCLE ============

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize brokerage service
        - Live: Connect to blockchain, load wallet
        - Paper: Connect to price feeds
        - Backtest: Load historical data
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Shutdown brokerage service
        - Close connections
        - Cleanup resources
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if service is healthy
        - Live: Check blockchain connection
        - Paper/Backtest: Check data availability
        """
        pass

    # ============ MARKET DATA ============

    @abstractmethod
    async def get_latest_price(self, symbol: str) -> PriceData:
        """
        Get current price with bid/ask/mid

        Args:
            symbol: Trading pair (e.g., "BTC-USD")

        Returns:
            PriceData with bid/ask/mid/timestamp
        """
        pass

    @abstractmethod
    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        """
        Stream real-time prices

        - Live: Poll Ostium API every N seconds
        - Paper: Poll Ostium API every N seconds
        - Backtest: Emit historical data at accelerated speed

        Args:
            symbol: Trading pair

        Yields:
            PriceData updates
        """
        pass

    @abstractmethod
    async def get_pairs(self) -> List[TradingPair]:
        """
        Get list of available trading pairs

        Returns:
            List of TradingPair with metadata
        """
        pass

    # ============ TRADING (MARKET ORDERS) ============

    @abstractmethod
    async def open_market_position(
        self,
        symbol: str,
        is_long: bool,
        collateral: float,
        leverage: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> OrderResult:
        """
        Open market position

        Args:
            symbol: Trading pair (e.g., "BTC-USD")
            is_long: True for long, False for short
            collateral: USDC amount
            leverage: 1-100x
            sl_price: Stop loss price (optional)
            tp_price: Take profit price (optional)

        Returns:
            OrderResult with pair_id, trade_index, success status
        """
        pass

    @abstractmethod
    async def close_position(
        self,
        pair_id: int,
        trade_index: int,
        percent: float = 100.0,
    ) -> bool:
        """
        Close position (full or partial)

        Args:
            pair_id: Pair ID
            trade_index: Trade index
            percent: Percentage to close (default: 100.0 = full close)

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def update_sl(
        self,
        pair_id: int,
        trade_index: int,
        new_sl: float,
    ) -> bool:
        """
        Update stop loss price

        Args:
            pair_id: Pair ID
            trade_index: Trade index
            new_sl: New stop loss price

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def update_tp(
        self,
        pair_id: int,
        trade_index: int,
        new_tp: float,
    ) -> bool:
        """
        Update take profit price

        Args:
            pair_id: Pair ID
            trade_index: Trade index
            new_tp: New take profit price

        Returns:
            True if successful
        """
        pass

    # ============ POSITION MANAGEMENT ============

    @abstractmethod
    async def get_open_positions(self) -> List[Position]:
        """
        Get all open positions

        Returns:
            List of Position objects
        """
        pass

    @abstractmethod
    async def get_position_metrics(
        self,
        pair_id: int,
        trade_index: int,
    ) -> PositionMetrics:
        """
        Get real-time position metrics
        - Unrealized PnL
        - Funding fees
        - Rollover fees
        - Liquidation price

        Args:
            pair_id: Pair ID
            trade_index: Trade index

        Returns:
            PositionMetrics with PnL and fees
        """
        pass

    # ============ ACCOUNT ============

    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        Get account balance

        Returns:
            Balance with USDC and native token amounts
        """
        pass

    @abstractmethod
    async def get_trade_history(
        self,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[TradeHistory]:
        """
        Get closed trade history

        Args:
            limit: Max number of trades to return
            start_date: Filter from date
            end_date: Filter to date

        Returns:
            List of TradeHistory
        """
        pass

    # ============ MODE INFO ============

    @abstractmethod
    def get_mode(self) -> str:
        """
        Get brokerage mode

        Returns:
            "live", "paper", or "backtest"
        """
        pass

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """Check if running in live mode"""
        pass

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """Check if running in paper trading mode"""
        pass

    @property
    @abstractmethod
    def is_backtest(self) -> bool:
        """Check if running in backtest mode"""
        pass
