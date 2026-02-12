"""
IExecutionEngine - Interface for order execution

Implementations:
- PaperExecutionEngine: Simulated execution with configurable slippage/fees
- LiveExecutionEngine: Real execution via venue adapter (future)
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from domain.models import Position, OrderRequest, OrderResult, Balance


class IExecutionEngine(ABC):
    """
    Order execution engine interface

    Responsibilities:
    - Execute orders (market/limit)
    - Manage positions lifecycle
    - Calculate fees and slippage
    - Track balance
    """

    @abstractmethod
    async def open_position(
        self,
        request: OrderRequest,
        client_order_id: str,
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> OrderResult:
        """
        Open a new position

        Args:
            request: Order parameters (symbol, side, size, sl, tp)
            client_order_id: Idempotency key
            current_price: Current market price
            timestamp: Execution timestamp (default: now)

        Returns:
            OrderResult with position_id and execution details
        """
        pass

    @abstractmethod
    async def close_position(
        self,
        position_id: str,
        client_order_id: str,
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> OrderResult:
        """
        Close an existing position

        Args:
            position_id: Position to close
            client_order_id: Idempotency key
            current_price: Current market price
            timestamp: Execution timestamp (default: now)

        Returns:
            OrderResult with PnL and execution details
        """
        pass

    @abstractmethod
    async def update_sl(self, position_id: str, new_sl: Optional[float]) -> None:
        """Update stop loss for a position"""
        pass

    @abstractmethod
    async def update_tp(self, position_id: str, new_tp: Optional[float]) -> None:
        """Update take profit for a position"""
        pass

    @abstractmethod
    async def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID"""
        pass

    @abstractmethod
    async def get_all_positions(self) -> list[Position]:
        """Get all open positions"""
        pass

    @abstractmethod
    async def get_balance(self) -> Balance:
        """Get current account balance"""
        pass

    @abstractmethod
    async def check_stops(self, current_prices: dict[str, float]) -> list[OrderResult]:
        """
        Check if any positions hit stop loss or take profit

        Args:
            current_prices: Dict of symbol -> current price

        Returns:
            List of OrderResults for positions that were closed
        """
        pass
