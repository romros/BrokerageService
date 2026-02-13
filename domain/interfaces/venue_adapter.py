"""
IVenueAdapter - Abstract interface for venue implementations

Responsibilities:
- Market data (ticker/mark)
- Trading operations (open/close positions)
- Account info (balance, positions, history)
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


class IVenueAdapter(ABC):
    """
    Abstract venue adapter interface

    All methods are async to support:
    - Blockchain operations (Lighter, etc.)
    - REST/WebSocket APIs
    - Simulated operations (backtest/paper)
    """

    # ============ LIFECYCLE ============

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize venue adapter
        - Connect to venue API/blockchain
        - Load configuration
        - Start background tasks (reconnect, reconcile, etc.)
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Shutdown venue adapter
        - Close connections
        - Cleanup resources
        - Stop background tasks
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if adapter is healthy
        - Connection status
        - Data availability
        - Account accessibility
        """
        pass

    # ============ MARKET DATA ============

    @abstractmethod
    async def get_latest_price(self, symbol: str) -> PriceData:
        """
        Get current ticker/mark price

        Args:
            symbol: Trading pair (e.g., "XAUUSD", "EURUSD", "BTC-USD")

        Returns:
            PriceData with bid/ask/mid/timestamp
        """
        pass

    @abstractmethod
    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        """
        Stream real-time prices

        Implementation varies by mode:
        - LIVE: Poll or WebSocket from venue
        - PAPER: Same as LIVE
        - BACKTEST: Emit historical data at accelerated speed

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
            List of TradingPair with metadata (leverage, precision, etc.)
        """
        pass

    # ============ TRADING (POSITION-BASED) ============

    @abstractmethod
    async def open_position(
        self,
        symbol: str,
        is_long: bool,
        collateral: float,
        leverage: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResult:
        """
        Open market position

        Args:
            symbol: Trading pair
            is_long: True for long, False for short
            collateral: Collateral amount (USDC)
            leverage: Leverage multiplier
            sl_price: Stop loss price (optional)
            tp_price: Take profit price (optional)
            client_order_id: Idempotency key (optional)

        Returns:
            OrderResult with position_id, success status
        """
        pass

    @abstractmethod
    async def close_position(
        self,
        position_id: str,
        percent: float = 100.0,
    ) -> bool:
        """
        Close position (full or partial)

        Args:
            position_id: Position identifier (venue-specific format)
            percent: Percentage to close (default: 100.0 = full close)

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def update_sl(
        self,
        position_id: str,
        new_sl: float,
    ) -> bool:
        """
        Update stop loss price

        Args:
            position_id: Position identifier
            new_sl: New stop loss price

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def update_tp(
        self,
        position_id: str,
        new_tp: float,
    ) -> bool:
        """
        Update take profit price

        Args:
            position_id: Position identifier
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
        position_id: str,
    ) -> PositionMetrics:
        """
        Get real-time position metrics

        Args:
            position_id: Position identifier

        Returns:
            PositionMetrics with PnL, fees, liquidation price
        """
        pass

    # ============ ACCOUNT ============

    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        Get account balance

        Returns:
            Balance with available funds and margin info
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
        Get adapter mode

        Returns:
            "live", "paper", or "backtest"
        """
        pass

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """Check if running in live mode (real money)"""
        pass

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """Check if running in paper trading mode (simulated execution)"""
        pass

    @property
    @abstractmethod
    def is_backtest(self) -> bool:
        """Check if running in backtest mode (historical data)"""
        pass

    @property
    @abstractmethod
    def venue_name(self) -> str:
        """
        Get venue name

        Returns:
            Venue identifier (e.g., "lighter")
        """
        pass
